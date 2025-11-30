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

from pathlib import Path
from typing import Any, Optional

import asyncpg
import yaml
from pydantic import BaseModel, Field

from .logger import Logger
from .pool import Pool


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


class StoredProceduresConfig(BaseModel):
    """Stored procedure names."""

    insert_event: str = Field(default="insert_event")
    insert_relay: str = Field(default="insert_relay")
    insert_relay_metadata: str = Field(default="insert_relay_metadata")
    delete_orphan_events: str = Field(default="delete_orphan_events")
    delete_orphan_nip11: str = Field(default="delete_orphan_nip11")
    delete_orphan_nip66: str = Field(default="delete_orphan_nip66")


class TimeoutsConfig(BaseModel):
    """Operation timeouts."""

    query: float = Field(default=60.0, ge=0.1, description="Query timeout (seconds)")
    procedure: float = Field(default=90.0, ge=0.1, description="Procedure timeout (seconds)")
    batch: float = Field(default=120.0, ge=0.1, description="Batch timeout (seconds)")


class BrotrConfig(BaseModel):
    """Complete Brotr configuration."""

    batch: BatchConfig = Field(default_factory=BatchConfig)
    procedures: StoredProceduresConfig = Field(default_factory=StoredProceduresConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)


# ============================================================================
# Brotr Class
# ============================================================================


class Brotr:
    """
    High-level database interface.

    Provides stored procedure wrappers and bulk insert operations.
    Uses composition: has a Pool (public property) for all connection operations.

    Usage:
        brotr = Brotr.from_yaml("config.yaml")

        async with brotr.pool:
            # Pool operations
            result = await brotr.pool.fetch("SELECT * FROM events")

            # Bulk inserts (optimized)
            await brotr.insert_events([event1, event2, ...])
            await brotr.insert_relays([relay1, relay2, ...])

            # Cleanup
            deleted = await brotr.cleanup_orphans()
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
        *args,
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

    async def insert_events(self, events: list[dict[str, Any]]) -> bool:
        """
        Insert events atomically using bulk insert.

        Args:
            events: List of event dictionaries

        Returns:
            True if successful, False on error

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
            return True

        self._validate_batch_size(events, "insert_events")

        try:
            async with self.pool.transaction() as conn:
                params = [
                    (
                        bytes.fromhex(e["event_id"]),
                        bytes.fromhex(e["pubkey"]),
                        e["created_at"],
                        e["kind"],
                        e["tags"],
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
                    f"SELECT {self._config.procedures.insert_event}($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
                    params,
                    timeout=self._config.timeouts.batch,
                )

            self._logger.debug("events_inserted", count=len(events))
            return True

        except (asyncpg.PostgresError, ValueError) as e:
            self._logger.error("insert_events_failed", error=str(e))
            return False

    async def insert_relays(self, relays: list[dict[str, Any]]) -> bool:
        """
        Insert relays atomically using bulk insert.

        Args:
            relays: List of relay dictionaries

        Returns:
            True if successful, False on error

        Relay format:
            {
                "url": "wss://...",
                "network": "clearnet" or "tor",
                "inserted_at": int
            }
        """
        if not relays:
            return True

        self._validate_batch_size(relays, "insert_relays")

        try:
            async with self.pool.transaction() as conn:
                params = [
                    (r["url"], r["network"], r["inserted_at"])
                    for r in relays
                ]

                await conn.executemany(
                    f"SELECT {self._config.procedures.insert_relay}($1, $2, $3)",
                    params,
                    timeout=self._config.timeouts.batch,
                )

            self._logger.debug("relays_inserted", count=len(relays))
            return True

        except (asyncpg.PostgresError, ValueError) as e:
            self._logger.error("insert_relays_failed", error=str(e))
            return False

    async def insert_relay_metadata(self, metadata_list: list[dict[str, Any]]) -> bool:
        """
        Insert relay metadata atomically using bulk insert.

        Args:
            metadata_list: List of metadata dictionaries

        Returns:
            True if successful, False on error
        """
        if not metadata_list:
            return True

        self._validate_batch_size(metadata_list, "insert_relay_metadata")

        try:
            async with self.pool.transaction() as conn:
                params = [
                    (
                        m["relay_url"],
                        m["relay_network"],
                        m["relay_inserted_at"],
                        m["generated_at"],
                        m.get("nip66") is not None,
                        m.get("nip66", {}).get("openable"),
                        m.get("nip66", {}).get("readable"),
                        m.get("nip66", {}).get("writable"),
                        m.get("nip66", {}).get("rtt_open"),
                        m.get("nip66", {}).get("rtt_read"),
                        m.get("nip66", {}).get("rtt_write"),
                        m.get("nip11") is not None,
                        m.get("nip11", {}).get("name"),
                        m.get("nip11", {}).get("description"),
                        m.get("nip11", {}).get("banner"),
                        m.get("nip11", {}).get("icon"),
                        m.get("nip11", {}).get("pubkey"),
                        m.get("nip11", {}).get("contact"),
                        m.get("nip11", {}).get("supported_nips"),
                        m.get("nip11", {}).get("software"),
                        m.get("nip11", {}).get("version"),
                        m.get("nip11", {}).get("privacy_policy"),
                        m.get("nip11", {}).get("terms_of_service"),
                        m.get("nip11", {}).get("limitation"),
                        m.get("nip11", {}).get("extra_fields"),
                    )
                    for m in metadata_list
                ]

                await conn.executemany(
                    f"SELECT {self._config.procedures.insert_relay_metadata}($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25)",
                    params,
                    timeout=self._config.timeouts.batch,
                )

            self._logger.debug("relay_metadata_inserted", count=len(metadata_list))
            return True

        except (asyncpg.PostgresError, ValueError) as e:
            self._logger.error("insert_relay_metadata_failed", error=str(e))
            return False

    # -------------------------------------------------------------------------
    # Cleanup Operations
    # -------------------------------------------------------------------------

    async def delete_orphan_events(self) -> int:
        """Delete orphaned events. Returns count."""
        return await self._call_procedure(
            self._config.procedures.delete_orphan_events,
            fetch_result=True,
        )

    async def delete_orphan_nip11(self) -> int:
        """Delete orphaned NIP-11 records. Returns count."""
        return await self._call_procedure(
            self._config.procedures.delete_orphan_nip11,
            fetch_result=True,
        )

    async def delete_orphan_nip66(self) -> int:
        """Delete orphaned NIP-66 records. Returns count."""
        return await self._call_procedure(
            self._config.procedures.delete_orphan_nip66,
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

    def __repr__(self) -> str:
        """String representation."""
        db = self.pool.config.database
        return f"Brotr(host={db.host}, database={db.database}, connected={self.pool.is_connected})"