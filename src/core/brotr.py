"""
Database Interface for BigBrotr.

High-level interface for database operations using stored procedures.

Features:
- Stored procedure wrappers for event/relay operations
- Bulk insert optimization via executemany
- Batch operations with configurable limits
- Type-safe dataclass inputs (Relay, EventRelay, RelayMetadata)
- Cleanup operations for orphaned data
- Materialized view refresh operations
- Structured logging
"""

import json
import time
from pathlib import Path
from typing import Any, Optional

import asyncpg
import yaml
from pydantic import BaseModel, Field, field_validator

from models import EventRelay, Relay, RelayMetadata

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


class TimeoutsConfig(BaseModel):
    """
    Operation timeouts for Brotr.

    All timeout values are in seconds. Use None for no timeout (infinite wait).
    When set, values must be >= 0.1 seconds.
    """

    query: Optional[float] = Field(default=60.0, description="Query timeout (seconds, None=infinite)")
    batch: Optional[float] = Field(default=120.0, description="Batch insert timeout (seconds, None=infinite)")
    cleanup: Optional[float] = Field(default=90.0, description="Cleanup procedure timeout (seconds, None=infinite)")
    refresh: Optional[float] = Field(default=None, description="Materialized view refresh timeout (seconds, None=infinite)")

    @field_validator("query", "batch", "cleanup", "refresh", mode="after")
    @classmethod
    def validate_timeout(cls, v: Optional[float]) -> Optional[float]:
        """Validate timeout: None (infinite) or >= 0.1 seconds."""
        if v is not None and v < 0.1:
            raise ValueError("Timeout must be None (infinite) or >= 0.1 seconds")
        return v


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

    All insert methods accept ONLY dataclass instances (Relay, EventRelay, RelayMetadata).

    Usage:
        from models import Relay, EventRelay, RelayMetadata

        brotr = Brotr.from_yaml("config.yaml")

        async with brotr:
            # Insert relays
            relay = Relay("wss://relay.example.com")
            await brotr.insert_relays(records=[relay])

            # Insert events
            event_relay = EventRelay.from_nostr_event(nostr_event, relay)
            inserted, skipped = await brotr.insert_events(records=[event_relay])

            # Insert metadata
            metadata = RelayMetadata(relay, nip11=nip11, nip66=nip66)
            await brotr.insert_relay_metadata(records=[metadata])
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
            timeouts:
              query: 60.0      # seconds, or null for infinite
              batch: 120.0     # seconds, or null for infinite
              cleanup: 90.0    # seconds, or null for infinite
              refresh: null    # seconds, or null for infinite (default: null)
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

    @property
    def config(self) -> BrotrConfig:
        """Get configuration."""
        return self._config

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
            timeout: Timeout in seconds (None = no timeout)

        Returns:
            Result value if fetch_result=True, otherwise None
        """
        params = ", ".join(f"${i + 1}" for i in range(len(args))) if args else ""
        query = f"SELECT {procedure_name}({params})"

        async def execute(c: asyncpg.Connection) -> Any:
            if fetch_result:
                result = await c.fetchval(query, *args, timeout=timeout)
                return result or 0
            await c.execute(query, *args, timeout=timeout)
            return None

        if conn is not None:
            return await execute(conn)

        async with self.pool.acquire() as acquired_conn:
            return await execute(acquired_conn)

    # -------------------------------------------------------------------------
    # Insert Operations
    # -------------------------------------------------------------------------

    async def insert_events(self, records: list[EventRelay]) -> tuple[int, int]:
        """
        Insert events atomically using bulk insert.

        Args:
            records: List of EventRelay dataclass instances

        Returns:
            Tuple of (inserted, skipped) counts

        Raises:
            asyncpg.PostgresError: On database errors
            ValueError: On validation errors (batch size)
        """
        if not records:
            return 0, 0

        self._validate_batch_size(records, "insert_events")

        async with self.pool.transaction() as conn:
            params = []
            skipped = 0

            for event_relay in records:
                try:
                    params.append(event_relay.to_db_params())
                except (ValueError, TypeError) as ex:
                    skipped += 1
                    try:
                        event_id = event_relay.event.id().to_hex() if hasattr(event_relay.event, "id") else "unknown"
                    except Exception:
                        event_id = "unknown"
                    self._logger.warning(
                        "invalid_event_skipped",
                        error=str(ex),
                        event_id=event_id,
                    )
                    continue

            if not params:
                self._logger.warning("all_events_invalid", total=len(records), skipped=skipped)
                return 0, skipped

            await conn.executemany(
                "SELECT insert_event($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
                params,
                timeout=self._config.timeouts.batch,
            )

        inserted = len(params)
        if skipped > 0:
            self._logger.info("events_inserted_with_skipped", inserted=inserted, skipped=skipped)
        else:
            self._logger.debug("events_inserted", count=inserted)
        return inserted, skipped

    async def insert_relays(self, records: list[Relay]) -> int:
        """
        Insert relays atomically using bulk insert.

        Args:
            records: List of Relay dataclass instances

        Returns:
            Number of relays inserted

        Raises:
            asyncpg.PostgresError: On database errors
            ValueError: On validation errors (batch size)
        """
        if not records:
            return 0

        self._validate_batch_size(records, "insert_relays")

        async with self.pool.transaction() as conn:
            params = [relay.to_db_params() for relay in records]

            await conn.executemany(
                "SELECT insert_relay($1, $2, $3)",
                params,
                timeout=self._config.timeouts.batch,
            )

        self._logger.debug("relays_inserted", count=len(records))
        return len(records)

    async def insert_relay_metadata(self, records: list[RelayMetadata]) -> int:
        """
        Insert relay metadata atomically using bulk insert.

        Each RelayMetadata represents a single junction record (one row in relay_metadata).
        The schema uses 6 parameters per record:
            (relay_url, relay_network, relay_discovered_at, generated_at,
             metadata_type, metadata_data)

        The metadata hash (content-addressed ID) is computed by PostgreSQL.

        Args:
            records: List of RelayMetadata dataclass instances

        Returns:
            Number of metadata records inserted

        Raises:
            asyncpg.PostgresError: On database errors
            ValueError: On validation errors (batch size)
        """
        if not records:
            return 0

        self._validate_batch_size(records, "insert_relay_metadata")

        # Collect params from each RelayMetadata
        all_params = [metadata.to_db_params() for metadata in records]

        async with self.pool.transaction() as conn:
            await conn.executemany(
                "SELECT insert_relay_metadata($1, $2, $3, $4, $5, $6)",
                all_params,
                timeout=self._config.timeouts.batch,
            )

        self._logger.debug("relay_metadata_inserted", count=len(all_params))
        return len(all_params)

    # -------------------------------------------------------------------------
    # Cleanup Operations
    # -------------------------------------------------------------------------

    async def delete_orphan_events(self) -> int:
        """Delete orphaned events. Returns count."""
        return await self._call_procedure(
            "delete_orphan_events",
            fetch_result=True,
            timeout=self._config.timeouts.cleanup,
        )

    async def delete_orphan_metadata(self) -> int:
        """Delete orphaned metadata records. Returns count."""
        return await self._call_procedure(
            "delete_orphan_metadata",
            fetch_result=True,
            timeout=self._config.timeouts.cleanup,
        )

    async def delete_failed_candidates(self, max_attempts: int = 10) -> int:
        """Delete validator candidates that exceeded max failed attempts. Returns count."""
        return await self._call_procedure(
            "delete_failed_candidates",
            max_attempts,
            fetch_result=True,
            timeout=self._config.timeouts.cleanup,
        )

    # -------------------------------------------------------------------------
    # Service Data Operations
    # -------------------------------------------------------------------------

    async def upsert_service_data(
        self, records: list[tuple[str, str, str, dict]]
    ) -> int:
        """
        Upsert service data records atomically using bulk insert.

        Args:
            records: List of tuples (service_name, data_type, key, value)

        Returns:
            Number of records upserted

        Tuple format: (service_name, data_type, key, value)
            - service_name: "finder", "validator", etc.
            - data_type: "candidate", "cursor", "state"
            - key: unique identifier
            - value: dict to store as JSON
        """
        if not records:
            return 0

        self._validate_batch_size(records, "upsert_service_data")

        now = int(time.time())
        async with self.pool.transaction() as conn:
            params = []
            for service_name, data_type, key, value in records:
                try:
                    value_json = json.dumps(value)
                except (TypeError, ValueError) as e:
                    # Handle circular references or non-serializable objects
                    self._logger.warning(
                        "service_data_json_error",
                        service=service_name,
                        data_type=data_type,
                        key=key,
                        error=str(e),
                    )
                    # Attempt fallback with default serialization
                    value_json = json.dumps(value, default=str)
                params.append((service_name, data_type, key, value_json, now))

            await conn.executemany(
                "SELECT upsert_service_data($1, $2, $3, $4, $5)",
                params,
                timeout=self._config.timeouts.batch,
            )

        self._logger.debug("service_data_upserted", count=len(records))
        return len(records)

    async def get_service_data(
        self,
        service_name: str,
        data_type: str,
        key: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Get service data records.

        Args:
            service_name: Name of the service
            data_type: Type of data
            key: Optional specific key (None = all records)

        Returns:
            List of records with keys: key, value, updated_at
        """
        rows = await self.pool.fetch(
            "SELECT * FROM get_service_data($1, $2, $3)",
            service_name,
            data_type,
            key,
            timeout=self._config.timeouts.query,
        )

        return [
            {"key": row["data_key"], "value": row["data"], "updated_at": row["updated_at"]}
            for row in rows
        ]

    async def delete_service_data(self, keys: list[tuple[str, str, str]]) -> int:
        """
        Delete service data records atomically.

        Args:
            keys: List of tuples (service_name, data_type, key)

        Returns:
            Number of records deleted

        Tuple format: (service_name, data_type, key)
            - service_name: "finder", "validator", etc.
            - data_type: "candidate", "cursor", "state"
            - key: unique identifier to delete
        """
        if not keys:
            return 0

        self._validate_batch_size(keys, "delete_service_data")

        async with self.pool.transaction() as conn:
            await conn.executemany(
                "SELECT delete_service_data($1, $2, $3)",
                keys,
                timeout=self._config.timeouts.batch,
            )

        self._logger.debug("service_data_deleted", count=len(keys))
        return len(keys)

    # -------------------------------------------------------------------------
    # Refresh Operations
    # -------------------------------------------------------------------------

    async def refresh_relay_metadata_latest(self) -> None:
        """Refresh relay_metadata_latest materialized view (concurrent, non-blocking)."""
        await self._call_procedure(
            "refresh_relay_metadata_latest",
            timeout=self._config.timeouts.refresh,
        )
        self._logger.debug("matview_refreshed", view="relay_metadata_latest")

    async def refresh_events_statistics(self) -> None:
        """Refresh events_statistics materialized view (concurrent, non-blocking)."""
        await self._call_procedure(
            "refresh_events_statistics",
            timeout=self._config.timeouts.refresh,
        )
        self._logger.debug("matview_refreshed", view="events_statistics")

    async def refresh_relays_statistics(self) -> None:
        """Refresh relays_statistics materialized view (concurrent, non-blocking)."""
        await self._call_procedure(
            "refresh_relays_statistics",
            timeout=self._config.timeouts.refresh,
        )
        self._logger.debug("matview_refreshed", view="relays_statistics")

    async def refresh_kind_counts_total(self) -> None:
        """Refresh kind_counts_total materialized view (concurrent, non-blocking)."""
        await self._call_procedure(
            "refresh_kind_counts_total",
            timeout=self._config.timeouts.refresh,
        )
        self._logger.debug("matview_refreshed", view="kind_counts_total")

    async def refresh_kind_counts_by_relay(self) -> None:
        """Refresh kind_counts_by_relay materialized view (concurrent, non-blocking)."""
        await self._call_procedure(
            "refresh_kind_counts_by_relay",
            timeout=self._config.timeouts.refresh,
        )
        self._logger.debug("matview_refreshed", view="kind_counts_by_relay")

    async def refresh_pubkey_counts_total(self) -> None:
        """Refresh pubkey_counts_total materialized view (concurrent, non-blocking)."""
        await self._call_procedure(
            "refresh_pubkey_counts_total",
            timeout=self._config.timeouts.refresh,
        )
        self._logger.debug("matview_refreshed", view="pubkey_counts_total")

    async def refresh_pubkey_counts_by_relay(self) -> None:
        """Refresh pubkey_counts_by_relay materialized view (concurrent, non-blocking)."""
        await self._call_procedure(
            "refresh_pubkey_counts_by_relay",
            timeout=self._config.timeouts.refresh,
        )
        self._logger.debug("matview_refreshed", view="pubkey_counts_by_relay")

    # -------------------------------------------------------------------------
    # Context Manager
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
