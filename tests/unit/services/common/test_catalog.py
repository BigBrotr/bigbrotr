"""Unit tests for services.common.catalog module.

Tests:
- TablePolicy and DvmTablePolicy Pydantic models
- ColumnSchema, TableSchema, QueryResult dataclasses
- Catalog schema discovery
- Catalog query builder
- Catalog PK lookup
- Filter parsing and sort parsing
"""

from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.services.common.catalog import (
    Catalog,
    CatalogError,
    ColumnSchema,
    DvmTablePolicy,
    QueryResult,
    TablePolicy,
    TableSchema,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def catalog_brotr(mock_brotr: Brotr) -> Brotr:
    """Brotr mock for catalog tests."""
    return mock_brotr


@pytest.fixture
def sample_columns() -> tuple[ColumnSchema, ...]:
    """Sample columns for a relay table."""
    return (
        ColumnSchema(name="url", pg_type="text", nullable=False),
        ColumnSchema(name="network", pg_type="text", nullable=False),
        ColumnSchema(name="discovered_at", pg_type="bigint", nullable=False),
    )


@pytest.fixture
def sample_table(sample_columns: tuple[ColumnSchema, ...]) -> TableSchema:
    """Sample table schema."""
    return TableSchema(
        name="relay",
        columns=sample_columns,
        primary_key=("url",),
        is_view=False,
    )


@pytest.fixture
def sample_bytea_table() -> TableSchema:
    """Table with bytea columns."""
    return TableSchema(
        name="event",
        columns=(
            ColumnSchema(name="id", pg_type="bytea", nullable=False),
            ColumnSchema(name="pubkey", pg_type="bytea", nullable=False),
            ColumnSchema(name="created_at", pg_type="bigint", nullable=False),
            ColumnSchema(name="kind", pg_type="integer", nullable=False),
        ),
        primary_key=("id",),
        is_view=False,
    )


@pytest.fixture
def populated_catalog(sample_table: TableSchema, sample_bytea_table: TableSchema) -> Catalog:
    """Catalog with pre-populated tables."""
    catalog = Catalog()
    catalog._tables = {
        sample_table.name: sample_table,
        sample_bytea_table.name: sample_bytea_table,
    }
    return catalog


# ============================================================================
# TablePolicy Tests
# ============================================================================


class TestTablePolicy:
    """Tests for TablePolicy Pydantic model."""

    def test_default_enabled(self) -> None:
        policy = TablePolicy()
        assert policy.enabled is True

    def test_disabled(self) -> None:
        policy = TablePolicy(enabled=False)
        assert policy.enabled is False

    def test_from_dict(self) -> None:
        policy = TablePolicy.model_validate({"enabled": False})
        assert policy.enabled is False


class TestDvmTablePolicy:
    """Tests for DvmTablePolicy Pydantic model."""

    def test_default_values(self) -> None:
        policy = DvmTablePolicy()
        assert policy.enabled is True
        assert policy.price == 0

    def test_with_price(self) -> None:
        policy = DvmTablePolicy(price=5000)
        assert policy.price == 5000

    def test_negative_price_rejected(self) -> None:
        with pytest.raises(ValueError):
            DvmTablePolicy(price=-1)

    def test_inherits_enabled(self) -> None:
        policy = DvmTablePolicy(enabled=False, price=100)
        assert policy.enabled is False
        assert policy.price == 100


# ============================================================================
# Dataclass Tests
# ============================================================================


class TestColumnSchema:
    """Tests for ColumnSchema dataclass."""

    def test_construction(self) -> None:
        col = ColumnSchema(name="url", pg_type="text", nullable=False)
        assert col.name == "url"
        assert col.pg_type == "text"
        assert col.nullable is False

    def test_frozen(self) -> None:
        col = ColumnSchema(name="url", pg_type="text", nullable=False)
        with pytest.raises(AttributeError):
            col.name = "other"  # type: ignore[misc]


class TestTableSchema:
    """Tests for TableSchema dataclass."""

    def test_construction(self, sample_table: TableSchema) -> None:
        assert sample_table.name == "relay"
        assert len(sample_table.columns) == 3
        assert sample_table.primary_key == ("url",)
        assert sample_table.is_view is False

    def test_frozen(self, sample_table: TableSchema) -> None:
        with pytest.raises(AttributeError):
            sample_table.name = "other"  # type: ignore[misc]

    def test_view(self) -> None:
        schema = TableSchema(name="relay_stats", columns=(), primary_key=(), is_view=True)
        assert schema.is_view is True
        assert schema.primary_key == ()


class TestQueryResult:
    """Tests for QueryResult dataclass."""

    def test_construction(self) -> None:
        result = QueryResult(rows=[{"a": 1}], total=10, limit=5, offset=0)
        assert result.rows == [{"a": 1}]
        assert result.total == 10
        assert result.limit == 5
        assert result.offset == 0

    def test_empty(self) -> None:
        result = QueryResult(rows=[], total=0, limit=100, offset=0)
        assert result.rows == []
        assert result.total == 0


# ============================================================================
# Catalog Discovery Tests
# ============================================================================


class TestCatalogDiscover:
    """Tests for Catalog.discover()."""

    def test_initial_state(self) -> None:
        catalog = Catalog()
        assert catalog.tables == {}

    async def test_discover_tables_and_matviews(self, catalog_brotr: Brotr) -> None:
        catalog = Catalog()

        def _attr_getter(obj: MagicMock, key: str) -> object:
            return getattr(obj, key)

        # Mock information_schema.tables (now returns table_type)
        table_rows = [
            MagicMock(table_name="relay", table_type="BASE TABLE"),
            MagicMock(table_name="event", table_type="BASE TABLE"),
            MagicMock(table_name="active_relays", table_type="VIEW"),
        ]
        for row in table_rows:
            row.__getitem__ = _attr_getter

        # Mock pg_matviews
        matview_rows = [MagicMock(table_name="relay_stats")]
        for row in matview_rows:
            row.__getitem__ = _attr_getter

        # Mock columns (now via pg_attribute — is_nullable is bool)
        col_rows = [
            MagicMock(table_name="relay", column_name="url", data_type="text", is_nullable=False),
            MagicMock(table_name="event", column_name="id", data_type="bytea", is_nullable=False),
            MagicMock(
                table_name="relay_stats", column_name="url", data_type="text", is_nullable=False
            ),
            MagicMock(
                table_name="active_relays", column_name="url", data_type="text", is_nullable=False
            ),
        ]
        for row in col_rows:
            row.__getitem__ = _attr_getter

        # Mock PKs
        pk_rows = [MagicMock(table_name="relay", column_name="url", pos=1)]
        for row in pk_rows:
            row.__getitem__ = _attr_getter

        async def mock_fetch(query: str, *args: object, **kwargs: object) -> list[MagicMock]:
            if "information_schema.tables" in query:
                return table_rows
            if "pg_matviews" in query:
                return matview_rows
            if "pg_attribute" in query:
                return col_rows
            if "pg_constraint" in query:
                return pk_rows
            if "pg_index" in query:
                return []
            return []

        catalog_brotr.fetch = AsyncMock(side_effect=mock_fetch)  # type: ignore[method-assign]
        await catalog.discover(catalog_brotr)

        assert "relay" in catalog.tables
        assert "event" in catalog.tables
        assert "relay_stats" in catalog.tables
        assert "active_relays" in catalog.tables
        # Base tables are NOT views
        assert catalog.tables["relay"].is_view is False
        assert catalog.tables["event"].is_view is False
        # Regular views and matviews ARE views
        assert catalog.tables["relay_stats"].is_view is True
        assert catalog.tables["active_relays"].is_view is True

    async def test_discover_empty_schema(self, catalog_brotr: Brotr) -> None:
        catalog = Catalog()
        catalog_brotr.fetch = AsyncMock(return_value=[])  # type: ignore[method-assign]

        await catalog.discover(catalog_brotr)
        assert catalog.tables == {}

    async def test_discover_matview_columns_included(self, catalog_brotr: Brotr) -> None:
        """Matview columns are discovered via pg_attribute (not information_schema)."""
        catalog = Catalog()

        def _attr_getter(obj: MagicMock, key: str) -> object:
            return getattr(obj, key)

        # No base tables or views
        matview_rows = [MagicMock(table_name="relay_stats")]
        for row in matview_rows:
            row.__getitem__ = _attr_getter

        # pg_attribute returns matview columns
        col_rows = [
            MagicMock(
                table_name="relay_stats", column_name="url", data_type="text", is_nullable=False
            ),
            MagicMock(
                table_name="relay_stats",
                column_name="event_count",
                data_type="bigint",
                is_nullable=False,
            ),
        ]
        for row in col_rows:
            row.__getitem__ = _attr_getter

        async def mock_fetch(query: str, *args: object, **kwargs: object) -> list[MagicMock]:
            if "information_schema.tables" in query:
                return []
            if "pg_matviews" in query:
                return matview_rows
            if "pg_attribute" in query:
                return col_rows
            if "pg_index" in query:
                return []
            return []

        catalog_brotr.fetch = AsyncMock(side_effect=mock_fetch)  # type: ignore[method-assign]
        await catalog.discover(catalog_brotr)

        assert "relay_stats" in catalog.tables
        assert len(catalog.tables["relay_stats"].columns) == 2

    async def test_discover_matview_unique_index_first_only(self, catalog_brotr: Brotr) -> None:
        """Only the first unique index per matview is used for primary key."""
        catalog = Catalog()

        def _attr_getter(obj: MagicMock, key: str) -> object:
            return getattr(obj, key)

        matview_rows = [MagicMock(table_name="relay_stats")]
        for row in matview_rows:
            row.__getitem__ = _attr_getter

        col_rows = [
            MagicMock(
                table_name="relay_stats", column_name="url", data_type="text", is_nullable=False
            ),
        ]
        for row in col_rows:
            row.__getitem__ = _attr_getter

        # Two unique indexes: first has cols (url), second has (url, extra)
        idx_rows = [
            MagicMock(table_name="relay_stats", index_oid=100, column_name="url", pos=1),
            MagicMock(table_name="relay_stats", index_oid=200, column_name="url", pos=1),
            MagicMock(table_name="relay_stats", index_oid=200, column_name="extra", pos=2),
        ]
        for row in idx_rows:
            row.__getitem__ = _attr_getter

        async def mock_fetch(query: str, *args: object, **kwargs: object) -> list[MagicMock]:
            if "information_schema.tables" in query:
                return []
            if "pg_matviews" in query:
                return matview_rows
            if "pg_attribute" in query:
                return col_rows
            if "pg_index" in query:
                return idx_rows
            return []

        catalog_brotr.fetch = AsyncMock(side_effect=mock_fetch)  # type: ignore[method-assign]
        await catalog.discover(catalog_brotr)

        # Only first index columns should be used
        assert catalog.tables["relay_stats"].primary_key == ("url",)


# ============================================================================
# Catalog Query Tests
# ============================================================================


class TestCatalogQuery:
    """Tests for Catalog.query()."""

    async def test_basic_query(self, populated_catalog: Catalog, catalog_brotr: Brotr) -> None:
        mock_row = MagicMock()
        mock_row.items.return_value = [
            ("url", "wss://relay.example.com"),
            ("network", "clearnet"),
            ("discovered_at", 100),
        ]
        mock_row.__iter__ = lambda self: iter(self.items())
        mock_row.keys.return_value = ["url", "network", "discovered_at"]
        mock_row.__getitem__ = lambda self, key: dict(self.items())[key]

        catalog_brotr.fetchval = AsyncMock(return_value=1)  # type: ignore[method-assign]
        catalog_brotr.fetch = AsyncMock(return_value=[mock_row])  # type: ignore[method-assign]

        result = await populated_catalog.query(
            catalog_brotr,
            "relay",
            limit=10,
            offset=0,
        )

        assert result.total == 1
        assert result.limit == 10
        assert result.offset == 0
        assert len(result.rows) == 1

    async def test_query_unknown_table(
        self, populated_catalog: Catalog, catalog_brotr: Brotr
    ) -> None:
        with pytest.raises(CatalogError, match="Unknown table"):
            await populated_catalog.query(catalog_brotr, "nonexistent", limit=10, offset=0)

    async def test_query_limit_clamped(
        self, populated_catalog: Catalog, catalog_brotr: Brotr
    ) -> None:
        catalog_brotr.fetchval = AsyncMock(return_value=0)  # type: ignore[method-assign]
        catalog_brotr.fetch = AsyncMock(return_value=[])  # type: ignore[method-assign]

        result = await populated_catalog.query(
            catalog_brotr,
            "relay",
            limit=99999,
            offset=0,
            max_page_size=1000,
        )
        assert result.limit == 1000

    async def test_query_offset_clamped(
        self, populated_catalog: Catalog, catalog_brotr: Brotr
    ) -> None:
        catalog_brotr.fetchval = AsyncMock(return_value=0)  # type: ignore[method-assign]
        catalog_brotr.fetch = AsyncMock(return_value=[])  # type: ignore[method-assign]

        result = await populated_catalog.query(
            catalog_brotr,
            "relay",
            limit=10,
            offset=200_000,
        )
        assert result.offset == 100_000

    async def test_query_negative_limit_clamped(
        self,
        populated_catalog: Catalog,
        catalog_brotr: Brotr,
    ) -> None:
        catalog_brotr.fetchval = AsyncMock(return_value=0)  # type: ignore[method-assign]
        catalog_brotr.fetch = AsyncMock(return_value=[])  # type: ignore[method-assign]

        result = await populated_catalog.query(
            catalog_brotr,
            "relay",
            limit=-5,
            offset=0,
        )
        assert result.limit == 1

    async def test_query_negative_offset_clamped(
        self,
        populated_catalog: Catalog,
        catalog_brotr: Brotr,
    ) -> None:
        catalog_brotr.fetchval = AsyncMock(return_value=0)  # type: ignore[method-assign]
        catalog_brotr.fetch = AsyncMock(return_value=[])  # type: ignore[method-assign]

        result = await populated_catalog.query(
            catalog_brotr,
            "relay",
            limit=10,
            offset=-100,
        )
        assert result.offset == 0

    async def test_query_with_multiple_filters(
        self,
        populated_catalog: Catalog,
        catalog_brotr: Brotr,
    ) -> None:
        catalog_brotr.fetchval = AsyncMock(return_value=0)  # type: ignore[method-assign]
        catalog_brotr.fetch = AsyncMock(return_value=[])  # type: ignore[method-assign]

        await populated_catalog.query(
            catalog_brotr,
            "relay",
            limit=10,
            offset=0,
            filters={"network": "clearnet", "discovered_at": ">=:1000000"},
        )

        # Verify correct parameter indexing ($1, $2 for filters, $3/$4 for limit/offset)
        data_args = catalog_brotr.fetch.call_args
        sql = data_args[0][0]
        assert "$1" in sql
        assert "$2" in sql
        assert "AND" in sql

    async def test_query_with_filter(
        self, populated_catalog: Catalog, catalog_brotr: Brotr
    ) -> None:
        catalog_brotr.fetchval = AsyncMock(return_value=0)  # type: ignore[method-assign]
        catalog_brotr.fetch = AsyncMock(return_value=[])  # type: ignore[method-assign]

        result = await populated_catalog.query(
            catalog_brotr,
            "relay",
            limit=10,
            offset=0,
            filters={"network": "clearnet"},
        )
        assert result.total == 0

        # Verify the SQL contains a WHERE clause
        call_args = catalog_brotr.fetch.call_args
        assert "WHERE" in call_args[0][0]

    async def test_query_with_invalid_filter_column(
        self, populated_catalog: Catalog, catalog_brotr: Brotr
    ) -> None:
        with pytest.raises(CatalogError, match="Unknown column"):
            await populated_catalog.query(
                catalog_brotr,
                "relay",
                limit=10,
                offset=0,
                filters={"nonexistent": "value"},
            )

    async def test_query_with_sort(self, populated_catalog: Catalog, catalog_brotr: Brotr) -> None:
        catalog_brotr.fetchval = AsyncMock(return_value=0)  # type: ignore[method-assign]
        catalog_brotr.fetch = AsyncMock(return_value=[])  # type: ignore[method-assign]

        await populated_catalog.query(
            catalog_brotr,
            "relay",
            limit=10,
            offset=0,
            sort="discovered_at:desc",
        )

        call_args = catalog_brotr.fetch.call_args
        assert "ORDER BY discovered_at DESC" in call_args[0][0]

    async def test_query_with_invalid_sort_column(
        self, populated_catalog: Catalog, catalog_brotr: Brotr
    ) -> None:
        with pytest.raises(CatalogError, match="Unknown sort column"):
            await populated_catalog.query(
                catalog_brotr,
                "relay",
                limit=10,
                offset=0,
                sort="nonexistent:asc",
            )


# ============================================================================
# Catalog PK Lookup Tests
# ============================================================================


class TestCatalogGetByPk:
    """Tests for Catalog.get_by_pk()."""

    async def test_get_by_pk(self, populated_catalog: Catalog, catalog_brotr: Brotr) -> None:
        mock_row = MagicMock()
        mock_row.items.return_value = [("url", "wss://relay.example.com")]
        mock_row.__iter__ = lambda self: iter(self.items())
        mock_row.keys.return_value = ["url"]
        mock_row.__getitem__ = lambda self, key: dict(self.items())[key]

        catalog_brotr.fetchrow = AsyncMock(return_value=mock_row)  # type: ignore[method-assign]

        result = await populated_catalog.get_by_pk(
            catalog_brotr,
            "relay",
            {"url": "wss://relay.example.com"},
        )
        assert result is not None

    async def test_get_by_pk_not_found(
        self, populated_catalog: Catalog, catalog_brotr: Brotr
    ) -> None:
        catalog_brotr.fetchrow = AsyncMock(return_value=None)  # type: ignore[method-assign]

        result = await populated_catalog.get_by_pk(
            catalog_brotr,
            "relay",
            {"url": "wss://nonexistent"},
        )
        assert result is None

    async def test_get_by_pk_no_pk(self, populated_catalog: Catalog, catalog_brotr: Brotr) -> None:
        # Add a view with no PK
        populated_catalog._tables["relay_stats"] = TableSchema(
            name="relay_stats",
            columns=(ColumnSchema(name="url", pg_type="text", nullable=False),),
            primary_key=(),
            is_view=True,
        )
        with pytest.raises(CatalogError, match="no primary key"):
            await populated_catalog.get_by_pk(catalog_brotr, "relay_stats", {"url": "x"})

    async def test_get_by_pk_missing_column(
        self, populated_catalog: Catalog, catalog_brotr: Brotr
    ) -> None:
        with pytest.raises(CatalogError, match="Missing primary key column"):
            await populated_catalog.get_by_pk(catalog_brotr, "relay", {})

    async def test_get_by_pk_bytea(self, populated_catalog: Catalog, catalog_brotr: Brotr) -> None:
        mock_row = MagicMock()
        mock_row.items.return_value = [("id", "abcd1234")]
        mock_row.__iter__ = lambda self: iter(self.items())
        mock_row.keys.return_value = ["id"]
        mock_row.__getitem__ = lambda self, key: dict(self.items())[key]

        catalog_brotr.fetchrow = AsyncMock(return_value=mock_row)  # type: ignore[method-assign]

        result = await populated_catalog.get_by_pk(
            catalog_brotr,
            "event",
            {"id": "abcd1234"},
        )
        assert result is not None
        # Verify bytes were passed for bytea column
        call_args = catalog_brotr.fetchrow.call_args
        assert call_args[0][1] == bytes.fromhex("abcd1234")


# ============================================================================
# Filter Parsing Tests
# ============================================================================


class TestFilterParsing:
    """Tests for Catalog._parse_filter()."""

    def test_default_operator(self) -> None:
        op, val = Catalog._parse_filter("clearnet")
        assert op == "="
        assert val == "clearnet"

    def test_gt_operator(self) -> None:
        op, val = Catalog._parse_filter(">:100")
        assert op == ">"
        assert val == "100"

    def test_gte_operator(self) -> None:
        op, val = Catalog._parse_filter(">=:50")
        assert op == ">="
        assert val == "50"

    def test_lt_operator(self) -> None:
        op, val = Catalog._parse_filter("<:50")
        assert op == "<"
        assert val == "50"

    def test_lte_operator(self) -> None:
        op, val = Catalog._parse_filter("<=:25")
        assert op == "<="
        assert val == "25"

    def test_ilike_operator(self) -> None:
        op, val = Catalog._parse_filter("ILIKE:%relay%")
        assert op == "ILIKE"
        assert val == "%relay%"


class TestSortParsing:
    """Tests for Catalog._parse_sort()."""

    def test_default_asc(self) -> None:
        col, direction = Catalog._parse_sort("name")
        assert col == "name"
        assert direction == "ASC"

    def test_desc(self) -> None:
        col, direction = Catalog._parse_sort("name:desc")
        assert col == "name"
        assert direction == "DESC"

    def test_asc_explicit(self) -> None:
        col, direction = Catalog._parse_sort("name:asc")
        assert col == "name"
        assert direction == "ASC"

    def test_invalid_direction(self) -> None:
        with pytest.raises(CatalogError, match="Invalid sort direction"):
            Catalog._parse_sort("name:invalid")


class TestSelectColumns:
    """Tests for Catalog._build_select_columns()."""

    def test_text_columns(self) -> None:
        cols = (
            ColumnSchema(name="url", pg_type="text", nullable=False),
            ColumnSchema(name="network", pg_type="text", nullable=False),
        )
        result = Catalog._build_select_columns(cols)
        assert result == "url, network"

    def test_bytea_column(self) -> None:
        cols = (ColumnSchema(name="id", pg_type="bytea", nullable=False),)
        result = Catalog._build_select_columns(cols)
        assert result == "ENCODE(id, 'hex') AS id"

    def test_date_column(self) -> None:
        cols = (ColumnSchema(name="created_at", pg_type="date", nullable=True),)
        result = Catalog._build_select_columns(cols)
        assert result == "created_at::text AS created_at"

    def test_numeric_column(self) -> None:
        cols = (ColumnSchema(name="score", pg_type="numeric", nullable=True),)
        result = Catalog._build_select_columns(cols)
        assert result == "score::float AS score"

    def test_mixed_columns(self) -> None:
        cols = (
            ColumnSchema(name="id", pg_type="bytea", nullable=False),
            ColumnSchema(name="name", pg_type="text", nullable=False),
            ColumnSchema(name="score", pg_type="numeric", nullable=True),
        )
        result = Catalog._build_select_columns(cols)
        assert result == "ENCODE(id, 'hex') AS id, name, score::float AS score"


# ============================================================================
# Param Cast Tests
# ============================================================================


class TestParamCast:
    """Tests for Catalog._param_cast()."""

    def test_bytea(self) -> None:
        assert Catalog._param_cast("bytea") == "::bytea"

    def test_integer(self) -> None:
        assert Catalog._param_cast("integer") == "::integer"

    def test_bigint(self) -> None:
        assert Catalog._param_cast("bigint") == "::bigint"

    def test_smallint(self) -> None:
        assert Catalog._param_cast("smallint") == "::smallint"

    def test_boolean(self) -> None:
        assert Catalog._param_cast("boolean") == "::boolean"

    def test_date(self) -> None:
        assert Catalog._param_cast("date") == "::date"

    def test_timestamp(self) -> None:
        assert Catalog._param_cast("timestamp without time zone") == "::timestamp without time zone"

    def test_timestamptz(self) -> None:
        assert Catalog._param_cast("timestamp with time zone") == "::timestamp with time zone"

    def test_numeric(self) -> None:
        assert Catalog._param_cast("numeric") == "::numeric"

    def test_decimal(self) -> None:
        assert Catalog._param_cast("decimal") == "::numeric"

    def test_jsonb(self) -> None:
        assert Catalog._param_cast("jsonb") == "::jsonb"

    def test_text_no_cast(self) -> None:
        assert Catalog._param_cast("text") == ""

    def test_text_array_no_cast(self) -> None:
        assert Catalog._param_cast("text[]") == ""


# ============================================================================
# Bytea Filter Tests
# ============================================================================


class TestByteaFilter:
    """Tests for bytea value conversion in query filters."""

    async def test_query_filter_bytea_converts_to_bytes(
        self,
        populated_catalog: Catalog,
        catalog_brotr: Brotr,
    ) -> None:
        catalog_brotr.fetchval = AsyncMock(return_value=0)  # type: ignore[method-assign]
        catalog_brotr.fetch = AsyncMock(return_value=[])  # type: ignore[method-assign]

        await populated_catalog.query(
            catalog_brotr,
            "event",
            limit=10,
            offset=0,
            filters={"id": "abcd1234"},
        )

        # The count query should have bytes, not string
        count_args = catalog_brotr.fetchval.call_args
        assert count_args[0][1] == bytes.fromhex("abcd1234")

        # The data query should also have bytes
        data_args = catalog_brotr.fetch.call_args
        assert data_args[0][1] == bytes.fromhex("abcd1234")

    async def test_query_filter_bytea_invalid_hex(
        self,
        populated_catalog: Catalog,
        catalog_brotr: Brotr,
    ) -> None:
        with pytest.raises(CatalogError, match="Invalid hex value for column id"):
            await populated_catalog.query(
                catalog_brotr,
                "event",
                limit=10,
                offset=0,
                filters={"id": "not_valid_hex!"},
            )

    async def test_get_by_pk_bytea_invalid_hex(
        self,
        populated_catalog: Catalog,
        catalog_brotr: Brotr,
    ) -> None:
        with pytest.raises(CatalogError, match="Invalid hex value for column id"):
            await populated_catalog.get_by_pk(
                catalog_brotr,
                "event",
                {"id": "zzz_bad"},
            )


# ============================================================================
# asyncpg.DataError Conversion Tests
# ============================================================================


class TestDataErrorConversion:
    """Tests that asyncpg.DataError is converted to CatalogError."""

    async def test_query_data_error_becomes_value_error(
        self,
        populated_catalog: Catalog,
        catalog_brotr: Brotr,
    ) -> None:
        catalog_brotr.fetchval = AsyncMock(  # type: ignore[method-assign]
            side_effect=asyncpg.DataError("invalid input syntax for type bigint"),
        )

        with pytest.raises(CatalogError, match="Invalid filter value"):
            await populated_catalog.query(
                catalog_brotr,
                "relay",
                limit=10,
                offset=0,
                filters={"discovered_at": ">=:not_a_number"},
            )

    async def test_query_data_error_on_data_fetch(
        self,
        populated_catalog: Catalog,
        catalog_brotr: Brotr,
    ) -> None:
        catalog_brotr.fetchval = AsyncMock(return_value=1)  # type: ignore[method-assign]
        catalog_brotr.fetch = AsyncMock(  # type: ignore[method-assign]
            side_effect=asyncpg.DataError("invalid input syntax"),
        )

        with pytest.raises(CatalogError, match="Invalid filter value"):
            await populated_catalog.query(
                catalog_brotr,
                "relay",
                limit=10,
                offset=0,
                filters={"network": "clearnet"},
            )

    async def test_get_by_pk_data_error_becomes_value_error(
        self,
        populated_catalog: Catalog,
        catalog_brotr: Brotr,
    ) -> None:
        catalog_brotr.fetchrow = AsyncMock(  # type: ignore[method-assign]
            side_effect=asyncpg.DataError("invalid input syntax for type bytea"),
        )

        with pytest.raises(CatalogError, match="Invalid parameter value"):
            await populated_catalog.get_by_pk(
                catalog_brotr,
                "relay",
                {"url": "wss://example.com"},
            )


# ============================================================================
# Partial Index Exclusion Tests
# ============================================================================


class TestPartialIndexExclusion:
    """Tests that partial unique indexes are excluded from matview discovery."""

    async def test_discover_excludes_partial_indexes(self, catalog_brotr: Brotr) -> None:
        catalog = Catalog()

        def _attr_getter(obj: MagicMock, key: str) -> object:
            return getattr(obj, key)

        matview_rows = [MagicMock(table_name="relay_stats")]
        for row in matview_rows:
            row.__getitem__ = _attr_getter

        col_rows = [
            MagicMock(
                table_name="relay_stats", column_name="url", data_type="text", is_nullable=False
            ),
        ]
        for row in col_rows:
            row.__getitem__ = _attr_getter

        # No index rows returned (partial indexes are excluded by the query).
        # Check pg_index BEFORE pg_attribute because the index query's SQL
        # also contains "pg_attribute" in the JOIN clause.
        async def mock_fetch(query: str, *args: object, **kwargs: object) -> list[MagicMock]:
            if "information_schema.tables" in query:
                return []
            if "pg_matviews" in query:
                return matview_rows
            if "pg_index" in query:
                assert "indpred IS NULL" in query
                return []
            if "pg_attribute" in query:
                return col_rows
            return []

        catalog_brotr.fetch = AsyncMock(side_effect=mock_fetch)  # type: ignore[method-assign]
        await catalog.discover(catalog_brotr)

        # No PK discovered (only partial indexes existed)
        assert catalog.tables["relay_stats"].primary_key == ()
