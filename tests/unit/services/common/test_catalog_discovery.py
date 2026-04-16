"""Unit tests for services.common.catalog_discovery module."""

from unittest.mock import AsyncMock, MagicMock

from bigbrotr.core.brotr import Brotr
from bigbrotr.services.common.catalog import ColumnSchema
from bigbrotr.services.common.catalog_discovery import (
    discover_columns,
    discover_matview_unique_indexes,
    discover_table_and_view_names,
)


def _row(**values: object) -> MagicMock:
    row = MagicMock(**values)
    row.__getitem__ = lambda _self, key: values[key]
    return row


class TestCatalogDiscovery:
    async def test_discover_table_and_view_names_splits_kinds(self, mock_brotr: Brotr) -> None:
        mock_brotr.fetch = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                _row(table_name="relay", table_type="BASE TABLE"),
                _row(table_name="event", table_type="BASE TABLE"),
                _row(table_name="relay_stats", table_type="VIEW"),
            ]
        )

        base_tables, views = await discover_table_and_view_names(mock_brotr)

        assert base_tables == {"relay", "event"}
        assert views == {"relay_stats"}

    async def test_discover_columns_builds_schema_objects(self, mock_brotr: Brotr) -> None:
        mock_brotr.fetch = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                _row(
                    table_name="relay",
                    column_name="url",
                    data_type="text",
                    is_nullable=False,
                ),
                _row(
                    table_name="relay",
                    column_name="discovered_at",
                    data_type="bigint",
                    is_nullable=False,
                ),
            ]
        )

        columns = await discover_columns(mock_brotr, {"relay"})

        assert columns == {
            "relay": [
                ColumnSchema(name="url", pg_type="text", nullable=False),
                ColumnSchema(name="discovered_at", pg_type="bigint", nullable=False),
            ]
        }

    async def test_discover_matview_unique_indexes_uses_first_index_only(
        self,
        mock_brotr: Brotr,
    ) -> None:
        mock_brotr.fetch = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                _row(table_name="relay_stats", index_oid=100, column_name="url", pos=1),
                _row(table_name="relay_stats", index_oid=200, column_name="url", pos=1),
                _row(table_name="relay_stats", index_oid=200, column_name="kind", pos=2),
            ]
        )

        indexes = await discover_matview_unique_indexes(mock_brotr, {"relay_stats"})

        assert indexes == {"relay_stats": ["url"]}
