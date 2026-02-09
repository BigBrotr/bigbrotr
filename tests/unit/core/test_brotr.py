"""
Unit tests for core.brotr module.

Tests:
- Configuration models (BatchConfig, BrotrTimeoutsConfig, BrotrConfig)
- Brotr initialization with defaults and custom config
- Factory methods (from_yaml, from_dict)
- Helper methods (_validate_batch_size, _transpose_to_columns, _call_procedure)
- Insert operations (insert_event, insert_event_relay, insert_relay, insert_metadata, insert_relay_metadata)
- Service state operations (upsert_service_state, get_service_state, delete_service_state)
- Cleanup operations (delete_orphan_event, delete_orphan_metadata)
- Materialized view refresh operations (refresh_materialized_view)
- Explicit lifecycle methods (connect, close)
- Context manager support
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from bigbrotr.core.brotr import (
    BatchConfig,
    Brotr,
    BrotrConfig,
    BrotrTimeoutsConfig,
)
from bigbrotr.core.pool import Pool
from bigbrotr.services.common.constants import ServiceState, ServiceStateKey


# ============================================================================
# Configuration Models Tests
# ============================================================================


class TestBatchConfig:
    """Tests for BatchConfig Pydantic model."""

    def test_defaults(self) -> None:
        """Test default configuration values."""
        config = BatchConfig()
        assert config.max_size == 1000

    def test_custom_value(self) -> None:
        """Test custom batch size configuration."""
        config = BatchConfig(max_size=5000)
        assert config.max_size == 5000

    def test_minimum_validation(self) -> None:
        """Test minimum value validation (>= 1)."""
        config = BatchConfig(max_size=1)
        assert config.max_size == 1

        with pytest.raises(ValidationError):
            BatchConfig(max_size=0)

    def test_maximum_validation(self) -> None:
        """Test maximum value validation (<= 100000)."""
        config = BatchConfig(max_size=100000)
        assert config.max_size == 100000

        with pytest.raises(ValidationError):
            BatchConfig(max_size=100001)


class TestBrotrTimeoutsConfig:
    """Tests for BrotrTimeoutsConfig Pydantic model."""

    def test_defaults(self) -> None:
        """Test default configuration values."""
        config = BrotrTimeoutsConfig()

        assert config.query == 60.0
        assert config.batch == 120.0
        assert config.cleanup == 90.0
        assert config.refresh is None

    def test_custom_values(self) -> None:
        """Test custom timeout configuration."""
        config = BrotrTimeoutsConfig(
            query=30.0,
            batch=60.0,
            cleanup=45.0,
            refresh=300.0,
        )

        assert config.query == 30.0
        assert config.batch == 60.0
        assert config.cleanup == 45.0
        assert config.refresh == 300.0

    def test_none_for_infinite_timeout(self) -> None:
        """Test that None represents infinite timeout."""
        config = BrotrTimeoutsConfig(
            query=None,
            batch=None,
            cleanup=None,
            refresh=None,
        )

        assert config.query is None
        assert config.batch is None
        assert config.cleanup is None
        assert config.refresh is None

    def test_minimum_validation(self) -> None:
        """Test minimum value validation (>= 0.1 or None)."""
        # Valid at minimum
        config = BrotrTimeoutsConfig(query=0.1)
        assert config.query == 0.1

        # Invalid: below minimum
        with pytest.raises(ValidationError):
            BrotrTimeoutsConfig(query=0.05)


class TestBrotrConfig:
    """Tests for BrotrConfig composite model."""

    def test_defaults(self) -> None:
        """Test default nested configuration."""
        config = BrotrConfig()

        assert config.batch.max_size == 1000
        assert config.timeouts.query == 60.0
        assert config.timeouts.batch == 120.0

    def test_nested_custom_values(self) -> None:
        """Test configuration with nested custom values."""
        config = BrotrConfig(
            batch=BatchConfig(max_size=5000),
            timeouts=BrotrTimeoutsConfig(query=30.0, batch=60.0),
        )

        assert config.batch.max_size == 5000
        assert config.timeouts.query == 30.0
        assert config.timeouts.batch == 60.0


# ============================================================================
# Brotr Initialization Tests
# ============================================================================


class TestBrotrInit:
    """Tests for Brotr initialization."""

    def test_default_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test Brotr with default configuration."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        brotr = Brotr()

        assert brotr._pool is not None
        assert brotr.config.batch.max_size == 1000
        assert brotr.config.timeouts.query == 60.0

    def test_with_injected_pool(self, mock_pool: Pool) -> None:
        """Test Brotr with injected pool."""
        brotr = Brotr(pool=mock_pool)

        assert brotr._pool is mock_pool

    def test_with_custom_config(self, mock_pool: Pool) -> None:
        """Test Brotr with custom configuration."""
        config = BrotrConfig(
            batch=BatchConfig(max_size=5000),
            timeouts=BrotrTimeoutsConfig(query=30.0),
        )
        brotr = Brotr(pool=mock_pool, config=config)

        assert brotr.config.batch.max_size == 5000
        assert brotr.config.timeouts.query == 30.0

    def test_config_property(self, mock_brotr: Brotr) -> None:
        """Test config property returns configuration."""
        config = mock_brotr.config

        assert isinstance(config, BrotrConfig)


class TestBrotrFactoryMethods:
    """Tests for Brotr factory methods."""

    def test_from_dict(
        self, brotr_config_dict: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test Brotr.from_dict() factory method."""
        monkeypatch.setenv("DB_PASSWORD", "dict_pass")
        brotr = Brotr.from_dict(brotr_config_dict)

        assert brotr.config.batch.max_size == 500

    def test_from_dict_without_pool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test from_dict creates default pool when not provided."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        config_dict = {"batch": {"max_size": 2000}}

        brotr = Brotr.from_dict(config_dict)

        assert brotr._pool is not None
        assert brotr.config.batch.max_size == 2000

    def test_from_yaml(
        self, brotr_config_dict: dict[str, Any], tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test Brotr.from_yaml() factory method."""
        import yaml

        monkeypatch.setenv("DB_PASSWORD", "yaml_pass")
        config_file = tmp_path / "brotr_config.yaml"
        config_file.write_text(yaml.dump(brotr_config_dict))

        brotr = Brotr.from_yaml(str(config_file))

        assert brotr.config.batch.max_size == 500

    def test_from_yaml_file_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test from_yaml raises FileNotFoundError for missing file."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")

        with pytest.raises(FileNotFoundError):
            Brotr.from_yaml("/nonexistent/path/config.yaml")


class TestBrotrRepr:
    """Tests for Brotr string representation."""

    def test_repr(self, mock_brotr: Brotr) -> None:
        """Test repr contains expected information."""
        repr_str = repr(mock_brotr)

        assert "Brotr" in repr_str
        assert "test_db" in repr_str


# ============================================================================
# Helper Methods Tests
# ============================================================================


class TestValidateBatchSize:
    """Tests for Brotr._validate_batch_size() method."""

    def test_valid_batch_size(self, mock_brotr: Brotr) -> None:
        """Test validation passes for valid batch size."""
        batch = [{"id": i} for i in range(100)]
        mock_brotr._validate_batch_size(batch, "test_operation")
        # Should not raise

    def test_exceeds_maximum_raises(self, mock_brotr: Brotr) -> None:
        """Test validation raises ValueError when batch exceeds maximum."""
        batch = [{"id": i} for i in range(15000)]

        with pytest.raises(ValueError, match="exceeds maximum"):
            mock_brotr._validate_batch_size(batch, "test_operation")

    def test_at_maximum_is_valid(self, mock_brotr: Brotr) -> None:
        """Test validation passes when batch equals maximum."""
        # Default max is 1000
        batch = [{"id": i} for i in range(1000)]
        mock_brotr._validate_batch_size(batch, "test_operation")
        # Should not raise

    def test_empty_batch_is_valid(self, mock_brotr: Brotr) -> None:
        """Test validation passes for empty batch."""
        mock_brotr._validate_batch_size([], "test_operation")
        # Should not raise


class TestTransposeToColumns:
    """Tests for Brotr._transpose_to_columns() method."""

    def test_empty_list(self, mock_brotr: Brotr) -> None:
        """Test transposing empty list returns empty tuple."""
        result = mock_brotr._transpose_to_columns([])
        assert result == ()

    def test_single_row(self, mock_brotr: Brotr) -> None:
        """Test transposing single row."""
        result = mock_brotr._transpose_to_columns([("a", 1, True)])
        assert result == (["a"], [1], [True])

    def test_multiple_rows(self, mock_brotr: Brotr) -> None:
        """Test transposing multiple rows."""
        params = [("a", 1), ("b", 2), ("c", 3)]
        result = mock_brotr._transpose_to_columns(params)
        assert result == (["a", "b", "c"], [1, 2, 3])

    def test_single_column(self, mock_brotr: Brotr) -> None:
        """Test transposing single column."""
        params = [(1,), (2,), (3,)]
        result = mock_brotr._transpose_to_columns(params)
        assert result == ([1, 2, 3],)

    def test_inconsistent_lengths_raises(self, mock_brotr: Brotr) -> None:
        """Test that inconsistent row lengths raise ValueError."""
        params = [("a", 1, True), ("b", 2)]  # Second row has 2 columns instead of 3

        with pytest.raises(ValueError, match="Row 1 has 2 columns, expected 3"):
            mock_brotr._transpose_to_columns(params)

    def test_different_types(self, mock_brotr: Brotr) -> None:
        """Test transposing rows with different value types."""
        params = [
            ("str", 123, True, None, 3.14),
            ("other", 456, False, "value", 2.71),
        ]
        result = mock_brotr._transpose_to_columns(params)

        assert result == (
            ["str", "other"],
            [123, 456],
            [True, False],
            [None, "value"],
            [3.14, 2.71],
        )


class TestCallProcedure:
    """Tests for Brotr._call_procedure() method."""

    @pytest.mark.asyncio
    async def test_valid_procedure_names(self, mock_brotr: Brotr) -> None:
        """Test that valid SQL identifiers are accepted."""
        valid_names = [
            "my_procedure",
            "procedure123",
            "_private_proc",
            "CamelCaseProc",
            "a",
            "_",
            "delete_123_test",
        ]

        for name in valid_names:
            try:
                await mock_brotr._call_procedure(name, fetch_result=True)
            except ValueError as e:
                if "Invalid procedure name" in str(e):
                    pytest.fail(f"Valid name '{name}' was rejected")

    @pytest.mark.asyncio
    async def test_invalid_procedure_names(self, mock_brotr: Brotr) -> None:
        """Test that invalid SQL identifiers are rejected."""
        invalid_names = [
            "my_proc; DROP TABLE users",  # SQL injection attempt
            "my_proc()",  # Contains parentheses
            "my-proc",  # Contains hyphen
            "123proc",  # Starts with number
            "my proc",  # Contains space
            "my_proc--comment",  # SQL comment
            "",  # Empty string
            "proc\nname",  # Newline
            "proc'name",  # Single quote
            'proc"name',  # Double quote
        ]

        for name in invalid_names:
            with pytest.raises(ValueError, match="Invalid procedure name"):
                await mock_brotr._call_procedure(name)

    @pytest.mark.asyncio
    async def test_fetch_result_true(self, mock_brotr: Brotr) -> None:
        """Test procedure call with fetch_result=True."""
        result = await mock_brotr._call_procedure("test_proc", fetch_result=True)
        assert result == 1  # Mock returns 1 by default

    @pytest.mark.asyncio
    async def test_fetch_result_false(self, mock_brotr: Brotr) -> None:
        """Test procedure call with fetch_result=False."""
        result = await mock_brotr._call_procedure("test_proc", fetch_result=False)
        assert result is None

    @pytest.mark.asyncio
    async def test_with_arguments(self, mock_brotr: Brotr) -> None:
        """Test procedure call with arguments."""
        await mock_brotr._call_procedure("test_proc", "arg1", 123, True, fetch_result=True)

    @pytest.mark.asyncio
    async def test_with_timeout(self, mock_brotr: Brotr) -> None:
        """Test procedure call with custom timeout."""
        await mock_brotr._call_procedure("test_proc", fetch_result=True, timeout=30.0)


# ============================================================================
# Insert Operations Tests
# ============================================================================


class TestInsertRelay:
    """Tests for Brotr.insert_relay() method."""

    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self, mock_brotr: Brotr) -> None:
        """Test that empty list returns 0."""
        inserted = await mock_brotr.insert_relay([])
        assert inserted == 0

    @pytest.mark.asyncio
    async def test_single_relay(self, mock_brotr: Brotr, sample_relay: Any) -> None:
        """Test inserting single relay."""
        inserted = await mock_brotr.insert_relay([sample_relay])
        assert inserted == 1

    @pytest.mark.asyncio
    async def test_multiple_relays(
        self, mock_brotr: Brotr, mock_pool: Pool, sample_relays_batch: list[Any]
    ) -> None:
        """Test inserting multiple relays."""
        mock_pool._mock_connection.fetchval = AsyncMock(  # type: ignore[attr-defined]
            return_value=len(sample_relays_batch)
        )
        inserted = await mock_brotr.insert_relay(sample_relays_batch)
        assert inserted == len(sample_relays_batch)


class TestInsertEvent:
    """Tests for Brotr.insert_event() method."""

    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self, mock_brotr: Brotr) -> None:
        """Test that empty list returns 0."""
        inserted = await mock_brotr.insert_event([])
        assert inserted == 0

    @pytest.mark.asyncio
    async def test_single_event(self, mock_brotr: Brotr, sample_event: Any) -> None:
        """Test inserting single event."""
        inserted = await mock_brotr.insert_event([sample_event.event])
        assert inserted == 1


class TestInsertEventRelay:
    """Tests for Brotr.insert_event_relay() method."""

    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self, mock_brotr: Brotr) -> None:
        """Test that empty list returns 0."""
        inserted = await mock_brotr.insert_event_relay([])
        assert inserted == 0

    @pytest.mark.asyncio
    async def test_single_event_relay(self, mock_brotr: Brotr, sample_event: Any) -> None:
        """Test inserting single event-relay junction."""
        inserted = await mock_brotr.insert_event_relay([sample_event])
        assert inserted == 1

    @pytest.mark.asyncio
    async def test_multiple_event_relays(
        self, mock_brotr: Brotr, mock_pool: Pool, sample_events_batch: list[Any]
    ) -> None:
        """Test inserting multiple event-relay junctions."""
        mock_pool._mock_connection.fetchval = AsyncMock(  # type: ignore[attr-defined]
            return_value=len(sample_events_batch)
        )
        inserted = await mock_brotr.insert_event_relay(sample_events_batch)
        assert inserted == len(sample_events_batch)

    @pytest.mark.asyncio
    async def test_cascade_true_default(
        self, mock_brotr: Brotr, mock_pool: Pool, sample_event: Any
    ) -> None:
        """Test that cascade=True is the default."""
        await mock_brotr.insert_event_relay([sample_event], cascade=True)
        # Verify cascade query was used (11 parameters)
        mock_conn = mock_pool._mock_connection  # type: ignore[attr-defined]
        call_args = mock_conn.fetchval.call_args
        assert "cascade" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_cascade_false(
        self, mock_brotr: Brotr, mock_pool: Pool, sample_event: Any
    ) -> None:
        """Test inserting with cascade=False."""
        await mock_brotr.insert_event_relay([sample_event], cascade=False)
        # Verify non-cascade query was used (3 parameters)
        mock_conn = mock_pool._mock_connection  # type: ignore[attr-defined]
        call_args = mock_conn.fetchval.call_args
        assert "event_relay_insert" in call_args[0][0]
        assert "cascade" not in call_args[0][0].lower()


class TestInsertMetadata:
    """Tests for Brotr.insert_metadata() method."""

    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self, mock_brotr: Brotr) -> None:
        """Test that empty list returns 0."""
        inserted = await mock_brotr.insert_metadata([])
        assert inserted == 0


class TestInsertRelayMetadata:
    """Tests for Brotr.insert_relay_metadata() method."""

    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self, mock_brotr: Brotr) -> None:
        """Test that empty list returns 0."""
        inserted = await mock_brotr.insert_relay_metadata([])
        assert inserted == 0

    @pytest.mark.asyncio
    async def test_single_metadata(self, mock_brotr: Brotr, sample_metadata: Any) -> None:
        """Test inserting single relay metadata."""
        inserted = await mock_brotr.insert_relay_metadata([sample_metadata])
        assert inserted == 1

    @pytest.mark.asyncio
    async def test_cascade_true_default(
        self, mock_brotr: Brotr, mock_pool: Pool, sample_metadata: Any
    ) -> None:
        """Test that cascade=True is the default."""
        await mock_brotr.insert_relay_metadata([sample_metadata], cascade=True)
        mock_conn = mock_pool._mock_connection  # type: ignore[attr-defined]
        call_args = mock_conn.fetchval.call_args
        assert "cascade" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_cascade_false(
        self, mock_brotr: Brotr, mock_pool: Pool, sample_metadata: Any
    ) -> None:
        """Test inserting with cascade=False."""
        await mock_brotr.insert_relay_metadata([sample_metadata], cascade=False)
        mock_conn = mock_pool._mock_connection  # type: ignore[attr-defined]
        call_args = mock_conn.fetchval.call_args
        assert "relay_metadata_insert" in call_args[0][0]
        assert "cascade" not in call_args[0][0].lower()


# ============================================================================
# Service State Operations Tests
# ============================================================================


class TestUpsertServiceState:
    """Tests for Brotr.upsert_service_state() method."""

    @pytest.mark.asyncio
    async def test_empty_records_returns_zero(self, mock_brotr: Brotr) -> None:
        """Test that empty records list returns 0."""
        result = await mock_brotr.upsert_service_state([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_single_record(self, mock_brotr: Brotr, mock_pool: Pool) -> None:
        """Test upserting single record."""
        records = [
            ServiceState(
                service_name="finder",
                state_type="cursor",
                state_key="key1",
                payload={"count": 1},
                updated_at=1700000000,
            )
        ]
        result = await mock_brotr.upsert_service_state(records)
        assert result == 1

    @pytest.mark.asyncio
    async def test_multiple_records(self, mock_brotr: Brotr, mock_pool: Pool) -> None:
        """Test upserting multiple records."""
        records = [
            ServiceState(
                service_name="finder",
                state_type="cursor",
                state_key="key1",
                payload={"count": 1},
                updated_at=1700000000,
            ),
            ServiceState(
                service_name="finder",
                state_type="cursor",
                state_key="key2",
                payload={"count": 2},
                updated_at=1700000000,
            ),
            ServiceState(
                service_name="monitor",
                state_type="state",
                state_key="key3",
                payload={"status": "ok"},
                updated_at=1700000000,
            ),
        ]
        result = await mock_brotr.upsert_service_state(records)
        assert result == 3

    @pytest.mark.asyncio
    async def test_dict_values_passed_directly(self, mock_brotr: Brotr, mock_pool: Pool) -> None:
        """Test that dict values are passed directly (JSON codec handles encoding)."""
        records = [
            ServiceState(
                service_name="finder",
                state_type="cursor",
                state_key="key1",
                payload={"nested": {"level": 1}},
                updated_at=1700000000,
            )
        ]
        await mock_brotr.upsert_service_state(records)

        mock_conn = mock_pool._mock_connection  # type: ignore[attr-defined]
        call_args = mock_conn.execute.call_args
        values_list = call_args[0][4]
        assert values_list[0] == {"nested": {"level": 1}}

    @pytest.mark.asyncio
    async def test_list_values_passed_directly(self, mock_brotr: Brotr, mock_pool: Pool) -> None:
        """Test that list values are passed directly (JSON codec handles encoding)."""
        records = [
            ServiceState(
                service_name="finder",
                state_type="cursor",
                state_key="key1",
                payload=["item1", "item2", "item3"],  # type: ignore[arg-type]
                updated_at=1700000000,
            )
        ]
        await mock_brotr.upsert_service_state(records)

        mock_conn = mock_pool._mock_connection  # type: ignore[attr-defined]
        call_args = mock_conn.execute.call_args
        values_list = call_args[0][4]
        assert values_list[0] == ["item1", "item2", "item3"]

    @pytest.mark.asyncio
    async def test_complex_nested_values(self, mock_brotr: Brotr, mock_pool: Pool) -> None:
        """Test complex nested objects are passed correctly."""
        complex_value = {
            "nested": {"level2": {"level3": ["a", "b", "c"]}},
            "list_of_dicts": [{"key1": "value1"}, {"key2": "value2"}],
            "mixed": [1, "string", True, None],
        }
        records = [
            ServiceState(
                service_name="monitor",
                state_type="state",
                state_key="complex_key",
                payload=complex_value,
                updated_at=1700000000,
            )
        ]

        await mock_brotr.upsert_service_state(records)

        mock_conn = mock_pool._mock_connection  # type: ignore[attr-defined]
        call_args = mock_conn.execute.call_args
        values_list = call_args[0][4]
        assert values_list[0] == complex_value


class TestGetServiceState:
    """Tests for Brotr.get_service_state() method."""

    @pytest.mark.asyncio
    async def test_returns_list(self, mock_brotr: Brotr) -> None:
        """Test that get returns a list."""
        result = await mock_brotr.get_service_state("finder", "cursor")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_with_specific_key(self, mock_brotr: Brotr) -> None:
        """Test getting specific key."""
        await mock_brotr.get_service_state("finder", "cursor", key="specific_key")

    @pytest.mark.asyncio
    async def test_without_key(self, mock_brotr: Brotr) -> None:
        """Test getting all records without specific key."""
        await mock_brotr.get_service_state("finder", "cursor", key=None)


class TestDeleteServiceState:
    """Tests for Brotr.delete_service_state() method."""

    @pytest.mark.asyncio
    async def test_empty_keys_returns_zero(self, mock_brotr: Brotr) -> None:
        """Test that empty keys list returns 0."""
        result = await mock_brotr.delete_service_state([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_single_key(self, mock_brotr: Brotr) -> None:
        """Test deleting single key."""
        keys = [ServiceStateKey(service_name="finder", state_type="cursor", state_key="key1")]
        result = await mock_brotr.delete_service_state(keys)
        assert result == 1

    @pytest.mark.asyncio
    async def test_multiple_keys(self, mock_brotr: Brotr, mock_pool: Pool) -> None:
        """Test deleting multiple keys."""
        mock_pool._mock_connection.fetchval = AsyncMock(return_value=3)  # type: ignore[attr-defined]
        keys = [
            ServiceStateKey(service_name="finder", state_type="cursor", state_key="key1"),
            ServiceStateKey(service_name="finder", state_type="cursor", state_key="key2"),
            ServiceStateKey(service_name="monitor", state_type="state", state_key="key3"),
        ]
        result = await mock_brotr.delete_service_state(keys)
        assert result == 3


# ============================================================================
# Cleanup Operations Tests
# ============================================================================


class TestDeleteOrphanEvent:
    """Tests for Brotr.delete_orphan_event() method."""

    @pytest.mark.asyncio
    async def test_returns_deleted_count(self, mock_brotr: Brotr) -> None:
        """Test that method returns count of deleted events."""
        result = await mock_brotr.delete_orphan_event()
        assert result == 1  # Mock returns 1 by default


class TestDeleteOrphanMetadata:
    """Tests for Brotr.delete_orphan_metadata() method."""

    @pytest.mark.asyncio
    async def test_returns_deleted_count(self, mock_brotr: Brotr) -> None:
        """Test that method returns count of deleted metadata."""
        result = await mock_brotr.delete_orphan_metadata()
        assert result == 1  # Mock returns 1 by default


# ============================================================================
# Query Operations Tests
# ============================================================================


class TestBrotrQueryOperations:
    """Tests for Brotr query facade methods (fetch, fetchrow, fetchval, execute)."""

    @pytest.mark.asyncio
    async def test_fetch_delegates_to_pool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that fetch() delegates to pool.fetch() with default timeout."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        brotr = Brotr()

        with patch.object(brotr._pool, "fetch", new_callable=AsyncMock, return_value=[]) as mock:
            result = await brotr.fetch("SELECT 1")
            mock.assert_called_once_with("SELECT 1", timeout=brotr._config.timeouts.query)
            assert result == []

    @pytest.mark.asyncio
    async def test_fetch_passes_args_and_custom_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that fetch() passes query args and custom timeout."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        brotr = Brotr()

        with patch.object(brotr._pool, "fetch", new_callable=AsyncMock, return_value=[]) as mock:
            await brotr.fetch("SELECT $1", "arg1", timeout=5.0)
            mock.assert_called_once_with("SELECT $1", "arg1", timeout=5.0)

    @pytest.mark.asyncio
    async def test_fetchrow_delegates_to_pool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that fetchrow() delegates to pool.fetchrow() with default timeout."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        brotr = Brotr()

        with patch.object(
            brotr._pool, "fetchrow", new_callable=AsyncMock, return_value=None
        ) as mock:
            result = await brotr.fetchrow("SELECT 1")
            mock.assert_called_once_with("SELECT 1", timeout=brotr._config.timeouts.query)
            assert result is None

    @pytest.mark.asyncio
    async def test_fetchval_delegates_to_pool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that fetchval() delegates to pool.fetchval() with default timeout."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        brotr = Brotr()

        with patch.object(brotr._pool, "fetchval", new_callable=AsyncMock, return_value=42) as mock:
            result = await brotr.fetchval("SELECT count(*)")
            mock.assert_called_once_with("SELECT count(*)", timeout=brotr._config.timeouts.query)
            assert result == 42

    @pytest.mark.asyncio
    async def test_execute_delegates_to_pool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that execute() delegates to pool.execute() with default timeout."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        brotr = Brotr()

        with patch.object(
            brotr._pool, "execute", new_callable=AsyncMock, return_value="DELETE 5"
        ) as mock:
            result = await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://x")
            mock.assert_called_once_with(
                "DELETE FROM relay WHERE url = $1",
                "wss://x",
                timeout=brotr._config.timeouts.query,
            )
            assert result == "DELETE 5"

    @pytest.mark.asyncio
    async def test_execute_with_custom_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that execute() passes custom timeout to pool."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        brotr = Brotr()

        with patch.object(
            brotr._pool, "execute", new_callable=AsyncMock, return_value="INSERT 0 1"
        ) as mock:
            await brotr.execute("INSERT INTO relay VALUES ($1)", "wss://x", timeout=10.0)
            mock.assert_called_once_with(
                "INSERT INTO relay VALUES ($1)",
                "wss://x",
                timeout=10.0,
            )


# ============================================================================
# Refresh Operations Tests
# ============================================================================


class TestRefreshMatview:
    """Tests for Brotr.refresh_materialized_view() method."""

    @pytest.mark.asyncio
    async def test_valid_view_names(self, mock_brotr: Brotr) -> None:
        """Test refreshing valid materialized view names."""
        valid_names = [
            "relay_metadata_latest",
            "events_statistics",
            "relays_statistics",
        ]

        for name in valid_names:
            await mock_brotr.refresh_materialized_view(name)

    @pytest.mark.asyncio
    async def test_sql_injection_prevented(self, mock_brotr: Brotr) -> None:
        """Test that SQL injection attempts are prevented by procedure name regex."""
        with pytest.raises(ValueError, match="Invalid procedure name"):
            await mock_brotr.refresh_materialized_view("events_statistics; DROP TABLE events;")


# ============================================================================
# Lifecycle Tests
# ============================================================================


class TestBrotrLifecycle:
    """Tests for Brotr explicit connect/close lifecycle methods."""

    @pytest.mark.asyncio
    async def test_connect_delegates_to_pool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that connect() delegates to pool.connect()."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        brotr = Brotr()

        with patch.object(brotr._pool, "connect", new_callable=AsyncMock) as mock_connect:
            await brotr.connect()
            mock_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_delegates_to_pool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that close() delegates to pool.close()."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        brotr = Brotr()

        with patch.object(brotr._pool, "close", new_callable=AsyncMock) as mock_close:
            await brotr.close()
            mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_delegates_to_connect_close(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that async context manager delegates to connect/close."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        brotr = Brotr()

        with (
            patch.object(brotr, "connect", new_callable=AsyncMock) as mock_connect,
            patch.object(brotr, "close", new_callable=AsyncMock) as mock_close,
        ):
            async with brotr:
                mock_connect.assert_called_once()
            mock_close.assert_called_once()


# ============================================================================
# Context Manager Tests
# ============================================================================


class TestBrotrContextManager:
    """Tests for Brotr async context manager."""

    @pytest.mark.asyncio
    async def test_connects_pool_on_enter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that context manager connects pool on entry."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        brotr = Brotr()

        with (
            patch.object(brotr._pool, "connect", new_callable=AsyncMock) as mock_connect,
            patch.object(brotr._pool, "close", new_callable=AsyncMock),
        ):
            async with brotr:
                mock_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_closes_pool_on_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that context manager closes pool on exit."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        brotr = Brotr()

        with (
            patch.object(brotr._pool, "connect", new_callable=AsyncMock),
            patch.object(brotr._pool, "close", new_callable=AsyncMock) as mock_close,
        ):
            async with brotr:
                pass
            mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_closes_pool_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that context manager closes pool even on exception."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        brotr = Brotr()

        with (
            patch.object(brotr._pool, "connect", new_callable=AsyncMock),
            patch.object(brotr._pool, "close", new_callable=AsyncMock) as mock_close,
        ):
            with pytest.raises(RuntimeError):
                async with brotr:
                    raise RuntimeError("Test error")

            mock_close.assert_called_once()
