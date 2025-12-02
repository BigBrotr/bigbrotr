"""
Database Interface for BigBrotr.

High-level interface for database operations using stored procedures.

Features:
- Stored procedure wrappers for event/relay operations
- Bulk insert optimization via executemany
- Batch operations with configurable limits
- Hex to bytea conversion for efficient storage
- Structured logging
- Parallel cleanup operations
"""

import asyncio
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
    """Operation timeouts for Brotr."""

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

        Returns:
            Result value if fetch_result=True, otherwise None
        """
        params = ", ".join(f"${i + 1}" for i in range(len(args))) if args else ""
        query = f"SELECT {procedure_name}({params})"
        timeout_value = timeout or self._config.timeouts.procedure

        async def execute(c: asyncpg.Connection) -> Any:
            if fetch_result:
                result = await c.fetchval(query, *args, timeout=timeout_value)
                return result or 0
            await c.execute(query, *args, timeout=timeout_value)
            return None

        if conn is not None:
            return await execute(conn)

        async with self.pool.acquire() as acquired_conn:
            return await execute(acquired_conn)

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
            params = [(r["url"], r["network"], r["inserted_at"]) for r in relays]

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

        def extract_params(m: dict[str, Any]) -> tuple[Any, ...]:
            """Extract parameters from metadata dict for stored procedure call."""
            # Cache dict lookups for efficiency and readability
            nip66 = m.get("nip66") or {}
            nip11 = m.get("nip11") or {}
            has_nip66 = bool(m.get("nip66"))
            has_nip11 = bool(m.get("nip11"))

            return (
                # Base relay info
                m["relay_url"],
                m["relay_network"],
                m["relay_inserted_at"],
                m["generated_at"],
                # NIP-66 fields
                has_nip66,
                nip66.get("openable") if has_nip66 else None,
                nip66.get("readable") if has_nip66 else None,
                nip66.get("writable") if has_nip66 else None,
                nip66.get("rtt_open") if has_nip66 else None,
                nip66.get("rtt_read") if has_nip66 else None,
                nip66.get("rtt_write") if has_nip66 else None,
                # NIP-11 fields
                has_nip11,
                nip11.get("name") if has_nip11 else None,
                nip11.get("description") if has_nip11 else None,
                nip11.get("banner") if has_nip11 else None,
                nip11.get("icon") if has_nip11 else None,
                nip11.get("pubkey") if has_nip11 else None,
                nip11.get("contact") if has_nip11 else None,
                to_jsonb(nip11.get("supported_nips")) if has_nip11 else None,
                nip11.get("software") if has_nip11 else None,
                nip11.get("version") if has_nip11 else None,
                nip11.get("privacy_policy") if has_nip11 else None,
                nip11.get("terms_of_service") if has_nip11 else None,
                to_jsonb(nip11.get("limitation")) if has_nip11 else None,
                to_jsonb(nip11.get("extra_fields")) if has_nip11 else None,
            )

        async with self.pool.transaction() as conn:
            params = [extract_params(m) for m in metadata_list]

            await conn.executemany(
                f"SELECT {PROC_INSERT_RELAY_METADATA}("
                "$1, $2, $3, $4, $5, $6, $7, $8, $9, $10, "
                "$11, $12, $13, $14, $15, $16, $17, $18, $19, $20, "
                "$21, $22, $23, $24, $25)",
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
        Delete all orphaned records in parallel.

        Runs all three cleanup operations concurrently for better performance.

        Returns:
            Dict with counts: {"events": n, "nip11": n, "nip66": n}
        """
        events, nip11, nip66 = await asyncio.gather(
            self.delete_orphan_events(),
            self.delete_orphan_nip11(),
            self.delete_orphan_nip66(),
        )
        result = {"events": events, "nip11": nip11, "nip66": nip66}
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
