"""
High-level database interface built on stored procedures.

Provides typed wrappers around PostgreSQL stored procedures for all data
operations: relay management, event ingestion, metadata storage, service
state persistence, and materialized view maintenance.

Bulk inserts use array parameters to perform the entire batch in a single
database round-trip. All insert methods accept only validated dataclass
instances ([Relay][bigbrotr.models.relay.Relay],
[Event][bigbrotr.models.event.Event],
[EventRelay][bigbrotr.models.event_relay.EventRelay],
[Metadata][bigbrotr.models.metadata.Metadata],
[RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]) to enforce
type safety at the API boundary.

Uses composition with [Pool][bigbrotr.core.pool.Pool] for connection
management and implements an async context manager for automatic pool
lifecycle handling.

See Also:
    [Pool][bigbrotr.core.pool.Pool]: Low-level connection pool that this
        module wraps.
    [bigbrotr.services.common.queries][bigbrotr.services.common.queries]:
        Domain SQL query functions that use
        [Brotr][bigbrotr.core.brotr.Brotr] for execution.
    [bigbrotr.models][bigbrotr.models]: Dataclass models consumed by the
        insert methods.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, ClassVar

import asyncpg  # noqa: TC002
from pydantic import BaseModel, Field, field_validator

from bigbrotr.models.service_state import ServiceState

from .logger import Logger
from .pool import Pool
from .yaml import load_yaml


_MIN_TIMEOUT_SECONDS = 0.1  # Floor for all configurable timeouts


if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager
    from types import TracebackType

    from bigbrotr.models import Event, EventRelay, Metadata, Relay, RelayMetadata
    from bigbrotr.models.constants import ServiceName
    from bigbrotr.models.service_state import ServiceStateType


class BatchConfig(BaseModel):
    """Controls the maximum number of records per bulk insert operation.

    Note:
        The batch size limit prevents excessively large array parameters
        from consuming too much memory in PostgreSQL. All insert methods
        on [Brotr][bigbrotr.core.brotr.Brotr] validate against this limit
        before executing.

    See Also:
        [BrotrConfig][bigbrotr.core.brotr.BrotrConfig]: Parent configuration
            that embeds this model.
    """

    max_size: int = Field(
        default=1000, ge=1, le=100_000, description="Maximum items per batch operation"
    )


class TimeoutsConfig(BaseModel):
    """Timeout settings for [Brotr][bigbrotr.core.brotr.Brotr] operations (in seconds).

    Each timeout can be set to ``None`` for no limit (infinite wait) or to a
    float >= 0.1 seconds. Different categories allow tuning timeouts for
    fast queries vs. slow bulk inserts vs. long-running maintenance tasks.

    Note:
        These timeouts are enforced client-side by asyncpg and are separate
        from the server-side ``statement_timeout`` configured in
        [ServerSettingsConfig][bigbrotr.core.pool.ServerSettingsConfig]. The
        ``refresh`` timeout defaults to ``None`` (infinite) because
        ``REFRESH MATERIALIZED VIEW CONCURRENTLY`` can take minutes on
        large tables.

    See Also:
        [BrotrConfig][bigbrotr.core.brotr.BrotrConfig]: Parent configuration
            that embeds this model.
        [TimeoutsConfig][bigbrotr.core.pool.TimeoutsConfig]:
            Lower-level pool acquisition and health-check timeouts.
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
    """Aggregate configuration for the [Brotr][bigbrotr.core.brotr.Brotr] database interface.

    See Also:
        [BatchConfig][bigbrotr.core.brotr.BatchConfig]: Bulk insert size limits.
        [TimeoutsConfig][bigbrotr.core.brotr.TimeoutsConfig]: Per-category
            timeout settings.
        [Brotr][bigbrotr.core.brotr.Brotr]: The database interface class that
            consumes this configuration.
    """

    batch: BatchConfig = Field(default_factory=BatchConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)


class Brotr:
    """High-level database interface wrapping PostgreSQL stored procedures.

    Brotr is the shared DB contract across all BigBrotr implementations
    (bigbrotr, lilbrotr, ...). It is domain-aware by design: typed insert
    methods accept validated dataclass instances
    ([Relay][bigbrotr.models.relay.Relay],
    [Event][bigbrotr.models.event.Event],
    [EventRelay][bigbrotr.models.event_relay.EventRelay],
    [Metadata][bigbrotr.models.metadata.Metadata],
    [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]) and call
    domain-specific stored procedures. However, all domain SQL queries
    live in ``services/common/queries.py``, not here.

    Bulk inserts use array parameters for single-roundtrip efficiency.
    Uses composition with a private [Pool][bigbrotr.core.pool.Pool]
    instance for connection management. Exposes generic query methods
    ([fetch()][bigbrotr.core.brotr.Brotr.fetch],
    [fetchrow()][bigbrotr.core.brotr.Brotr.fetchrow],
    [fetchval()][bigbrotr.core.brotr.Brotr.fetchval],
    [execute()][bigbrotr.core.brotr.Brotr.execute],
    [transaction()][bigbrotr.core.brotr.Brotr.transaction]) as a facade over
    the pool for custom queries. Implements async context manager for
    automatic pool lifecycle management.

    Examples:
        ```python
        brotr = Brotr.from_yaml("config.yaml")

        async with brotr:
            relay = Relay("wss://relay.example.com")
            await brotr.insert_relay(records=[relay])

            event_relay = EventRelay(event=Event(nostr_event), relay=relay)
            await brotr.insert_event_relay(records=[event_relay])
        ```

    Note:
        The ``_pool`` attribute is intentionally private. Services must use
        [Brotr][bigbrotr.core.brotr.Brotr] methods for all database access,
        never the pool directly. This ensures consistent timeout application,
        batch-size validation, and structured logging across the codebase.

    See Also:
        [Pool][bigbrotr.core.pool.Pool]: The underlying connection pool.
        [BrotrConfig][bigbrotr.core.brotr.BrotrConfig]: Configuration model
            for batch sizes and timeouts.
        [BaseService][bigbrotr.core.base_service.BaseService]: Abstract
            service base class that receives a ``Brotr`` instance.
        [bigbrotr.models.relay.Relay][bigbrotr.models.relay.Relay]: Relay
            dataclass consumed by
            [insert_relay()][bigbrotr.core.brotr.Brotr.insert_relay].
        [bigbrotr.models.event.Event][bigbrotr.models.event.Event]: Event
            dataclass consumed by
            [insert_event()][bigbrotr.core.brotr.Brotr.insert_event].
        [bigbrotr.models.metadata.Metadata][bigbrotr.models.metadata.Metadata]:
            Metadata dataclass consumed by
            [insert_metadata()][bigbrotr.core.brotr.Brotr.insert_metadata].
    """

    def __init__(
        self,
        pool: Pool | None = None,
        config: BrotrConfig | None = None,
    ) -> None:
        """Initialize the database interface.

        The instance is created in a disconnected state. Call
        [connect()][bigbrotr.core.brotr.Brotr.connect] or use the async
        context manager to establish the underlying pool connection.

        Args:
            pool: Connection pool for database access. Creates a default
                [Pool][bigbrotr.core.pool.Pool] if not provided.
            config: Brotr-specific configuration (batch sizes, timeouts).
                Uses default [BrotrConfig][bigbrotr.core.brotr.BrotrConfig]
                if not provided.

        See Also:
            [from_yaml()][bigbrotr.core.brotr.Brotr.from_yaml]: Construct
                from a YAML configuration file.
            [from_dict()][bigbrotr.core.brotr.Brotr.from_dict]: Construct
                from a pre-parsed dictionary.
        """
        self._pool = pool or Pool()
        self._config = config or BrotrConfig()
        self._logger = Logger("brotr")

    @property
    def config(self) -> BrotrConfig:
        """The Brotr configuration (read-only)."""
        return self._config

    @classmethod
    def from_yaml(cls, config_path: str) -> Brotr:
        """Create a Brotr instance from a YAML configuration file.

        The YAML file should contain a ``pool`` key for
        [Pool][bigbrotr.core.pool.Pool] connection settings and optional
        ``batch``/``timeouts`` keys for Brotr-specific settings. Delegates
        to [load_yaml()][bigbrotr.core.yaml.load_yaml] for safe YAML
        parsing.

        Args:
            config_path: Path to the YAML configuration file.

        Returns:
            A configured Brotr instance (not yet connected).

        See Also:
            [from_dict()][bigbrotr.core.brotr.Brotr.from_dict]: Construct
                from a pre-parsed dictionary.
        """
        return cls.from_dict(load_yaml(config_path))

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> Brotr:
        """Create a Brotr instance from a configuration dictionary.

        Extracts the ``pool`` key to build the
        [Pool][bigbrotr.core.pool.Pool] and passes remaining keys as
        [BrotrConfig][bigbrotr.core.brotr.BrotrConfig] fields (batch sizes,
        timeouts).
        """
        pool = None
        if "pool" in config_dict:
            pool = Pool.from_dict(config_dict["pool"])

        brotr_config_dict = {k: v for k, v in config_dict.items() if k != "pool"}
        config = BrotrConfig(**brotr_config_dict) if brotr_config_dict else None

        return cls(pool=pool, config=config)

    def _validate_batch_size(self, batch: list[Any], operation: str) -> None:
        """Raise ValueError if batch exceeds the configured maximum size."""
        if len(batch) > self._config.batch.max_size:
            max_size = self._config.batch.max_size
            raise ValueError(f"{operation} batch size ({len(batch)}) exceeds maximum ({max_size})")

    def _transpose_to_columns(self, params: Sequence[tuple[Any, ...]]) -> tuple[list[Any], ...]:
        """Transpose rows to columns for PostgreSQL array-parameter bulk inserts.

        Converts a list of row tuples into a tuple of column lists, matching
        the parameter layout expected by stored procedures that accept array
        arguments (e.g. ``relay_insert($1::text[], $2::text[], ...)``).

        Args:
            params: Row-oriented data where each tuple is one record,
                typically from ``model.to_db_params()``.

        Returns:
            Column-oriented data where each list contains all values for
            one column across all rows.

        Raises:
            ValueError: If any row has a different number of columns.

        Note:
            This row-to-column transposition enables single-roundtrip bulk
            inserts via PostgreSQL ``UNNEST`` or array parameters. The stored
            procedures expand these parallel arrays into row sets server-side,
            avoiding the overhead of per-row ``INSERT`` statements.
        """
        if not params:
            return ()

        expected_len = len(params[0])
        for i, row in enumerate(params):
            if len(row) != expected_len:
                raise ValueError(f"Row {i} has {len(row)} columns, expected {expected_len}")

        return tuple(list(col) for col in zip(*params, strict=True))

    # Pattern for valid SQL identifiers (prevents injection in procedure calls)
    _VALID_PROCEDURE_NAME: ClassVar[re.Pattern[str]] = re.compile(r"^[a-z_][a-z0-9_]*$")

    async def _call_procedure(
        self,
        procedure_name: str,
        *args: Any,
        fetch_result: bool = False,
        timeout: float | None = None,  # noqa: ASYNC109
    ) -> Any:
        """Call a PostgreSQL stored procedure by name.

        Builds a ``SELECT procedure_name($1, $2, ...)`` query with
        parameterized arguments. The procedure name is validated against
        a strict SQL identifier pattern to prevent injection.

        Args:
            procedure_name: Name of the stored procedure. Must match
                ``[a-z_][a-z0-9_]*``.
            *args: Arguments passed as parameterized query values.
            fetch_result: If ``True``, return the scalar result (defaulting
                to ``0`` for ``None``). If ``False``, execute without returning.
            timeout: Query timeout in seconds (``None`` = no timeout).

        Returns:
            The procedure's return value if ``fetch_result`` is ``True``,
            otherwise ``None``.

        Raises:
            ValueError: If ``procedure_name`` is not a valid SQL identifier.

        Warning:
            The procedure name is interpolated into the SQL string (not
            parameterized), so it is validated against ``_VALID_PROCEDURE_NAME``
            to prevent SQL injection. Only lowercase letters, digits, and
            underscores are permitted.
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

    async def fetch(
        self,
        query: str,
        *args: Any,
    ) -> list[asyncpg.Record]:
        """Execute a query and return all rows.

        Delegates to [Pool.fetch()][bigbrotr.core.pool.Pool.fetch] with
        timeout from
        [config.timeouts.query][bigbrotr.core.brotr.TimeoutsConfig].

        Args:
            query: SQL query with ``$1``, ``$2``, ... placeholders.
            *args: Query parameters.
        """
        return await self._pool.fetch(query, *args, timeout=self._config.timeouts.query)

    async def fetchrow(
        self,
        query: str,
        *args: Any,
    ) -> asyncpg.Record | None:
        """Execute a query and return the first row.

        Delegates to [Pool.fetchrow()][bigbrotr.core.pool.Pool.fetchrow] with
        timeout from
        [config.timeouts.query][bigbrotr.core.brotr.TimeoutsConfig].

        Args:
            query: SQL query with ``$1``, ``$2``, ... placeholders.
            *args: Query parameters.
        """
        return await self._pool.fetchrow(query, *args, timeout=self._config.timeouts.query)

    async def fetchval(self, query: str, *args: Any) -> Any:
        """Execute a query and return the first column of the first row.

        Delegates to [Pool.fetchval()][bigbrotr.core.pool.Pool.fetchval] with
        timeout from
        [config.timeouts.query][bigbrotr.core.brotr.TimeoutsConfig].

        Args:
            query: SQL query with ``$1``, ``$2``, ... placeholders.
            *args: Query parameters.
        """
        return await self._pool.fetchval(query, *args, timeout=self._config.timeouts.query)

    async def execute(self, query: str, *args: Any) -> str:
        """Execute a query and return the command status string.

        Delegates to [Pool.execute()][bigbrotr.core.pool.Pool.execute] with
        timeout from
        [config.timeouts.query][bigbrotr.core.brotr.TimeoutsConfig].

        Args:
            query: SQL query with ``$1``, ``$2``, ... placeholders.
            *args: Query parameters.
        """
        return await self._pool.execute(query, *args, timeout=self._config.timeouts.query)

    def transaction(self) -> AbstractAsyncContextManager[asyncpg.Connection[asyncpg.Record]]:
        """Return a transaction context manager from the pool.

        The transaction commits automatically on normal exit and rolls back
        if an exception propagates. Delegates to
        [Pool.transaction()][bigbrotr.core.pool.Pool.transaction].

        Yields:
            An asyncpg connection with an active transaction. The
            transaction commits on normal exit and rolls back on exception.

        Examples:
            ```python
            async with brotr.transaction() as conn:
                await conn.execute("INSERT INTO ...")
                await conn.execute("DELETE FROM ...")
            ```

        See Also:
            [Pool.transaction()][bigbrotr.core.pool.Pool.transaction]:
                Underlying pool method.
        """
        return self._pool.transaction()

    async def insert_relay(self, records: list[Relay]) -> int:
        """Bulk-insert relay records into the ``relay`` table.

        Calls the ``relay_insert`` stored procedure with transposed column
        arrays for single-roundtrip efficiency.

        Args:
            records: Validated [Relay][bigbrotr.models.relay.Relay] dataclass
                instances.

        Returns:
            Number of new relays inserted (duplicates are skipped).

        Raises:
            asyncpg.PostgresError: On database errors.
            ValueError: If the batch exceeds the configured maximum size
                from [BatchConfig][bigbrotr.core.brotr.BatchConfig].

        See Also:
            [insert_event_relay()][bigbrotr.core.brotr.Brotr.insert_event_relay]:
                Cascade insert that also creates relay records.
        """
        if not records:
            return 0

        self._validate_batch_size(records, "insert_relay")

        params = [relay.to_db_params() for relay in records]
        columns = self._transpose_to_columns(params)

        inserted: int = await self._call_procedure(
            "relay_insert",
            *columns,
            fetch_result=True,
            timeout=self._config.timeouts.batch,
        )

        self._logger.debug("relay_inserted", count=inserted, attempted=len(params))
        return inserted

    async def insert_event(self, records: list[Event]) -> int:
        """Bulk-insert event records into the ``event`` table only.

        Does not create relay associations. Use
        [insert_event_relay()][bigbrotr.core.brotr.Brotr.insert_event_relay]
        with ``cascade=True`` to also insert relays and junction records.

        Args:
            records: Validated [Event][bigbrotr.models.event.Event] dataclass
                instances.

        Returns:
            Number of new events inserted (duplicates are skipped).

        Raises:
            asyncpg.PostgresError: On database errors.
            ValueError: If the batch exceeds the configured maximum size
                from [BatchConfig][bigbrotr.core.brotr.BatchConfig].

        See Also:
            [insert_event_relay()][bigbrotr.core.brotr.Brotr.insert_event_relay]:
                Cascade insert that creates events, relays, and junction records
                in a single stored procedure call.
        """
        if not records:
            return 0

        self._validate_batch_size(records, "insert_event")

        params = [event.to_db_params() for event in records]
        columns = self._transpose_to_columns(params)

        inserted: int = await self._call_procedure(
            "event_insert",
            *columns,
            fetch_result=True,
            timeout=self._config.timeouts.batch,
        )

        self._logger.debug("event_inserted", count=inserted, attempted=len(params))
        return inserted

    async def insert_event_relay(self, records: list[EventRelay], *, cascade: bool = True) -> int:
        """Bulk-insert event-relay junction records.

        Args:
            records: Validated
                [EventRelay][bigbrotr.models.event_relay.EventRelay] dataclass
                instances.
            cascade: If ``True`` (default), also inserts the parent
                [Relay][bigbrotr.models.relay.Relay] and
                [Event][bigbrotr.models.event.Event] records atomically
                (relays -> events -> junctions) via the
                ``event_relay_insert_cascade`` stored procedure. If
                ``False``, only inserts junction rows via
                ``event_relay_insert`` and expects foreign keys to already
                exist.

        Returns:
            Number of new junction records inserted.

        Raises:
            asyncpg.PostgresError: On database errors.
            ValueError: If the batch exceeds the configured maximum size
                from [BatchConfig][bigbrotr.core.brotr.BatchConfig].

        See Also:
            [insert_event()][bigbrotr.core.brotr.Brotr.insert_event]:
                Insert events without relay associations.
            [insert_relay()][bigbrotr.core.brotr.Brotr.insert_relay]:
                Insert relays without event associations.
        """
        if not records:
            return 0

        self._validate_batch_size(records, "insert_event_relay")

        params = [event_relay.to_db_params() for event_relay in records]
        columns: tuple[list[Any], ...]

        if cascade:
            # Cascade: relay -> event -> event_relay in one procedure call
            columns = self._transpose_to_columns(params)
            procedure = "event_relay_insert_cascade"
        else:
            # Junction-only: caller guarantees foreign keys exist
            event_ids = [p.event_id for p in params]
            relay_urls = [p.relay_url for p in params]
            seen_ats = [p.seen_at for p in params]
            procedure = "event_relay_insert"
            columns = (event_ids, relay_urls, seen_ats)

        inserted: int = await self._call_procedure(
            procedure,
            *columns,
            fetch_result=True,
            timeout=self._config.timeouts.batch,
        )

        self._logger.debug(
            "event_relay_inserted", count=inserted, attempted=len(params), cascade=cascade
        )
        return inserted

    async def insert_metadata(self, records: list[Metadata]) -> int:
        """Bulk-insert metadata records into the ``metadata`` table.

        Metadata is content-addressed: each record's SHA-256 hash combined
        with its metadata type forms the composite primary key, providing
        automatic deduplication within each type. The hash is computed in
        Python for deterministic behavior across environments.

        Use
        [insert_relay_metadata()][bigbrotr.core.brotr.Brotr.insert_relay_metadata]
        with ``cascade=True`` to also create the relay association in a
        single stored procedure call.

        Args:
            records: Validated [Metadata][bigbrotr.models.metadata.Metadata]
                dataclass instances.

        Returns:
            Number of new metadata records inserted (duplicates are skipped).

        Raises:
            asyncpg.PostgresError: On database errors.
            ValueError: If the batch exceeds the configured maximum size
                from [BatchConfig][bigbrotr.core.brotr.BatchConfig].

        Note:
            The ``metadata`` table has columns ``id``, ``metadata_type``, and
            ``data`` with composite PK ``(id, metadata_type)``.
            The SHA-256 hash is computed over the canonical JSON representation
            in the [Metadata][bigbrotr.models.metadata.Metadata] model's
            ``__post_init__`` method.

        See Also:
            [insert_relay_metadata()][bigbrotr.core.brotr.Brotr.insert_relay_metadata]:
                Cascade insert that also creates relay-metadata junction records.
        """
        if not records:
            return 0

        self._validate_batch_size(records, "insert_metadata")

        params = [metadata.to_db_params() for metadata in records]
        columns = self._transpose_to_columns(params)

        inserted: int = await self._call_procedure(
            "metadata_insert",
            *columns,
            fetch_result=True,
            timeout=self._config.timeouts.batch,
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
            records: Validated
                [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]
                dataclass instances.
            cascade: If ``True`` (default), also inserts the parent
                [Relay][bigbrotr.models.relay.Relay] and
                [Metadata][bigbrotr.models.metadata.Metadata] records
                (relays -> metadata -> relay_metadata) via the
                ``relay_metadata_insert_cascade`` stored procedure. If
                ``False``, only inserts junction rows via
                ``relay_metadata_insert`` and expects foreign keys to
                already exist.

        Returns:
            Number of new relay-metadata records inserted.

        Raises:
            asyncpg.PostgresError: On database errors.
            ValueError: If the batch exceeds the configured maximum size
                from [BatchConfig][bigbrotr.core.brotr.BatchConfig].

        See Also:
            [insert_metadata()][bigbrotr.core.brotr.Brotr.insert_metadata]:
                Insert metadata without relay associations.
            [insert_relay()][bigbrotr.core.brotr.Brotr.insert_relay]:
                Insert relays without metadata associations.
        """
        if not records:
            return 0

        self._validate_batch_size(records, "insert_relay_metadata")

        params = [record.to_db_params() for record in records]

        if cascade:
            # Cascade: relays -> metadata -> relay_metadata in one procedure call
            columns = self._transpose_to_columns(params)
            procedure = "relay_metadata_insert_cascade"
        else:
            # Junction-only: caller guarantees foreign keys exist
            relay_urls = [p.relay_url for p in params]
            metadata_ids = [p.metadata_id for p in params]
            metadata_types = [p.metadata_type for p in params]
            generated_ats = [p.generated_at for p in params]
            procedure = "relay_metadata_insert"
            columns = (relay_urls, metadata_ids, metadata_types, generated_ats)

        inserted: int = await self._call_procedure(
            procedure,
            *columns,
            fetch_result=True,
            timeout=self._config.timeouts.batch,
        )

        self._logger.debug(
            "relay_metadata_inserted",
            count=inserted,
            attempted=len(params),
            cascade=cascade,
        )
        return inserted

    async def delete_orphan_event(self) -> int:
        """Delete events that have no associated relay in the junction table.

        Orphaned events occur when relays are deleted or events were
        inserted without relay associations. Removing them reclaims
        storage and maintains referential consistency. Calls the
        ``orphan_event_delete`` stored procedure.

        Returns:
            Number of orphaned events deleted.

        Raises:
            asyncpg.PostgresError: On database errors.

        See Also:
            [delete_orphan_metadata()][bigbrotr.core.brotr.Brotr.delete_orphan_metadata]:
                Companion cleanup for orphaned metadata records.
        """
        result: int = await self._call_procedure(
            "orphan_event_delete",
            fetch_result=True,
            timeout=self._config.timeouts.cleanup,
        )
        return result

    async def delete_orphan_metadata(self) -> int:
        """Delete metadata records that have no associated relay in the junction table.

        Orphaned metadata occurs when all relay associations for a content-
        addressed blob are removed (e.g., superseded NIP-11 or NIP-66 data).
        Removing them reclaims storage. Calls the ``orphan_metadata_delete``
        stored procedure.

        Returns:
            Number of orphaned metadata records deleted.

        Raises:
            asyncpg.PostgresError: On database errors.

        See Also:
            [delete_orphan_event()][bigbrotr.core.brotr.Brotr.delete_orphan_event]:
                Companion cleanup for orphaned event records.
        """
        result: int = await self._call_procedure(
            "orphan_metadata_delete",
            fetch_result=True,
            timeout=self._config.timeouts.cleanup,
        )
        return result

    async def upsert_service_state(self, records: list[ServiceState]) -> int:
        """Atomically upsert service state records using bulk array parameters.

        Services use this to persist operational state (cursors, monitoring
        markers, publication markers, candidates) across restarts. Each record is identified by the
        composite key ``(service_name, state_type, state_key)``. Calls the
        ``service_state_upsert`` stored procedure.

        Args:
            records: List of
                [ServiceState][bigbrotr.models.service_state.ServiceState]
                dataclass instances.

        Returns:
            Number of records upserted.

        See Also:
            [get_service_state()][bigbrotr.core.brotr.Brotr.get_service_state]:
                Retrieve persisted state records.
            [delete_service_state()][bigbrotr.core.brotr.Brotr.delete_service_state]:
                Remove persisted state records.
        """
        if not records:
            return 0

        self._validate_batch_size(records, "upsert_service_state")

        params = [r.to_db_params() for r in records]
        columns = self._transpose_to_columns(params)

        # Procedure returns VOID; no DB-confirmed count available
        await self._call_procedure(
            "service_state_upsert",
            *columns,
            fetch_result=False,
            timeout=self._config.timeouts.batch,
        )

        self._logger.debug("service_state_upserted", count=len(records))
        return len(records)

    async def get_service_state(
        self,
        service_name: ServiceName,
        state_type: ServiceStateType,
        key: str | None = None,
    ) -> list[ServiceState]:
        """Retrieve persisted service state records.

        Calls the ``service_state_get`` stored procedure.

        Args:
            service_name: Owning service name (e.g.
                ``ServiceName.FINDER``).
            state_type: Category of state. See
                [ServiceStateType][bigbrotr.models.service_state.ServiceStateType]
                for the canonical enum values.
            key: Specific record key, or ``None`` to retrieve all records
                matching the service/type combination.

        Returns:
            List of [ServiceState][bigbrotr.models.service_state.ServiceState]
            instances reconstructed from the database rows.

        See Also:
            [upsert_service_state()][bigbrotr.core.brotr.Brotr.upsert_service_state]:
                Persist state records.
            [delete_service_state()][bigbrotr.core.brotr.Brotr.delete_service_state]:
                Remove state records.
        """
        rows = await self.fetch(
            "SELECT * FROM service_state_get($1, $2, $3)",
            service_name,
            state_type,
            key,
        )

        return [
            ServiceState(
                service_name=service_name,
                state_type=state_type,
                state_key=row["state_key"],
                state_value=row["state_value"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def delete_service_state(
        self,
        service_names: list[ServiceName],
        state_types: list[ServiceStateType],
        state_keys: list[str],
    ) -> int:
        """Atomically delete service state records by composite key.

        Calls the ``service_state_delete`` stored procedure with three
        parallel arrays identifying the records to remove.

        Args:
            service_names: Service name for each record.
            state_types: State type for each record.
            state_keys: State key for each record.

        Returns:
            Number of records actually deleted.

        See Also:
            [upsert_service_state()][bigbrotr.core.brotr.Brotr.upsert_service_state]:
                Persist state records.
            [get_service_state()][bigbrotr.core.brotr.Brotr.get_service_state]:
                Retrieve state records.
        """
        if not service_names:
            return 0

        if not (len(service_names) == len(state_types) == len(state_keys)):
            raise ValueError(
                f"Parallel arrays must have equal length: "
                f"service_names={len(service_names)}, "
                f"state_types={len(state_types)}, "
                f"state_keys={len(state_keys)}"
            )

        self._validate_batch_size(service_names, "delete_service_state")

        deleted: int = await self._call_procedure(
            "service_state_delete",
            service_names,
            state_types,
            state_keys,
            fetch_result=True,
            timeout=self._config.timeouts.batch,
        )

        self._logger.debug(
            "service_state_deleted",
            count=deleted,
            attempted=len(service_names),
        )
        return deleted

    async def refresh_materialized_view(self, view_name: str) -> None:
        """Refresh a materialized view concurrently (non-blocking).

        Calls a stored procedure named ``{view_name}_refresh`` which
        performs ``REFRESH MATERIALIZED VIEW CONCURRENTLY``. The view
        name is validated by
        ``_call_procedure()``
        against a strict SQL identifier regex to prevent injection.

        Args:
            view_name: Name of the materialized view to refresh
                (e.g. ``"relay_metadata_latest"``, ``"event_stats"``).

        Raises:
            ValueError: If the view name is not a valid SQL identifier.

        Note:
            The timeout for refresh operations defaults to ``None``
            (infinite) via
            [TimeoutsConfig.refresh][bigbrotr.core.brotr.TimeoutsConfig]
            because ``REFRESH MATERIALIZED VIEW CONCURRENTLY`` can take
            several minutes on large tables with complex indexes.
        """
        await self._call_procedure(
            f"{view_name}_refresh",
            timeout=self._config.timeouts.refresh,
        )
        self._logger.debug("matview_refreshed", view=view_name)

    async def connect(self) -> None:
        """Connect the underlying pool. Idempotent."""
        await self._pool.connect()
        self._logger.debug("session_started")

    async def close(self) -> None:
        """Close the underlying pool. Idempotent."""
        self._logger.debug("session_ending")
        await self._pool.close()

    async def __aenter__(self) -> Brotr:
        """Connect the underlying pool on context entry."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Close the underlying pool on context exit."""
        await self.close()

    def __repr__(self) -> str:
        """Return a human-readable representation with host and connection status."""
        db = self._pool.config.database
        return f"Brotr(host={db.host}, database={db.database}, connected={self._pool.is_connected})"
