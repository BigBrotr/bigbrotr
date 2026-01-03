"""
Database Interface for BigBrotr.

High-level interface for database operations using stored procedures.

Features:
- Stored procedure wrappers for event/relay operations
- Bulk insert optimization via array parameters (single roundtrip)
- Batch operations with configurable limits
- Type-safe dataclass inputs (Relay, EventRelay, RelayMetadata)
- Cleanup operations for orphaned data
- Materialized view refresh operations
- Structured logging
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import asyncpg
import yaml
from pydantic import BaseModel, Field, field_validator

from models import Event, EventRelay, Metadata, Relay, RelayMetadata

from .logger import Logger
from .pool import Pool


# ============================================================================
# Configuration Models
# ============================================================================


class BatchConfig(BaseModel):
    """Batch operation configuration."""

    max_batch_size: int = Field(
        default=10000, ge=1, le=100000, description="Maximum items per batch operation"
    )


class TimeoutsConfig(BaseModel):
    """
    Operation timeouts for Brotr.

    All timeout values are in seconds. Use None for no timeout (infinite wait).
    When set, values must be >= 0.1 seconds.
    """

    query: float | None = Field(default=60.0, description="Query timeout (seconds, None=infinite)")
    batch: float | None = Field(
        default=120.0, description="Batch insert timeout (seconds, None=infinite)"
    )
    cleanup: float | None = Field(
        default=90.0, description="Cleanup procedure timeout (seconds, None=infinite)"
    )
    refresh: float | None = Field(
        default=None, description="Materialized view refresh timeout (seconds, None=infinite)"
    )

    @field_validator("query", "batch", "cleanup", "refresh", mode="after")
    @classmethod
    def validate_timeout(cls, v: float | None) -> float | None:
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

    All insert methods accept ONLY dataclass instances (Relay, Event, EventRelay, Metadata, RelayMetadata).

    Usage:
        from models import Relay, Event, EventRelay, Metadata, RelayMetadata

        brotr = Brotr.from_yaml("config.yaml")

        async with brotr:
            # Insert relays
            relay = Relay("wss://relay.example.com")
            await brotr.insert_relays(records=[relay])

            # Insert events only
            event = Event(nostr_event)
            inserted, skipped = await brotr.insert_events(records=[event])

            # Insert events with relays and junctions (cascade)
            event_relay = EventRelay(Event(nostr_event), relay)
            inserted, skipped = await brotr.insert_events_relays(records=[event_relay])

            # Insert metadata only
            metadata = Metadata({"name": "My Relay"})
            await brotr.insert_metadata(records=[metadata])

            # Insert relay metadata with relay and junction (cascade)
            relay_metadata = RelayMetadata(relay, metadata=metadata, metadata_type="nip11")
            await brotr.insert_relay_metadata(records=[relay_metadata])
    """

    def __init__(
        self,
        pool: Pool | None = None,
        config: BrotrConfig | None = None,
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

    @property
    def config(self) -> BrotrConfig:
        """Get configuration."""
        return self._config

    @classmethod
    def from_yaml(cls, config_path: str) -> Brotr:
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
    def from_dict(cls, config_dict: dict[str, Any]) -> Brotr:
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

    def _transpose_to_columns(self, params: list[tuple[Any, ...]]) -> tuple[list[Any], ...]:
        """
        Transpose list of tuples to tuple of lists (columns) for bulk SQL operations.

        Args:
            params: List of tuples where each tuple represents a row

        Returns:
            Tuple of lists where each list represents a column

        Raises:
            ValueError: If tuples have inconsistent lengths
        """
        if not params:
            return ()

        expected_len = len(params[0])
        for i, row in enumerate(params):
            if len(row) != expected_len:
                raise ValueError(f"Row {i} has {len(row)} columns, expected {expected_len}")

        return tuple(list(col) for col in zip(*params, strict=False))

    async def _call_procedure(
        self,
        procedure_name: str,
        *args: Any,
        conn: asyncpg.Connection[asyncpg.Record] | None = None,
        fetch_result: bool = False,
        timeout: float | None = None,
    ) -> Any:
        """
        Call a stored procedure.

        Procedure names are always hardcoded string literals in the calling methods.
        SQL injection is prevented by parameterized arguments ($1, $2, etc.).

        Args:
            procedure_name: Procedure name (hardcoded in calling method)
            *args: Procedure arguments (passed as parameterized values)
            conn: Optional connection (acquires from pool if None)
            fetch_result: Return result if True
            timeout: Timeout in seconds (None = no timeout)

        Returns:
            Result value if fetch_result=True, otherwise None
        """
        params = ", ".join(f"${i + 1}" for i in range(len(args))) if args else ""
        query = f"SELECT {procedure_name}({params})"

        async def execute(c: asyncpg.Connection[asyncpg.Record]) -> Any:
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

    async def insert_relays(self, records: list[Relay]) -> int:
        """
        Insert relays using bulk insert with array parameters.

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

        params = [relay.to_db_params() for relay in records]
        columns = self._transpose_to_columns(params)

        async with self.pool.transaction() as conn:
            inserted: int = (
                await conn.fetchval(
                    "SELECT relays_insert($1, $2, $3)",
                    *columns,
                    timeout=self._config.timeouts.batch,
                )
                or 0
            )

        self._logger.debug("relays_inserted", count=inserted, attempted=len(records))
        return inserted

    async def insert_events(self, records: list[Event]) -> tuple[int, int]:
        """
        Insert events using bulk insert with array parameters.

        Inserts only into the events table. Use insert_events_relays with
        cascade=True to also insert relays and event-relay junctions.

        Args:
            records: List of Event instances

        Returns:
            Tuple of (inserted, skipped) counts

        Raises:
            asyncpg.PostgresError: On database errors
            ValueError: On validation errors (batch size)
        """
        if not records:
            return 0, 0

        self._validate_batch_size(records, "insert_events")

        # Collect valid params and track skipped
        valid_params: list[tuple[Any, ...]] = []
        skipped = 0

        for event in records:
            try:
                valid_params.append(event.to_db_params())
            except (ValueError, TypeError) as ex:
                skipped += 1
                self._logger.warning(
                    "invalid_event_skipped",
                    error=str(ex),
                    event_id=event.id().to_hex(),
                )

        if not valid_params:
            self._logger.warning("all_events_invalid", total=len(records), skipped=skipped)
            return 0, skipped

        columns = self._transpose_to_columns(valid_params)

        async with self.pool.transaction() as conn:
            inserted: int = (
                await conn.fetchval(
                    "SELECT events_insert($1, $2, $3, $4, $5, $6, $7)",
                    *columns,
                    timeout=self._config.timeouts.batch,
                )
                or 0
            )

        if skipped > 0:
            self._logger.info("events_inserted_with_skipped", inserted=inserted, skipped=skipped)
        else:
            self._logger.debug("events_inserted", count=inserted, attempted=len(valid_params))
        return inserted, skipped

    async def insert_events_relays(
        self, records: list[EventRelay], *, cascade: bool = True
    ) -> tuple[int, int]:
        """
        Insert event-relay junctions using bulk insert with array parameters.

        Args:
            records: List of EventRelay dataclass instances
            cascade: If True (default), also inserts relays and events.
                     If False, inserts only into events_relays junction (FKs must exist).

        Returns:
            Tuple of (inserted, skipped) counts

        Raises:
            asyncpg.PostgresError: On database errors
            ValueError: On validation errors (batch size)
        """
        if not records:
            return 0, 0

        self._validate_batch_size(records, "insert_events_relays")

        # Collect valid params and track skipped
        valid_params: list[tuple[Any, ...]] = []
        skipped = 0

        for event_relay in records:
            try:
                valid_params.append(event_relay.to_db_params())
            except (ValueError, TypeError) as ex:
                skipped += 1
                self._logger.warning(
                    "invalid_event_relay_skipped",
                    error=str(ex),
                    event_id=event_relay.event.id().to_hex(),
                )

        if not valid_params:
            self._logger.warning("all_event_relays_invalid", total=len(records), skipped=skipped)
            return 0, skipped

        columns = self._transpose_to_columns(valid_params)

        if cascade:
            # Insert relays → events → events_relays
            query = (
                "SELECT events_relays_insert_cascade($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)"
            )
        else:
            # Insert only events_relays junction (event_id, relay_url, seen_at)
            # Columns: 0=id, 7=relay_url, 10=seen_at
            event_ids = columns[0]
            relay_urls = columns[7]
            seen_ats = columns[10]
            query = "SELECT events_relays_insert($1, $2, $3)"
            columns = (event_ids, relay_urls, seen_ats)

        async with self.pool.transaction() as conn:
            inserted: int = (
                await conn.fetchval(query, *columns, timeout=self._config.timeouts.batch) or 0
            )

        if skipped > 0:
            self._logger.info(
                "events_relays_inserted_with_skipped", inserted=inserted, skipped=skipped
            )
        else:
            self._logger.debug(
                "events_relays_inserted",
                count=inserted,
                attempted=len(valid_params),
                cascade=cascade,
            )
        return inserted, skipped

    async def insert_metadata(self, records: list[Metadata]) -> int:
        """
        Insert metadata records using bulk insert with array parameters.

        Inserts only into the metadata table (content-addressed by hash).
        Hash is computed in PostgreSQL using digest().
        Use insert_relay_metadata with cascade=True to also insert relays and junctions.

        Args:
            records: List of Metadata dataclass instances

        Returns:
            Number of metadata records inserted

        Raises:
            asyncpg.PostgresError: On database errors
            ValueError: On validation errors (batch size)
        """
        if not records:
            return 0

        self._validate_batch_size(records, "insert_metadata")

        # Pass only data, hash computed in DB
        datas = [metadata.to_db_params()[0] for metadata in records]

        async with self.pool.transaction() as conn:
            inserted: int = (
                await conn.fetchval(
                    "SELECT metadata_insert($1)",
                    datas,
                    timeout=self._config.timeouts.batch,
                )
                or 0
            )

        self._logger.debug("metadata_inserted", count=inserted, attempted=len(records))
        return inserted

    async def insert_relay_metadata(
        self, records: list[RelayMetadata], *, cascade: bool = True
    ) -> int:
        """
        Insert relay metadata using bulk insert with array parameters.

        Args:
            records: List of RelayMetadata dataclass instances
            cascade: If True (default), also inserts relays and metadata records.
                     If False, inserts only into relay_metadata junction (FKs must exist).

        Returns:
            Number of relay_metadata records inserted

        Raises:
            asyncpg.PostgresError: On database errors
            ValueError: On validation errors (batch size)
        """
        if not records:
            return 0

        self._validate_batch_size(records, "insert_relay_metadata")

        if cascade:
            # Insert relays → metadata → relay_metadata (hash computed in DB)
            all_params = [metadata.to_db_params() for metadata in records]
            columns = self._transpose_to_columns(all_params)

            async with self.pool.transaction() as conn:
                inserted: int = (
                    await conn.fetchval(
                        "SELECT relay_metadata_insert_cascade($1, $2, $3, $4, $5, $6)",
                        *columns,
                        timeout=self._config.timeouts.batch,
                    )
                    or 0
                )
        else:
            # Insert only into relay_metadata junction (FKs must exist)
            # Hash is computed in PostgreSQL using digest()
            relay_urls: list[str] = []
            metadata_datas: list[str] = []
            types: list[str] = []
            generated_ats: list[int] = []

            for record in records:
                relay_urls.append(record.relay.url_without_scheme)
                metadata_datas.append(record.metadata.to_db_params()[0])
                types.append(record.metadata_type)
                generated_ats.append(record.generated_at)

            async with self.pool.transaction() as conn:
                inserted = (
                    await conn.fetchval(
                        "SELECT relay_metadata_insert($1, $2, $3, $4)",
                        relay_urls,
                        metadata_datas,
                        types,
                        generated_ats,
                        timeout=self._config.timeouts.batch,
                    )
                    or 0
                )

        self._logger.debug(
            "relay_metadata_inserted", count=inserted, attempted=len(records), cascade=cascade
        )
        return inserted

    # -------------------------------------------------------------------------
    # Cleanup Operations
    # -------------------------------------------------------------------------

    async def delete_orphan_events(self) -> int:
        """Delete orphaned events. Returns count."""
        result: int = await self._call_procedure(
            "orphan_events_delete",
            fetch_result=True,
            timeout=self._config.timeouts.cleanup,
        )
        return result

    async def delete_orphan_metadata(self) -> int:
        """Delete orphaned metadata records. Returns count."""
        result: int = await self._call_procedure(
            "orphan_metadata_delete",
            fetch_result=True,
            timeout=self._config.timeouts.cleanup,
        )
        return result

    async def delete_failed_candidates(self, max_attempts: int) -> int:
        """
        Delete validator candidates that exceeded max failed attempts.

        Args:
            max_attempts: Threshold for deletion. Candidates with
                         failed_attempts >= max_attempts will be deleted.

        Returns:
            Number of deleted candidates.
        """
        result: int = await self._call_procedure(
            "failed_candidates_delete",
            max_attempts,
            fetch_result=True,
            timeout=self._config.timeouts.cleanup,
        )
        return result

    # -------------------------------------------------------------------------
    # Service Data Operations
    # -------------------------------------------------------------------------

    async def upsert_service_data(self, records: list[tuple[str, str, str, dict[str, Any]]]) -> int:
        """
        Upsert service data records atomically using bulk insert with array parameters.

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
        service_names: list[str] = []
        data_types: list[str] = []
        keys: list[str] = []
        values: list[str] = []
        updated_ats: list[int] = []

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

            service_names.append(service_name)
            data_types.append(data_type)
            keys.append(key)
            values.append(value_json)
            updated_ats.append(now)

        async with self.pool.transaction() as conn:
            await conn.execute(
                "SELECT service_data_upsert($1, $2, $3, $4, $5)",
                service_names,
                data_types,
                keys,
                values,
                updated_ats,
                timeout=self._config.timeouts.batch,
            )

        self._logger.debug("service_data_upserted", count=len(records))
        return len(records)

    async def get_service_data(
        self,
        service_name: str,
        data_type: str,
        key: str | None = None,
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
            "SELECT * FROM service_data_get($1, $2, $3)",
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
        Delete service data records atomically using bulk delete with array parameters.

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

        # Transpose list of tuples to separate lists
        service_names = [k[0] for k in keys]
        data_types = [k[1] for k in keys]
        data_keys = [k[2] for k in keys]

        async with self.pool.transaction() as conn:
            deleted: int = (
                await conn.fetchval(
                    "SELECT service_data_delete($1, $2, $3)",
                    service_names,
                    data_types,
                    data_keys,
                    timeout=self._config.timeouts.batch,
                )
                or 0
            )

        self._logger.debug("service_data_deleted", count=deleted, attempted=len(keys))
        return deleted

    # -------------------------------------------------------------------------
    # Query Operations
    # -------------------------------------------------------------------------

    async def get_relays_needing_check(
        self,
        service_name: str,
        check_interval_seconds: int,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """
        Get relays that need health check based on last check time.

        Finds relays that either have no checkpoint record or whose last check
        was older than the specified interval.

        Args:
            service_name: Name of the service (e.g., 'monitor')
            check_interval_seconds: Minimum seconds since last check
            limit: Maximum number of relays to return (default: 1000)

        Returns:
            List of dicts with keys: url, network, discovered_at
        """
        cutoff = int(time.time()) - check_interval_seconds

        query = """
            SELECT r.url, r.network, r.discovered_at
            FROM relays r
            LEFT JOIN service_data sd ON
                sd.service_name = $1
                AND sd.data_type = 'checkpoint'
                AND sd.data_key = r.url
            WHERE sd.data_key IS NULL
               OR (sd.data->>'last_check_at')::BIGINT < $2
            ORDER BY r.discovered_at ASC
            LIMIT $3
        """

        rows = await self.pool.fetch(
            query, service_name, cutoff, limit, timeout=self._config.timeouts.query
        )

        self._logger.debug(
            "relays_needing_check",
            service=service_name,
            count=len(rows),
            cutoff=cutoff,
        )

        return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # Refresh Operations
    # -------------------------------------------------------------------------

    async def refresh_relay_metadata_latest(self) -> None:
        """Refresh relay_metadata_latest materialized view (concurrent, non-blocking)."""
        await self._call_procedure(
            "relay_metadata_latest_refresh",
            timeout=self._config.timeouts.refresh,
        )
        self._logger.debug("matview_refreshed", view="relay_metadata_latest")

    async def refresh_events_statistics(self) -> None:
        """Refresh events_statistics materialized view (concurrent, non-blocking)."""
        await self._call_procedure(
            "events_statistics_refresh",
            timeout=self._config.timeouts.refresh,
        )
        self._logger.debug("matview_refreshed", view="events_statistics")

    async def refresh_relays_statistics(self) -> None:
        """Refresh relays_statistics materialized view (concurrent, non-blocking)."""
        await self._call_procedure(
            "relays_statistics_refresh",
            timeout=self._config.timeouts.refresh,
        )
        self._logger.debug("matview_refreshed", view="relays_statistics")

    async def refresh_kind_counts_total(self) -> None:
        """Refresh kind_counts_total materialized view (concurrent, non-blocking)."""
        await self._call_procedure(
            "kind_counts_total_refresh",
            timeout=self._config.timeouts.refresh,
        )
        self._logger.debug("matview_refreshed", view="kind_counts_total")

    async def refresh_kind_counts_by_relay(self) -> None:
        """Refresh kind_counts_by_relay materialized view (concurrent, non-blocking)."""
        await self._call_procedure(
            "kind_counts_by_relay_refresh",
            timeout=self._config.timeouts.refresh,
        )
        self._logger.debug("matview_refreshed", view="kind_counts_by_relay")

    async def refresh_pubkey_counts_total(self) -> None:
        """Refresh pubkey_counts_total materialized view (concurrent, non-blocking)."""
        await self._call_procedure(
            "pubkey_counts_total_refresh",
            timeout=self._config.timeouts.refresh,
        )
        self._logger.debug("matview_refreshed", view="pubkey_counts_total")

    async def refresh_pubkey_counts_by_relay(self) -> None:
        """Refresh pubkey_counts_by_relay materialized view (concurrent, non-blocking)."""
        await self._call_procedure(
            "pubkey_counts_by_relay_refresh",
            timeout=self._config.timeouts.refresh,
        )
        self._logger.debug("matview_refreshed", view="pubkey_counts_by_relay")

    # -------------------------------------------------------------------------
    # Context Manager
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> Brotr:
        """
        Async context manager entry - connects the pool.

        Usage:
            async with brotr:
                await brotr.insert_events_relays([...])
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
