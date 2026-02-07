"""
High-level database interface built on stored procedures.

Provides typed wrappers around PostgreSQL stored procedures for all data
operations: relay management, event ingestion, metadata storage, service
state persistence, and materialized view maintenance.

Bulk inserts use array parameters to perform the entire batch in a single
database round-trip. All insert methods accept only validated dataclass
instances (Relay, Event, EventRelay, Metadata, RelayMetadata) to enforce
type safety at the API boundary.

Uses composition with ``Pool`` for connection management and implements
an async context manager for automatic pool lifecycle handling.
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any, ClassVar

import asyncpg
from pydantic import BaseModel, Field, field_validator

from utils.yaml import load_yaml

from .logger import Logger
from .pool import Pool, PoolConfig


_MIN_TIMEOUT_SECONDS = 0.1  # Floor for all configurable timeouts


if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager

    from models import Event, EventRelay, Metadata, Relay, RelayMetadata


# ---------------------------------------------------------------------------
# Configuration Models
# ---------------------------------------------------------------------------


class BatchConfig(BaseModel):
    """Controls the maximum number of records per bulk insert operation."""

    max_batch_size: int = Field(
        default=1000, ge=1, le=100000, description="Maximum items per batch operation"
    )


class TimeoutsConfig(BaseModel):
    """Timeout settings for Brotr operations (in seconds).

    Each timeout can be set to None for no limit (infinite wait) or to a
    float >= 0.1 seconds. Different categories allow tuning timeouts for
    fast queries vs. slow bulk inserts vs. long-running maintenance tasks.
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
        if v is not None and v < _MIN_TIMEOUT_SECONDS:
            raise ValueError(
                f"Timeout must be None (infinite) or >= {_MIN_TIMEOUT_SECONDS} seconds"
            )
        return v


class BrotrConfig(BaseModel):
    """Aggregate configuration for the Brotr database interface."""

    batch: BatchConfig = Field(default_factory=BatchConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)


# ---------------------------------------------------------------------------
# Brotr Class
# ---------------------------------------------------------------------------


class Brotr:
    """High-level database interface wrapping PostgreSQL stored procedures.

    Encapsulates all database operations behind typed methods that accept
    validated dataclass instances (Relay, Event, EventRelay, Metadata,
    RelayMetadata). Bulk inserts use array parameters for single-roundtrip
    efficiency.

    Uses composition with a private ``Pool`` instance for connection
    management. Exposes generic query methods (fetch, fetchrow, fetchval,
    execute, transaction) as a facade over the pool. Implements async
    context manager for automatic pool lifecycle management.

    Example:
        brotr = Brotr.from_yaml("config.yaml")

        async with brotr:
            relay = Relay("wss://relay.example.com")
            await brotr.insert_relays(records=[relay])

            event_relay = EventRelay(Event(nostr_event), relay)
            await brotr.insert_events_relays(records=[event_relay])
    """

    def __init__(
        self,
        pool: Pool | None = None,
        config: BrotrConfig | None = None,
    ) -> None:
        """Initialize the database interface.

        Args:
            pool: Connection pool for database access. Creates a default
                Pool if not provided.
            config: Brotr-specific configuration (batch sizes, timeouts).
                Uses defaults if not provided.
        """
        self._pool = pool or Pool()
        self._config = config or BrotrConfig()
        self._logger = Logger("brotr")

    @property
    def config(self) -> BrotrConfig:
        """The Brotr configuration (read-only)."""
        return self._config

    @property
    def pool_config(self) -> PoolConfig:
        """Read-only access to the underlying pool configuration."""
        return self._pool.config

    @classmethod
    def from_yaml(cls, config_path: str) -> Brotr:
        """Create a Brotr instance from a YAML configuration file.

        The YAML file should contain a ``pool`` key for connection settings
        and optional ``batch``/``timeouts`` keys for Brotr-specific settings.

        Args:
            config_path: Path to the YAML configuration file.

        Returns:
            A configured Brotr instance (not yet connected).
        """
        return cls.from_dict(load_yaml(config_path))

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> Brotr:
        """Create a Brotr instance from a configuration dictionary.

        Extracts the ``pool`` key to build the Pool and passes remaining
        keys as BrotrConfig fields (batch sizes, timeouts).
        """
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
        """Raise ValueError if batch exceeds the configured maximum size."""
        if len(batch) > self._config.batch.max_batch_size:
            max_size = self._config.batch.max_batch_size
            raise ValueError(f"{operation} batch size ({len(batch)}) exceeds maximum ({max_size})")

    def _transpose_to_columns(self, params: Sequence[tuple[Any, ...]]) -> tuple[list[Any], ...]:
        """Transpose rows to columns for PostgreSQL array-parameter bulk inserts.

        Converts a list of row tuples into a tuple of column lists, matching
        the parameter layout expected by stored procedures that accept array
        arguments (e.g. ``relays_insert($1::text[], $2::text[], ...)``).

        Args:
            params: Row-oriented data where each tuple is one record.

        Returns:
            Column-oriented data where each list contains all values for
            one column across all rows.

        Raises:
            ValueError: If any row has a different number of columns.
        """
        if not params:
            return ()

        expected_len = len(params[0])
        for i, row in enumerate(params):
            if len(row) != expected_len:
                raise ValueError(f"Row {i} has {len(row)} columns, expected {expected_len}")

        return tuple(list(col) for col in zip(*params, strict=False))

    # Pattern for valid SQL identifiers (prevents injection in procedure calls)
    _VALID_PROCEDURE_NAME: ClassVar[re.Pattern[str]] = re.compile(
        r"^[a-z_][a-z0-9_]*$", re.IGNORECASE
    )

    async def _call_procedure(
        self,
        procedure_name: str,
        *args: Any,
        fetch_result: bool = False,
        timeout: float | None = None,
    ) -> Any:
        """Call a PostgreSQL stored procedure by name.

        Builds a ``SELECT procedure_name($1, $2, ...)`` query with
        parameterized arguments. The procedure name is validated against
        a strict SQL identifier pattern to prevent injection.

        Args:
            procedure_name: Name of the stored procedure. Must match
                ``[a-z_][a-z0-9_]*`` (case-insensitive).
            *args: Arguments passed as parameterized query values.
            fetch_result: If True, return the scalar result (defaulting
                to 0 for None). If False, execute without returning.
            timeout: Query timeout in seconds (None = no timeout).

        Returns:
            The procedure's return value if ``fetch_result`` is True,
            otherwise None.

        Raises:
            ValueError: If ``procedure_name`` is not a valid SQL identifier.
        """
        if not self._VALID_PROCEDURE_NAME.match(procedure_name):
            raise ValueError(
                f"Invalid procedure name '{procedure_name}': "
                "must be a valid SQL identifier (letters, numbers, underscores)"
            )

        params = ", ".join(f"${i + 1}" for i in range(len(args))) if args else ""
        query = f"SELECT {procedure_name}({params})"

        if fetch_result:
            result = await self._pool.fetchval(query, *args, timeout=timeout)
            return result if result is not None else 0
        await self._pool.execute(query, *args, timeout=timeout)
        return None

    # -------------------------------------------------------------------------
    # Generic Query Facade
    # -------------------------------------------------------------------------

    async def fetch(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> list[asyncpg.Record]:
        """Execute a query and return all rows.

        Args:
            query: SQL query with $1, $2, ... placeholders.
            *args: Query parameters.
            timeout: Query timeout in seconds. Defaults to
                ``config.timeouts.query``.
        """
        t = timeout if timeout is not None else self._config.timeouts.query
        return await self._pool.fetch(query, *args, timeout=t)

    async def fetchrow(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> asyncpg.Record | None:
        """Execute a query and return the first row.

        Args:
            query: SQL query with $1, $2, ... placeholders.
            *args: Query parameters.
            timeout: Query timeout in seconds. Defaults to
                ``config.timeouts.query``.
        """
        t = timeout if timeout is not None else self._config.timeouts.query
        return await self._pool.fetchrow(query, *args, timeout=t)

    async def fetchval(self, query: str, *args: Any, timeout: float | None = None) -> Any:
        """Execute a query and return the first column of the first row.

        Args:
            query: SQL query with $1, $2, ... placeholders.
            *args: Query parameters.
            timeout: Query timeout in seconds. Defaults to
                ``config.timeouts.query``.
        """
        t = timeout if timeout is not None else self._config.timeouts.query
        return await self._pool.fetchval(query, *args, timeout=t)

    async def execute(self, query: str, *args: Any, timeout: float | None = None) -> str:
        """Execute a query and return the command status string.

        Args:
            query: SQL query with $1, $2, ... placeholders.
            *args: Query parameters.
            timeout: Query timeout in seconds. Defaults to
                ``config.timeouts.query``.
        """
        t = timeout if timeout is not None else self._config.timeouts.query
        return await self._pool.execute(query, *args, timeout=t)

    def transaction(self) -> AbstractAsyncContextManager[asyncpg.Connection[asyncpg.Record]]:
        """Return a transaction context manager from the pool.

        The transaction commits automatically on normal exit and rolls back
        if an exception propagates.

        Example:
            async with self._brotr.transaction() as conn:
                await conn.execute("INSERT INTO ...")
                await conn.execute("DELETE FROM ...")
        """
        return self._pool.transaction()

    # -------------------------------------------------------------------------
    # Insert Operations
    # -------------------------------------------------------------------------

    async def insert_relays(self, records: list[Relay]) -> int:
        """Bulk-insert relay records into the relays table.

        Args:
            records: Validated Relay dataclass instances.

        Returns:
            Number of new relays inserted (duplicates are skipped).

        Raises:
            asyncpg.PostgresError: On database errors.
            ValueError: If the batch exceeds the configured maximum size.
        """
        if not records:
            return 0

        self._validate_batch_size(records, "insert_relays")

        params = [relay.to_db_params() for relay in records]
        columns = self._transpose_to_columns(params)

        async with self._pool.transaction() as conn:
            inserted: int = (
                await conn.fetchval(
                    "SELECT relays_insert($1, $2, $3)",
                    *columns,
                    timeout=self._config.timeouts.batch,
                )
                or 0
            )

        self._logger.debug("relays_inserted", count=inserted, attempted=len(params))
        return inserted

    async def insert_events(self, records: list[Event]) -> int:
        """Bulk-insert event records into the events table only.

        Does not create relay associations. Use ``insert_events_relays()``
        with ``cascade=True`` to also insert relays and junction records.

        Args:
            records: Validated Event dataclass instances.

        Returns:
            Number of new events inserted (duplicates are skipped).

        Raises:
            asyncpg.PostgresError: On database errors.
            ValueError: If the batch exceeds the configured maximum size.
        """
        if not records:
            return 0

        self._validate_batch_size(records, "insert_events")

        params = [event.to_db_params() for event in records]
        columns = self._transpose_to_columns(params)

        async with self._pool.transaction() as conn:
            inserted: int = (
                await conn.fetchval(
                    "SELECT events_insert($1, $2, $3, $4, $5, $6, $7)",
                    *columns,
                    timeout=self._config.timeouts.batch,
                )
                or 0
            )

        self._logger.debug("events_inserted", count=inserted, attempted=len(params))
        return inserted

    async def insert_events_relays(self, records: list[EventRelay], cascade: bool = True) -> int:
        """Bulk-insert event-relay junction records.

        Args:
            records: Validated EventRelay dataclass instances.
            cascade: If True (default), also inserts the parent relay and
                event records in a single transaction (relays -> events ->
                junctions). If False, only inserts junction rows and
                expects foreign keys to already exist.

        Returns:
            Number of new junction records inserted.

        Raises:
            asyncpg.PostgresError: On database errors.
            ValueError: If the batch exceeds the configured maximum size.
        """
        if not records:
            return 0

        self._validate_batch_size(records, "insert_events_relays")

        params = [event_relay.to_db_params() for event_relay in records]
        columns: tuple[list[Any], ...]

        if cascade:
            # Cascade: relays -> events -> events_relays in one procedure call
            columns = self._transpose_to_columns(params)
            query = (
                "SELECT events_relays_insert_cascade($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)"
            )
        else:
            # Junction-only: caller guarantees foreign keys exist
            event_ids = [p.event_id for p in params]
            relay_urls = [p.relay_url for p in params]
            seen_ats = [p.seen_at for p in params]
            query = "SELECT events_relays_insert($1, $2, $3)"
            columns = (event_ids, relay_urls, seen_ats)

        async with self._pool.transaction() as conn:
            inserted: int = (
                await conn.fetchval(query, *columns, timeout=self._config.timeouts.batch) or 0
            )

        self._logger.debug(
            "events_relays_inserted", count=inserted, attempted=len(params), cascade=cascade
        )
        return inserted

    async def insert_metadata(self, records: list[Metadata]) -> int:
        """Bulk-insert metadata records into the metadata table.

        Metadata is content-addressed: each record's SHA-256 hash serves as
        its primary key, providing automatic deduplication. The hash is
        computed in Python for deterministic behavior across environments.

        Use ``insert_relay_metadata()`` with ``cascade=True`` to also create
        the relay association in a single transaction.

        Args:
            records: Validated Metadata dataclass instances.

        Returns:
            Number of new metadata records inserted (duplicates are skipped).

        Raises:
            asyncpg.PostgresError: On database errors.
            ValueError: If the batch exceeds the configured maximum size.
        """
        if not records:
            return 0

        self._validate_batch_size(records, "insert_metadata")

        params = [metadata.to_db_params() for metadata in records]
        ids = [p.id for p in params]
        values = [p.value for p in params]

        async with self._pool.transaction() as conn:
            inserted: int = (
                await conn.fetchval(
                    "SELECT metadata_insert($1, $2)",
                    ids,
                    values,
                    timeout=self._config.timeouts.batch,
                )
                or 0
            )

        self._logger.debug("metadata_inserted", count=inserted, attempted=len(params))
        return inserted

    async def insert_relay_metadata(
        self, records: list[RelayMetadata], *, cascade: bool = True
    ) -> int:
        """Bulk-insert relay-metadata junction records.

        Links relays to content-addressed metadata records. SHA-256 hashes
        are computed in Python for deterministic deduplication.

        Args:
            records: Validated RelayMetadata dataclass instances.
            cascade: If True (default), also inserts the parent relay and
                metadata records (relays -> metadata -> relay_metadata).
                If False, only inserts junction rows and expects foreign
                keys to already exist.

        Returns:
            Number of new relay-metadata records inserted.

        Raises:
            asyncpg.PostgresError: On database errors.
            ValueError: If the batch exceeds the configured maximum size.
        """
        if not records:
            return 0

        self._validate_batch_size(records, "insert_relay_metadata")

        params = [record.to_db_params() for record in records]

        if cascade:
            # Cascade: relays -> metadata -> relay_metadata in one procedure call
            columns = self._transpose_to_columns(params)

            async with self._pool.transaction() as conn:
                inserted: int = (
                    await conn.fetchval(
                        "SELECT relay_metadata_insert_cascade($1, $2, $3, $4, $5, $6, $7)",
                        *columns,
                        timeout=self._config.timeouts.batch,
                    )
                    or 0
                )
        else:
            # Junction-only: caller guarantees foreign keys exist
            relay_urls = [p.relay_url for p in params]
            metadata_ids = [p.metadata_id for p in params]
            metadata_values = [p.metadata_value for p in params]
            metadata_types = [p.metadata_type for p in params]
            generated_ats = [p.generated_at for p in params]

            async with self._pool.transaction() as conn:
                inserted = (
                    await conn.fetchval(
                        "SELECT relay_metadata_insert($1, $2, $3, $4, $5)",
                        relay_urls,
                        metadata_ids,
                        metadata_values,
                        metadata_types,
                        generated_ats,
                        timeout=self._config.timeouts.batch,
                    )
                    or 0
                )

        self._logger.debug(
            "relay_metadata_inserted",
            count=inserted,
            attempted=len(params),
            cascade=cascade,
        )
        return inserted

    # -------------------------------------------------------------------------
    # Cleanup Operations
    # -------------------------------------------------------------------------

    async def delete_orphan_events(self) -> int:
        """Delete events that have no associated relay in the junction table.

        Orphaned events occur when relays are deleted or events were
        inserted without relay associations. Removing them reclaims
        storage and maintains referential consistency.

        Returns:
            Number of orphaned events deleted.

        Raises:
            asyncpg.PostgresError: On database errors.
        """
        result: int = await self._call_procedure(
            "orphan_events_delete",
            fetch_result=True,
            timeout=self._config.timeouts.cleanup,
        )
        return result

    async def delete_orphan_metadata(self) -> int:
        """Delete metadata records that have no associated relay in the junction table.

        Orphaned metadata occurs when all relay associations for a content-
        addressed blob are removed (e.g., superseded NIP-11 or NIP-66 data).
        Removing them reclaims storage.

        Returns:
            Number of orphaned metadata records deleted.

        Raises:
            asyncpg.PostgresError: On database errors.
        """
        result: int = await self._call_procedure(
            "orphan_metadata_delete",
            fetch_result=True,
            timeout=self._config.timeouts.cleanup,
        )
        return result

    # -------------------------------------------------------------------------
    # Service Data Operations
    # -------------------------------------------------------------------------

    async def upsert_service_data(self, records: list[tuple[str, str, str, dict[str, Any]]]) -> int:
        """Atomically upsert service state records using bulk array parameters.

        Services use this to persist operational state (cursors, checkpoints,
        candidates) across restarts. Each record is identified by the
        composite key (service_name, data_type, key).

        Args:
            records: List of ``(service_name, data_type, key, value)`` tuples.
                - service_name: Owning service (e.g. "finder", "validator").
                - data_type: Category (e.g. "candidate", "cursor", "state").
                - key: Unique identifier within the service/type namespace.
                - value: Arbitrary dict stored as JSONB.

        Returns:
            Number of records upserted.
        """
        if not records:
            return 0

        self._validate_batch_size(records, "upsert_service_data")

        now = int(time.time())
        service_names: list[str] = []
        data_types: list[str] = []
        keys: list[str] = []
        values: list[dict[str, Any]] = []
        updated_ats: list[int] = []

        for service_name, data_type, key, value in records:
            service_names.append(service_name)
            data_types.append(data_type)
            keys.append(key)
            values.append(value)  # asyncpg JSON codec handles dict -> JSONB encoding
            updated_ats.append(now)

        async with self._pool.transaction() as conn:
            await conn.execute(
                "SELECT service_data_upsert($1, $2, $3, $4::jsonb[], $5)",
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
        """Retrieve persisted service state records.

        Args:
            service_name: Owning service name (e.g. "finder").
            data_type: Category of data (e.g. "cursor", "checkpoint").
            key: Specific record key, or None to retrieve all records
                matching the service/type combination.

        Returns:
            List of dicts with keys: ``key``, ``value``, ``updated_at``.
        """
        rows = await self._pool.fetch(
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
        """Atomically delete service state records by composite key.

        Args:
            keys: List of ``(service_name, data_type, key)`` tuples
                identifying the records to remove.

        Returns:
            Number of records actually deleted.
        """
        if not keys:
            return 0

        self._validate_batch_size(keys, "delete_service_data")

        # Transpose to column arrays for the stored procedure
        service_names = [k[0] for k in keys]
        data_types = [k[1] for k in keys]
        data_keys = [k[2] for k in keys]

        async with self._pool.transaction() as conn:
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
    # Refresh Operations
    # -------------------------------------------------------------------------

    async def refresh_matview(self, view_name: str) -> None:
        """Refresh a materialized view concurrently (non-blocking).

        Calls a stored procedure named ``{view_name}_refresh`` which
        performs ``REFRESH MATERIALIZED VIEW CONCURRENTLY``. The view
        name is validated by ``_call_procedure()`` against a strict SQL
        identifier regex to prevent injection.

        Args:
            view_name: Name of the materialized view to refresh.

        Raises:
            ValueError: If the view name is not a valid SQL identifier.
        """
        await self._call_procedure(
            f"{view_name}_refresh",
            timeout=self._config.timeouts.refresh,
        )
        self._logger.debug("matview_refreshed", view=view_name)

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def connect(self) -> None:
        """Connect the underlying pool. Idempotent."""
        await self._pool.connect()
        self._logger.debug("session_started")

    async def close(self) -> None:
        """Close the underlying pool. Idempotent."""
        self._logger.debug("session_ending")
        await self._pool.close()

    # -------------------------------------------------------------------------
    # Context Manager
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> Brotr:
        """Connect the underlying pool on context entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Close the underlying pool on context exit."""
        await self.close()

    def __repr__(self) -> str:
        """Return a human-readable representation with host and connection status."""
        db = self._pool.config.database
        return f"Brotr(host={db.host}, database={db.database}, connected={self._pool.is_connected})"
