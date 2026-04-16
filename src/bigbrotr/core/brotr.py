"""
High-level database interface built on stored procedures.

Provides typed wrappers around PostgreSQL stored procedures for all data
operations: relay management, event ingestion, metadata storage, service
state persistence, and derived-state refresh procedures.

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
    Query modules under ``bigbrotr.services``:
        Domain SQL helpers that use
        [Brotr][bigbrotr.core.brotr.Brotr] for execution.
    [bigbrotr.models][bigbrotr.models]: Dataclass models consumed by the
        insert methods.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

import asyncpg  # noqa: TC002

from bigbrotr.models.service_state import ServiceState

from .brotr_config import BatchConfig, BrotrConfig, TimeoutsConfig
from .logger import Logger
from .pool import Pool
from .yaml import load_yaml


__all__ = ["BatchConfig", "Brotr", "BrotrConfig", "TimeoutsConfig"]


if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager
    from types import TracebackType

    from bigbrotr.models import Event, EventRelay, Metadata, Relay, RelayMetadata


class _DbParamRecord(Protocol):
    """Model contract for Brotr bulk-insert helpers."""

    def to_db_params(self) -> tuple[Any, ...]: ...


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
    live in service query modules, not here.

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

    def _validate_batch_size(self, batch: Sequence[Any], operation: str) -> None:
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

    async def _call_counting_procedure(
        self,
        procedure_name: str,
        *args: Any,
        timeout: float | None,  # noqa: ASYNC109
        log_event: str | None = None,
        attempted: int | None = None,
        **fields: Any,
    ) -> int:
        """Call a procedure that returns a count and optionally emit a debug log."""
        count: int = await self._call_procedure(
            procedure_name,
            *args,
            fetch_result=True,
            timeout=timeout,
        )
        if log_event is not None:
            log_fields: dict[str, Any] = {"count": count, **fields}
            if attempted is not None:
                log_fields["attempted"] = attempted
            self._logger.debug(log_event, **log_fields)
        return count

    async def _insert_record_batch(
        self,
        operation: str,
        procedure_name: str,
        records: Sequence[_DbParamRecord],
        *,
        log_event: str,
        **fields: Any,
    ) -> int:
        """Run a standard bulk insert for record models with ``to_db_params()``."""
        if not records:
            return 0

        self._validate_batch_size(records, operation)
        params = [record.to_db_params() for record in records]
        return await self._call_counting_procedure(
            procedure_name,
            *self._transpose_to_columns(params),
            timeout=self._config.timeouts.batch,
            log_event=log_event,
            attempted=len(params),
            **fields,
        )

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
        return await self._insert_record_batch(
            "insert_relay",
            "relay_insert",
            records,
            log_event="relay_inserted",
        )

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
        return await self._insert_record_batch(
            "insert_event",
            "event_insert",
            records,
            log_event="event_inserted",
        )

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

        return await self._call_counting_procedure(
            procedure,
            *columns,
            timeout=self._config.timeouts.batch,
            log_event="event_relay_inserted",
            attempted=len(params),
            cascade=cascade,
        )

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
            The ``metadata`` table has columns ``id``, ``type``, and
            ``data`` with composite PK ``(id, type)``.
            The SHA-256 hash is computed over the canonical JSON representation
            in the [Metadata][bigbrotr.models.metadata.Metadata] model's
            ``__post_init__`` method.

        See Also:
            [insert_relay_metadata()][bigbrotr.core.brotr.Brotr.insert_relay_metadata]:
                Cascade insert that also creates relay-metadata junction records.
        """
        return await self._insert_record_batch(
            "insert_metadata",
            "metadata_insert",
            records,
            log_event="metadata_inserted",
        )

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

        return await self._call_counting_procedure(
            procedure,
            *columns,
            timeout=self._config.timeouts.batch,
            log_event="relay_metadata_inserted",
            attempted=len(params),
            cascade=cascade,
        )

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
        return await self._call_counting_procedure(
            "orphan_event_delete",
            timeout=self._config.timeouts.cleanup,
        )

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
        return await self._call_counting_procedure(
            "orphan_metadata_delete",
            timeout=self._config.timeouts.cleanup,
        )

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
        return await self._insert_record_batch(
            "upsert_service_state",
            "service_state_upsert",
            records,
            log_event="service_state_upserted",
        )

    async def get_service_state(
        self,
        service_name: str,
        state_type: str,
        key: str | None = None,
    ) -> list[ServiceState]:
        """Retrieve persisted service state records.

        Calls the ``service_state_get`` stored procedure.

        Args:
            service_name: Owning service identifier. Built-in callers
                typically use names from
                [ServiceName][bigbrotr.models.constants.ServiceName], but any
                normalized non-empty string is accepted.
            state_type: Category of state. Built-in callers typically use
                [ServiceStateType][bigbrotr.models.service_state.ServiceStateType],
                but any normalized non-empty string is accepted.
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
            )
            for row in rows
        ]

    async def delete_service_state(
        self,
        service_names: list[str],
        state_types: list[str],
        state_keys: list[str],
    ) -> int:
        """Atomically delete service state records by composite key.

        Calls the ``service_state_delete`` stored procedure with three
        parallel arrays identifying the records to remove.

        Args:
            service_names: Service identifier for each record.
            state_types: State type identifier for each record.
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

        return await self._call_counting_procedure(
            "service_state_delete",
            service_names,
            state_types,
            state_keys,
            timeout=self._config.timeouts.batch,
            log_event="service_state_deleted",
            attempted=len(service_names),
        )

    async def run_refresh_procedure(self, target_name: str) -> None:
        """Run a long-running ``{target_name}_refresh`` stored procedure.

        This helper is intentionally generic: some refresh procedures maintain
        current-state tables, some maintain analytics tables, and others may
        refresh bounded reporting views in custom deployments.

        Args:
            target_name: Logical target whose stored procedure is named
                ``{target_name}_refresh``.

        Raises:
            ValueError: If ``target_name`` is not a valid SQL identifier.
        """
        await self._call_procedure(
            f"{target_name}_refresh",
            timeout=self._config.timeouts.refresh,
        )
        self._logger.debug("refresh_procedure_completed", target=target_name)

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
