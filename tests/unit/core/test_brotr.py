"""
Unit tests for core.brotr module.

Tests:
- Configuration models (BatchConfig, TimeoutsConfig, BrotrConfig)
- Brotr initialization with defaults and custom config
- Factory methods (from_yaml, from_dict)
- Insert operations (insert_events, insert_events_relays, insert_relays, insert_relay_metadata)
- Service data operations (upsert, get, delete)
- Cleanup operations (delete_orphan_events, delete_orphan_metadata)
- Query operations (get_relays_needing_check)
- Materialized view refresh operations
- Context manager support
"""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from core.brotr import (
    BatchConfig,
    Brotr,
    BrotrConfig,
    TimeoutsConfig,
)


class TestBatchConfig:
    """BatchConfig Pydantic model."""

    def test_defaults(self):
        config = BatchConfig()
        assert config.max_batch_size == 10000

    def test_validation_min(self):
        with pytest.raises(ValidationError):
            BatchConfig(max_batch_size=0)

    def test_validation_max(self):
        with pytest.raises(ValidationError):
            BatchConfig(max_batch_size=200000)


class TestTimeoutsConfig:
    """TimeoutsConfig Pydantic model."""

    def test_defaults(self):
        config = TimeoutsConfig()
        assert config.query == 60.0
        assert config.cleanup == 90.0
        assert config.batch == 120.0
        assert config.refresh is None


class TestBrotrInit:
    """Brotr initialization."""

    def test_defaults(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        brotr = Brotr()
        assert brotr.pool is not None
        assert brotr.config.batch.max_batch_size == 10000

    def test_with_injected_pool(self, mock_pool):
        config = BrotrConfig(batch=BatchConfig(max_batch_size=5000))
        brotr = Brotr(pool=mock_pool, config=config)
        assert brotr.pool is mock_pool
        assert brotr.config.batch.max_batch_size == 5000

    def test_from_dict(self, brotr_config_dict, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "dict_pass")
        brotr = Brotr.from_dict(brotr_config_dict)
        assert brotr.config.batch.max_batch_size == 500

    def test_from_yaml(self, brotr_config_dict, tmp_path, monkeypatch):
        import yaml

        monkeypatch.setenv("DB_PASSWORD", "yaml_pass")
        config_file = tmp_path / "brotr_config.yaml"
        config_file.write_text(yaml.dump(brotr_config_dict))
        brotr = Brotr.from_yaml(str(config_file))
        assert brotr.config.batch.max_batch_size == 500

    def test_repr(self, mock_brotr):
        assert "Brotr" in repr(mock_brotr)


class TestBrotrBatchValidation:
    """Brotr batch validation."""

    def test_valid_size(self, mock_brotr):
        mock_brotr._validate_batch_size([{"id": i} for i in range(100)], "test")

    def test_exceeds_max(self, mock_brotr):
        with pytest.raises(ValueError, match="exceeds maximum"):
            mock_brotr._validate_batch_size([{"id": i} for i in range(15000)], "test")


class TestBrotrTransposeToColumns:
    """Brotr._transpose_to_columns() method."""

    def test_empty_list(self, mock_brotr):
        result = mock_brotr._transpose_to_columns([])
        assert result == ()

    def test_single_row(self, mock_brotr):
        result = mock_brotr._transpose_to_columns([("a", 1, True)])
        assert result == (["a"], [1], [True])

    def test_multiple_rows(self, mock_brotr):
        params = [("a", 1), ("b", 2), ("c", 3)]
        result = mock_brotr._transpose_to_columns(params)
        assert result == (["a", "b", "c"], [1, 2, 3])

    def test_inconsistent_lengths_raises(self, mock_brotr):
        params = [("a", 1, True), ("b", 2)]  # Second row has 2 columns instead of 3
        with pytest.raises(ValueError, match="Row 1 has 2 columns, expected 3"):
            mock_brotr._transpose_to_columns(params)


class TestBrotrInsertEventsRelays:
    """Brotr.insert_events_relays() method."""

    @pytest.mark.asyncio
    async def test_empty_list(self, mock_brotr):
        inserted, skipped = await mock_brotr.insert_events_relays([])
        assert inserted == 0
        assert skipped == 0

    @pytest.mark.asyncio
    async def test_single(self, mock_brotr, sample_event):
        inserted, skipped = await mock_brotr.insert_events_relays([sample_event])
        assert inserted == 1

    @pytest.mark.asyncio
    async def test_multiple(self, mock_brotr, mock_pool, sample_events_batch):
        # Configure mock to return the batch size (simulating all records inserted)
        mock_pool._mock_connection.fetchval = AsyncMock(return_value=len(sample_events_batch))
        inserted, skipped = await mock_brotr.insert_events_relays(sample_events_batch)
        assert inserted == len(sample_events_batch)


class TestBrotrInsertRelays:
    """Brotr.insert_relays() method."""

    @pytest.mark.asyncio
    async def test_empty_list(self, mock_brotr):
        result = await mock_brotr.insert_relays([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_single(self, mock_brotr, sample_relay):
        result = await mock_brotr.insert_relays([sample_relay])
        assert result == 1


class TestBrotrInsertMetadata:
    """Brotr.insert_relay_metadata() method."""

    @pytest.mark.asyncio
    async def test_empty_list(self, mock_brotr):
        result = await mock_brotr.insert_relay_metadata([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_single(self, mock_brotr, sample_metadata):
        result = await mock_brotr.insert_relay_metadata([sample_metadata])
        assert result == 1


class TestCallProcedureValidation:
    """Brotr._call_procedure() name validation."""

    @pytest.mark.asyncio
    async def test_valid_procedure_names(self, mock_brotr):
        """Valid SQL identifiers should be accepted."""
        valid_names = [
            "my_procedure",
            "procedure123",
            "_private_proc",
            "CamelCaseProc",
            "a",
            "_",
        ]
        for name in valid_names:
            # Should not raise - will fail on execution but pass validation
            try:
                await mock_brotr._call_procedure(name, fetch_result=True)
            except ValueError as e:
                if "Invalid procedure name" in str(e):
                    pytest.fail(f"Valid name '{name}' was rejected")

    @pytest.mark.asyncio
    async def test_invalid_procedure_names(self, mock_brotr):
        """Invalid SQL identifiers should be rejected."""
        invalid_names = [
            "my_proc; DROP TABLE users",  # SQL injection attempt
            "my_proc()",  # Contains parentheses
            "my-proc",  # Contains hyphen
            "123proc",  # Starts with number
            "my proc",  # Contains space
            "my_proc--comment",  # SQL comment
            "",  # Empty string
            "proc\nname",  # Newline
        ]
        for name in invalid_names:
            with pytest.raises(ValueError, match="Invalid procedure name"):
                await mock_brotr._call_procedure(name)


class TestBrotrCleanup:
    """Brotr cleanup operations."""

    @pytest.mark.asyncio
    async def test_delete_orphan_events(self, mock_brotr):
        result = await mock_brotr.delete_orphan_events()
        assert result == 1

    @pytest.mark.asyncio
    async def test_delete_orphan_metadata(self, mock_brotr):
        result = await mock_brotr.delete_orphan_metadata()
        assert result == 1


class TestBrotrContextManager:
    """Brotr async context manager."""

    @pytest.mark.asyncio
    async def test_connects_and_closes(self, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        brotr = Brotr()

        with (
            patch.object(brotr.pool, "connect", new_callable=AsyncMock) as mock_connect,
            patch.object(brotr.pool, "close", new_callable=AsyncMock) as mock_close,
        ):
            async with brotr:
                mock_connect.assert_called_once()
            mock_close.assert_called_once()


class TestUpsertServiceData:
    """Brotr.upsert_service_data() JSON serialization tests."""

    @pytest.mark.asyncio
    async def test_json_fallback_for_non_dict(self, mock_brotr, mock_pool):
        """Test that list values get JSON serialized correctly."""
        # List value should serialize without issue (no fallback needed)
        records = [
            ("finder", "cursor", "api_source_1", ["item1", "item2", "item3"]),
        ]

        result = await mock_brotr.upsert_service_data(records)

        assert result == 1
        # Verify execute was called with list passed directly (JSON codec handles encoding)
        mock_conn = mock_pool._mock_connection
        call_args = mock_conn.execute.call_args
        # The 4th argument (index 3) is the values list containing Python objects
        values_list = call_args[0][4]
        assert len(values_list) == 1
        # With JSON codec, values are passed as Python objects directly
        assert values_list[0] == ["item1", "item2", "item3"]

    @pytest.mark.asyncio
    async def test_json_fallback_for_nested_objects(self, mock_brotr, mock_pool):
        """Test complex nested objects are passed correctly."""
        # Complex nested structure with various types
        complex_value = {
            "nested": {
                "level2": {
                    "level3": ["a", "b", "c"],
                    "numbers": [1, 2, 3],
                }
            },
            "list_of_dicts": [
                {"key1": "value1"},
                {"key2": "value2"},
            ],
            "mixed": [1, "string", True, None, {"inner": "dict"}],
        }
        records = [
            ("monitor", "state", "complex_key", complex_value),
        ]

        result = await mock_brotr.upsert_service_data(records)

        assert result == 1
        # Verify execute was called with Python objects (JSON codec handles encoding)
        mock_conn = mock_pool._mock_connection
        call_args = mock_conn.execute.call_args
        values_list = call_args[0][4]
        assert len(values_list) == 1
        # With JSON codec, values are passed as Python objects directly
        assert values_list[0] == complex_value
        assert values_list[0]["nested"]["level2"]["level3"] == ["a", "b", "c"]
        assert values_list[0]["list_of_dicts"][0]["key1"] == "value1"
        assert values_list[0]["mixed"] == [1, "string", True, None, {"inner": "dict"}]

    @pytest.mark.asyncio
    async def test_non_dict_values_passed_directly(self, mock_brotr, mock_pool):
        """Test that non-dict values are passed directly with JSON codec."""
        # With JSON codec, all Python objects are passed directly - asyncpg handles encoding
        records = [
            ("validator", "state", "list_key", ["a", "b", "c"]),
            ("validator", "state", "int_key", 42),
            ("validator", "state", "str_key", "simple string"),
        ]

        result = await mock_brotr.upsert_service_data(records)

        assert result == 3
        mock_conn = mock_pool._mock_connection
        call_args = mock_conn.execute.call_args
        values_list = call_args[0][4]
        assert len(values_list) == 3
        # Values are passed as Python objects
        assert values_list[0] == ["a", "b", "c"]
        assert values_list[1] == 42
        assert values_list[2] == "simple string"

    @pytest.mark.asyncio
    async def test_empty_records(self, mock_brotr):
        """Test that empty records list returns 0."""
        result = await mock_brotr.upsert_service_data([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_multiple_records(self, mock_brotr, mock_pool):
        """Test multiple records are serialized correctly."""
        records = [
            ("finder", "cursor", "key1", {"count": 1}),
            ("finder", "cursor", "key2", {"count": 2}),
            ("monitor", "state", "key3", ["a", "b"]),
        ]

        result = await mock_brotr.upsert_service_data(records)

        assert result == 3
        mock_conn = mock_pool._mock_connection
        call_args = mock_conn.execute.call_args
        # Verify all three values were passed (now as dicts due to JSON codec)
        values_list = call_args[0][4]
        assert len(values_list) == 3
        # With JSON codecs, values are passed as Python objects (not JSON strings)
        assert values_list[0] == {"count": 1}
        assert values_list[1] == {"count": 2}
        assert values_list[2] == ["a", "b"]
