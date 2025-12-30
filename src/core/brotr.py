"""
Database Interface for BigBrotr.

High-level interface for database operations using stored procedures.

Features:
- Stored procedure wrappers for event/relay operations
- Bulk insert optimization via executemany
- Batch operations with configurable limits
- Type-safe dataclass inputs (Relay, EventRelay, RelayMetadata)
- Structured logging
- Parallel cleanup operations
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Final, Optional

import asyncpg
import yaml
from pydantic import BaseModel, Field

from models import EventRelay, Relay, RelayMetadata

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
PROC_DELETE_ORPHAN_METADATA: Final[str] = "delete_orphan_metadata"
PROC_DELETE_FAILED_CANDIDATES: Final[str] = "delete_failed_candidates"
PROC_UPSERT_SERVICE_DATA: Final[str] = "upsert_service_data"
PROC_DELETE_SERVICE_DATA: Final[str] = "delete_service_data"


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
                    # Fix: Check if event has id() method, not if event_relay has event attribute
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
                f"SELECT {PROC_INSERT_EVENT}($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
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
                f"SELECT {PROC_INSERT_RELAY}($1, $2, $3)",
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
                f"SELECT {PROC_INSERT_RELAY_METADATA}($1, $2, $3, $4, $5, $6)",
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
            PROC_DELETE_ORPHAN_EVENTS,
            fetch_result=True,
        )

    async def delete_orphan_metadata(self) -> int:
        """Delete orphaned metadata records. Returns count."""
        return await self._call_procedure(
            PROC_DELETE_ORPHAN_METADATA,
            fetch_result=True,
        )

    async def delete_failed_candidates(self, max_attempts: int = 10) -> int:
        """Delete validator candidates that exceeded max failed attempts. Returns count."""
        return await self._call_procedure(
            PROC_DELETE_FAILED_CANDIDATES,
            max_attempts,
            fetch_result=True,
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
                f"SELECT {PROC_UPSERT_SERVICE_DATA}($1, $2, $3, $4, $5)",
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
        if key is not None:
            rows = await self.pool.fetch(
                """
                SELECT data_key, data, updated_at
                FROM service_data
                WHERE service_name = $1 AND data_type = $2 AND data_key = $3
                """,
                service_name,
                data_type,
                key,
                timeout=self._config.timeouts.query,
            )
        else:
            rows = await self.pool.fetch(
                """
                SELECT data_key, data, updated_at
                FROM service_data
                WHERE service_name = $1 AND data_type = $2
                ORDER BY updated_at ASC
                """,
                service_name,
                data_type,
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
                f"SELECT {PROC_DELETE_SERVICE_DATA}($1, $2, $3)",
                keys,
                timeout=self._config.timeouts.batch,
            )

        self._logger.debug("service_data_deleted", count=len(keys))
        return len(keys)

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
