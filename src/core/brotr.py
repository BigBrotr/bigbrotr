"""
Database Interface for BigBrotr.

High-level interface for database operations using stored procedures.

Features:
- Stored procedure wrappers for event/relay operations
- Bulk insert optimization via executemany
- Batch operations with configurable limits
- Hex to bytea conversion for efficient storage
- Structured logging
"""

import json
from pathlib import Path
from typing import Any, Final, Optional

import asyncpg
import yaml
from pydantic import BaseModel, Field

from .logger import Logger
from .pool import Pool


# ============================================================================
# Stored Procedure Names (Hardcoded for Security)
# ============================================================================
# These are intentionally not configurable to prevent SQL injection attacks.
# If you need to change procedure names, modify these constants and the
# corresponding SQL files in implementations/bigbrotr/postgres/init/.

PROC_INSERT_EVENT: Final[str] = "insert_event"
PROC_INSERT_RELAY: Final[str] = "insert_relay"
PROC_INSERT_RELAY_METADATA: Final[str] = "insert_relay_metadata"
PROC_DELETE_ORPHAN_EVENTS: Final[str] = "delete_orphan_events"
PROC_DELETE_ORPHAN_NIP11: Final[str] = "delete_orphan_nip11"
PROC_DELETE_ORPHAN_NIP66: Final[str] = "delete_orphan_nip66"


# ============================================================================
# Configuration Models
# ============================================================================


class BatchConfig(BaseModel):
    """Batch operation configuration."""

    max_batch_size: int = Field(
        default=10000,
        ge=1,
        le=100000,
        description="Maximum items per batch operation",
    )


class TimeoutsConfig(BaseModel):
    """Operation timeouts."""

    query: float = Field(default=60.0, ge=0.1, description="Query timeout (seconds)")
    procedure: float = Field(default=90.0, ge=0.1, description="Procedure timeout (seconds)")
    batch: float = Field(default=120.0, ge=0.1, description="Batch timeout (seconds)")


class BrotrConfig(BaseModel):
    """Complete Brotr configuration."""

    batch: BatchConfig = Field(default_factory=BatchConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)


# ============================================================================
# Brotr Class
# ============================================================================


class Brotr:
    """
    High-level database interface.

    Provides stored procedure wrappers and bulk insert operations.
    Uses composition: has a Pool (public property) for all connection operations.
    Implements async context manager for automatic pool lifecycle management.

    Usage:
        brotr = Brotr.from_yaml("config.yaml")

        # Option 1: Use Brotr context manager (recommended)
        async with brotr:
            result = await brotr.pool.fetch("SELECT * FROM events")
            await brotr.insert_events([event1, event2, ...])
            await brotr.insert_relays([relay1, relay2, ...])
            deleted = await brotr.cleanup_orphans()

        # Option 2: Manual pool management (legacy)
        async with brotr.pool:
            await brotr.insert_events([...])
    """

    def __init__(
        self,
        pool: Optional[Pool] = None,
        config: Optional[BrotrConfig] = None,
    ) -> None:
        """
        Initialize Brotr.

        Args:
            pool: Database pool (creates default if not provided)
            config: Brotr configuration (uses defaults if not provided)
        """
        self.pool = pool or Pool()
        self._config = config or BrotrConfig()
        self._logger = Logger("brotr")

    @classmethod
    def from_yaml(cls, config_path: str) -> "Brotr":
        """
        Create Brotr from YAML configuration.

        Expected structure:
            pool:
              database: {...}
              limits: {...}
            batch:
              max_batch_size: 10000
            procedures: {...}
            timeouts: {...}
        """
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with path.open() as f:
            config_data = yaml.safe_load(f) or {}

        return cls.from_dict(config_data)

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> "Brotr":
        """Create Brotr from dictionary configuration."""
        pool = None
        if "pool" in config_dict:
            pool = Pool.from_dict(config_dict["pool"])

        brotr_config_dict = {k: v for k, v in config_dict.items() if k != "pool"}
        config = BrotrConfig(**brotr_config_dict) if brotr_config_dict else None

        return cls(pool=pool, config=config)

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _validate_batch_size(self, batch: list[Any], operation: str) -> None:
        """Validate batch size against maximum."""
        if len(batch) > self._config.batch.max_batch_size:
            raise ValueError(
                f"{operation} batch size ({len(batch)}) exceeds maximum ({self._config.batch.max_batch_size})"
            )

    async def _call_procedure(
        self,
        procedure_name: str,
        *args: Any,
        conn: Optional[asyncpg.Connection] = None,
        fetch_result: bool = False,
        timeout: Optional[float] = None,
    ) -> Any:
        """
        Call a stored procedure.

        Args:
            procedure_name: Procedure name
            *args: Procedure arguments
            conn: Optional connection (acquires from pool if None)
            fetch_result: Return result if True
            timeout: Optional timeout override
        """
        params = ", ".join(f"${i+1}" for i in range(len(args))) if args else ""
        query = f"SELECT {procedure_name}({params})"
        timeout_value = timeout or self._config.timeouts.procedure

        if conn is None:
            async with self.pool.acquire() as acquired_conn:
                if fetch_result:
                    result = await acquired_conn.fetchval(query, *args, timeout=timeout_value)
                    return result or 0
                await acquired_conn.execute(query, *args, timeout=timeout_value)
                return None

        if fetch_result:
            result = await conn.fetchval(query, *args, timeout=timeout_value)
            return result or 0
        await conn.execute(query, *args, timeout=timeout_value)
        return None

    # -------------------------------------------------------------------------
    # Insert Operations
    # -------------------------------------------------------------------------

    async def insert_events(self, events: list[dict[str, Any]]) -> int:
        """
        Insert events atomically using bulk insert.

        Args:
            events: List of event dictionaries

        Returns:
            Number of events inserted

        Raises:
            asyncpg.PostgresError: On database errors
            ValueError: On validation errors (batch size, hex conversion)

        Event format:
            {
                "event_id": "64-char hex",
                "pubkey": "64-char hex",
                "created_at": int,
                "kind": int,
                "tags": [[...], ...],
                "content": "text",
                "sig": "128-char hex",
                "relay_url": "wss://...",
                "relay_network": "clearnet" or "tor",
                "relay_inserted_at": int,
                "seen_at": int
            }
        """
        if not events:
            return 0

        self._validate_batch_size(events, "insert_events")

        async with self.pool.transaction() as conn:
            params = [
                (
                    bytes.fromhex(e["event_id"]),
                    bytes.fromhex(e["pubkey"]),
                    e["created_at"],
                    e["kind"],
                    json.dumps(e["tags"]),
                    e["content"],
                    bytes.fromhex(e["sig"]),
                    e["relay_url"],
                    e["relay_network"],
                    e["relay_inserted_at"],
                    e["seen_at"],
                )
                for e in events
            ]

            await conn.executemany(
                f"SELECT {PROC_INSERT_EVENT}($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
                params,
                timeout=self._config.timeouts.batch,
            )

        self._logger.debug("events_inserted", count=len(events))
        return len(events)

    async def insert_relays(self, relays: list[dict[str, Any]]) -> int:
        """
        Insert relays atomically using bulk insert.

        Args:
            relays: List of relay dictionaries

        Returns:
            Number of relays inserted

        Raises:
            asyncpg.PostgresError: On database errors
            ValueError: On validation errors (batch size)

        Relay format:
            {
                "url": "wss://...",
                "network": "clearnet" or "tor",
                "inserted_at": int
            }
        """
        if not relays:
            return 0

        self._validate_batch_size(relays, "insert_relays")

        async with self.pool.transaction() as conn:
            params = [
                (r["url"], r["network"], r["inserted_at"])
                for r in relays
            ]

            await conn.executemany(
                f"SELECT {PROC_INSERT_RELAY}($1, $2, $3)",
                params,
                timeout=self._config.timeouts.batch,
            )

        self._logger.debug("relays_inserted", count=len(relays))
        return len(relays)

    async def insert_relay_metadata(self, metadata_list: list[dict[str, Any]]) -> int:
        """
        Insert relay metadata atomically using bulk insert.

        Args:
            metadata_list: List of metadata dictionaries

        Returns:
            Number of metadata records inserted

        Raises:
            asyncpg.PostgresError: On database errors
            ValueError: On validation errors (batch size)
        """
        if not metadata_list:
            return 0

        self._validate_batch_size(metadata_list, "insert_relay_metadata")

        def to_jsonb(value: Any) -> Optional[str]:
            """Convert Python object to JSON string for JSONB columns."""
            return json.dumps(value) if value is not None else None

        async with self.pool.transaction() as conn:
            params = [
                (
                    m["relay_url"],
                    m["relay_network"],
                    m["relay_inserted_at"],
                    m["generated_at"],
                    m.get("nip66") is not None,
                    m.get("nip66", {}).get("openable") if m.get("nip66") else None,
                    m.get("nip66", {}).get("readable") if m.get("nip66") else None,
                    m.get("nip66", {}).get("writable") if m.get("nip66") else None,
                    m.get("nip66", {}).get("rtt_open") if m.get("nip66") else None,
                    m.get("nip66", {}).get("rtt_read") if m.get("nip66") else None,
                    m.get("nip66", {}).get("rtt_write") if m.get("nip66") else None,
                    m.get("nip11") is not None,
                    m.get("nip11", {}).get("name") if m.get("nip11") else None,
                    m.get("nip11", {}).get("description") if m.get("nip11") else None,
                    m.get("nip11", {}).get("banner") if m.get("nip11") else None,
                    m.get("nip11", {}).get("icon") if m.get("nip11") else None,
                    m.get("nip11", {}).get("pubkey") if m.get("nip11") else None,
                    m.get("nip11", {}).get("contact") if m.get("nip11") else None,
                    to_jsonb(m.get("nip11", {}).get("supported_nips")) if m.get("nip11") else None,
                    m.get("nip11", {}).get("software") if m.get("nip11") else None,
                    m.get("nip11", {}).get("version") if m.get("nip11") else None,
                    m.get("nip11", {}).get("privacy_policy") if m.get("nip11") else None,
                    m.get("nip11", {}).get("terms_of_service") if m.get("nip11") else None,
                    to_jsonb(m.get("nip11", {}).get("limitation")) if m.get("nip11") else None,
                    to_jsonb(m.get("nip11", {}).get("extra_fields")) if m.get("nip11") else None,
                )
                for m in metadata_list
            ]

            await conn.executemany(
                f"SELECT {PROC_INSERT_RELAY_METADATA}($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25)",
                params,
                timeout=self._config.timeouts.batch,
            )

        self._logger.debug("relay_metadata_inserted", count=len(metadata_list))
        return len(metadata_list)

    # -------------------------------------------------------------------------
    # Cleanup Operations
    # -------------------------------------------------------------------------

    async def delete_orphan_events(self) -> int:
        """Delete orphaned events. Returns count."""
        return await self._call_procedure(
            PROC_DELETE_ORPHAN_EVENTS,
            fetch_result=True,
        )

    async def delete_orphan_nip11(self) -> int:
        """Delete orphaned NIP-11 records. Returns count."""
        return await self._call_procedure(
            PROC_DELETE_ORPHAN_NIP11,
            fetch_result=True,
        )

    async def delete_orphan_nip66(self) -> int:
        """Delete orphaned NIP-66 records. Returns count."""
        return await self._call_procedure(
            PROC_DELETE_ORPHAN_NIP66,
            fetch_result=True,
        )

    async def cleanup_orphans(self) -> dict[str, int]:
        """
        Delete all orphaned records.

        Returns:
            Dict with counts: {"events": n, "nip11": n, "nip66": n}
        """
        result = {
            "events": await self.delete_orphan_events(),
            "nip11": await self.delete_orphan_nip11(),
            "nip66": await self.delete_orphan_nip66(),
        }
        self._logger.info("cleanup_completed", **result)
        return result

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------

    @property
    def config(self) -> BrotrConfig:
        """Get configuration."""
        return self._config

    # -------------------------------------------------------------------------
    # Context Manager (delegates to Pool)
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> "Brotr":
        """
        Async context manager entry - connects the pool.

        Usage:
            async with brotr:
                await brotr.insert_events([...])
        """
        await self.pool.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit - closes the pool."""
        await self.pool.close()

    def __repr__(self) -> str:
        """String representation."""
        db = self.pool.config.database
        return f"Brotr(host={db.host}, database={db.database}, connected={self.pool.is_connected})"