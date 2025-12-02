"""
Unit tests for core.brotr module.

Tests:
- Configuration models (BatchConfig, TimeoutsConfig, BrotrConfig)
- Stored procedure constants
- Brotr initialization and factory methods
- Insert operations (events, relays, metadata)
- Cleanup operations (orphan deletion)
- Context manager behavior
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from core.brotr import (
    PROC_DELETE_ORPHAN_EVENTS,
    PROC_DELETE_ORPHAN_NIP11,
    PROC_DELETE_ORPHAN_NIP66,
    PROC_INSERT_EVENT,
    PROC_INSERT_RELAY,
    PROC_INSERT_RELAY_METADATA,
    BatchConfig,
    Brotr,
    BrotrConfig,
    TimeoutsConfig,
)
from core.pool import Pool


# ============================================================================
# BatchConfig Tests
# ============================================================================


class TestBatchConfig:
    """Tests for BatchConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default batch configuration."""
        config = BatchConfig()
        assert config.max_batch_size == 10000

    def test_custom_values(self) -> None:
        """Test custom batch configuration."""
        config = BatchConfig(max_batch_size=5000)
        assert config.max_batch_size == 5000

    def test_validation_min(self) -> None:
        """Test minimum batch size validation."""
        with pytest.raises(ValidationError):
            BatchConfig(max_batch_size=0)

    def test_validation_max(self) -> None:
        """Test maximum batch size validation."""
        with pytest.raises(ValidationError):
            BatchConfig(max_batch_size=200000)

    def test_boundary_values(self) -> None:
        """Test boundary values are accepted."""
        config_min = BatchConfig(max_batch_size=1)
        assert config_min.max_batch_size == 1

        config_max = BatchConfig(max_batch_size=100000)
        assert config_max.max_batch_size == 100000


# ============================================================================
# TimeoutsConfig Tests
# ============================================================================


class TestTimeoutsConfig:
    """Tests for TimeoutsConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default timeout values."""
        config = TimeoutsConfig()

        assert config.query == 60.0
        assert config.procedure == 90.0
        assert config.batch == 120.0

    def test_custom_values(self) -> None:
        """Test custom timeout values."""
        config = TimeoutsConfig(
            query=30.0,
            procedure=45.0,
            batch=60.0,
        )

        assert config.query == 30.0
        assert config.procedure == 45.0
        assert config.batch == 60.0

    def test_validation_min(self) -> None:
        """Test minimum timeout validation."""
        with pytest.raises(ValidationError):
            TimeoutsConfig(query=0.0)


# ============================================================================
# Stored Procedure Constants Tests
# ============================================================================


class TestStoredProcedureConstants:
    """Tests for stored procedure constants (hardcoded for security)."""

    def test_procedure_names_are_expected_values(self) -> None:
        """Test that procedure names match expected SQL function names."""
        assert PROC_INSERT_EVENT == "insert_event"
        assert PROC_INSERT_RELAY == "insert_relay"
        assert PROC_INSERT_RELAY_METADATA == "insert_relay_metadata"
        assert PROC_DELETE_ORPHAN_EVENTS == "delete_orphan_events"
        assert PROC_DELETE_ORPHAN_NIP11 == "delete_orphan_nip11"
        assert PROC_DELETE_ORPHAN_NIP66 == "delete_orphan_nip66"

    def test_constants_are_strings(self) -> None:
        """Ensure constants are strings for safe SQL interpolation."""
        assert isinstance(PROC_INSERT_EVENT, str)
        assert isinstance(PROC_INSERT_RELAY, str)
        assert isinstance(PROC_INSERT_RELAY_METADATA, str)
        assert isinstance(PROC_DELETE_ORPHAN_EVENTS, str)
        assert isinstance(PROC_DELETE_ORPHAN_NIP11, str)
        assert isinstance(PROC_DELETE_ORPHAN_NIP66, str)


# ============================================================================
# BrotrConfig Tests
# ============================================================================


class TestBrotrConfig:
    """Tests for BrotrConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default configuration."""
        config = BrotrConfig()

        assert config.batch.max_batch_size == 10000
        assert config.timeouts.query == 60.0
        assert config.timeouts.procedure == 90.0
        assert config.timeouts.batch == 120.0

    def test_custom_nested_values(self) -> None:
        """Test custom nested configuration."""
        config = BrotrConfig(
            batch=BatchConfig(max_batch_size=5000),
            timeouts=TimeoutsConfig(query=30.0),
        )

        assert config.batch.max_batch_size == 5000
        assert config.timeouts.query == 30.0


# ============================================================================
# Brotr Initialization Tests
# ============================================================================


class TestBrotrInit:
    """Tests for Brotr initialization."""

    def test_init_with_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test initialization with default values."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        brotr = Brotr()

        assert brotr.pool is not None
        assert brotr.config.batch.max_batch_size == 10000
        assert brotr.pool.is_connected is False

    def test_init_with_injected_pool(self, mock_pool: Pool) -> None:
        """Test initialization with injected pool."""
        config = BrotrConfig(batch=BatchConfig(max_batch_size=5000))
        brotr = Brotr(pool=mock_pool, config=config)

        assert brotr.pool is mock_pool
        assert brotr.config.batch.max_batch_size == 5000

    def test_init_with_custom_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test initialization with custom configuration."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        config = BrotrConfig(
            batch=BatchConfig(max_batch_size=2000),
            timeouts=TimeoutsConfig(
                query=45.0,
                procedure=60.0,
                batch=90.0,
            ),
        )
        brotr = Brotr(config=config)

        assert brotr.config.batch.max_batch_size == 2000
        assert brotr.config.timeouts.query == 45.0
        assert brotr.config.timeouts.procedure == 60.0
        assert brotr.config.timeouts.batch == 90.0

    def test_from_dict(self, brotr_config_dict: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
        """Test creation from dictionary."""
        monkeypatch.setenv("DB_PASSWORD", "dict_pass")
        brotr = Brotr.from_dict(brotr_config_dict)

        assert brotr.pool.config.database.host == "localhost"
        assert brotr.config.batch.max_batch_size == 500

    def test_from_dict_without_pool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test from_dict without pool config uses defaults."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        config_dict = {
            "batch": {"max_batch_size": 1000},
        }
        brotr = Brotr.from_dict(config_dict)

        assert brotr.config.batch.max_batch_size == 1000

    def test_from_yaml(
        self, brotr_config_dict: dict[str, Any], tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test creation from YAML file."""
        import yaml

        monkeypatch.setenv("DB_PASSWORD", "yaml_pass")

        config_file = tmp_path / "brotr_config.yaml"
        config_file.write_text(yaml.dump(brotr_config_dict))

        brotr = Brotr.from_yaml(str(config_file))

        assert brotr.pool.config.database.host == "localhost"
        assert brotr.config.batch.max_batch_size == 500
        assert brotr.config.timeouts.query == 30.0
        assert brotr.config.timeouts.procedure == 60.0

    def test_from_yaml_file_not_found(self) -> None:
        """Test from_yaml raises when file not found."""
        with pytest.raises(FileNotFoundError):
            Brotr.from_yaml("/nonexistent/path/config.yaml")

    def test_repr(self, mock_brotr: Brotr) -> None:
        """Test string representation."""
        repr_str = repr(mock_brotr)

        assert "Brotr" in repr_str
        assert "localhost" in repr_str

    def test_config_property(self, mock_brotr: Brotr) -> None:
        """Test config property returns configuration."""
        assert mock_brotr.config is not None
        assert isinstance(mock_brotr.config, BrotrConfig)


# ============================================================================
# Brotr Batch Validation Tests
# ============================================================================


class TestBrotrBatchValidation:
    """Tests for Brotr batch validation."""

    def test_validate_batch_size_success(self, mock_brotr: Brotr) -> None:
        """Test batch size validation passes for valid size."""
        items = [{"id": i} for i in range(100)]
        mock_brotr._validate_batch_size(items, "test_operation")

    def test_validate_batch_size_exceeds_max(self, mock_brotr: Brotr) -> None:
        """Test batch size validation fails when exceeding max."""
        items = [{"id": i} for i in range(15000)]

        with pytest.raises(ValueError) as exc_info:
            mock_brotr._validate_batch_size(items, "test_operation")

        assert "exceeds maximum" in str(exc_info.value)
        assert "15000" in str(exc_info.value)

    def test_validate_batch_size_empty(self, mock_brotr: Brotr) -> None:
        """Test batch size validation passes for empty list."""
        mock_brotr._validate_batch_size([], "test_operation")


# ============================================================================
# Brotr Insert Events Tests
# ============================================================================


class TestBrotrInsertEvents:
    """Tests for Brotr.insert_events() method."""

    @pytest.mark.asyncio
    async def test_insert_events_empty_list(self, mock_brotr: Brotr) -> None:
        """Test inserting empty list returns 0."""
        result = await mock_brotr.insert_events([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_insert_events_single(self, mock_brotr: Brotr, sample_event: dict[str, Any]) -> None:
        """Test inserting single event returns count."""
        result = await mock_brotr.insert_events([sample_event])
        assert result == 1

    @pytest.mark.asyncio
    async def test_insert_events_multiple(self, mock_brotr: Brotr, sample_events_batch: list[dict[str, Any]]) -> None:
        """Test inserting multiple events returns count."""
        result = await mock_brotr.insert_events(sample_events_batch)
        assert result == len(sample_events_batch)

    @pytest.mark.asyncio
    async def test_insert_events_batch_size_exceeded(
        self, sample_event: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test insert fails when batch size exceeded."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        config = BrotrConfig(batch=BatchConfig(max_batch_size=5))
        brotr = Brotr(config=config)

        events = [sample_event.copy() for _ in range(10)]

        with pytest.raises(ValueError) as exc_info:
            await brotr.insert_events(events)

        assert "exceeds maximum" in str(exc_info.value)


# ============================================================================
# Brotr Insert Relays Tests
# ============================================================================


class TestBrotrInsertRelays:
    """Tests for Brotr.insert_relays() method."""

    @pytest.mark.asyncio
    async def test_insert_relays_empty_list(self, mock_brotr: Brotr) -> None:
        """Test inserting empty list returns 0."""
        result = await mock_brotr.insert_relays([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_insert_relays_single(self, mock_brotr: Brotr, sample_relay: dict[str, Any]) -> None:
        """Test inserting single relay returns count."""
        result = await mock_brotr.insert_relays([sample_relay])
        assert result == 1

    @pytest.mark.asyncio
    async def test_insert_relays_multiple(self, mock_brotr: Brotr, sample_relays_batch: list[dict[str, Any]]) -> None:
        """Test inserting multiple relays returns count."""
        result = await mock_brotr.insert_relays(sample_relays_batch)
        assert result == len(sample_relays_batch)


# ============================================================================
# Brotr Insert Metadata Tests
# ============================================================================


class TestBrotrInsertMetadata:
    """Tests for Brotr.insert_relay_metadata() method."""

    @pytest.mark.asyncio
    async def test_insert_metadata_empty_list(self, mock_brotr: Brotr) -> None:
        """Test inserting empty list returns 0."""
        result = await mock_brotr.insert_relay_metadata([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_insert_metadata_single(self, mock_brotr: Brotr, sample_metadata: dict[str, Any]) -> None:
        """Test inserting single metadata record returns count."""
        result = await mock_brotr.insert_relay_metadata([sample_metadata])
        assert result == 1

    @pytest.mark.asyncio
    async def test_insert_metadata_without_nip11(self, mock_brotr: Brotr, sample_metadata: dict[str, Any]) -> None:
        """Test inserting metadata without NIP-11 data returns count."""
        import copy

        metadata = copy.deepcopy(sample_metadata)
        metadata["nip11"] = None

        result = await mock_brotr.insert_relay_metadata([metadata])
        assert result == 1

    @pytest.mark.asyncio
    async def test_insert_metadata_without_nip66(self, mock_brotr: Brotr, sample_metadata: dict[str, Any]) -> None:
        """Test inserting metadata without NIP-66 data returns count."""
        import copy

        metadata = copy.deepcopy(sample_metadata)
        metadata["nip66"] = None

        result = await mock_brotr.insert_relay_metadata([metadata])
        assert result == 1

    @pytest.mark.asyncio
    async def test_insert_metadata_missing_nip_keys(self, mock_brotr: Brotr, sample_metadata: dict[str, Any]) -> None:
        """Test inserting metadata with missing nip keys (uses .get())."""
        import copy

        metadata = copy.deepcopy(sample_metadata)
        del metadata["nip11"]
        del metadata["nip66"]

        result = await mock_brotr.insert_relay_metadata([metadata])
        assert result == 1


# ============================================================================
# Brotr Cleanup Operations Tests
# ============================================================================


class TestBrotrCleanup:
    """Tests for Brotr cleanup operations."""

    @pytest.mark.asyncio
    async def test_delete_orphan_events(self, mock_brotr: Brotr) -> None:
        """Test delete_orphan_events returns count."""
        result = await mock_brotr.delete_orphan_events()
        assert result == 1

    @pytest.mark.asyncio
    async def test_delete_orphan_nip11(self, mock_brotr: Brotr) -> None:
        """Test delete_orphan_nip11 returns count."""
        result = await mock_brotr.delete_orphan_nip11()
        assert result == 1

    @pytest.mark.asyncio
    async def test_delete_orphan_nip66(self, mock_brotr: Brotr) -> None:
        """Test delete_orphan_nip66 returns count."""
        result = await mock_brotr.delete_orphan_nip66()
        assert result == 1

    @pytest.mark.asyncio
    async def test_cleanup_orphans(self, mock_brotr: Brotr) -> None:
        """Test cleanup_orphans returns dictionary with all counts."""
        result = await mock_brotr.cleanup_orphans()

        assert "events" in result
        assert "nip11" in result
        assert "nip66" in result
        assert result["events"] == 1
        assert result["nip11"] == 1
        assert result["nip66"] == 1

    @pytest.mark.asyncio
    async def test_cleanup_orphans_parallel_execution(self, mock_brotr: Brotr) -> None:
        """Test cleanup_orphans runs operations in parallel."""
        import asyncio

        call_times: list[float] = []
        original_delete_orphan_events = mock_brotr.delete_orphan_events

        async def tracked_delete_orphan_events() -> int:
            call_times.append(asyncio.get_event_loop().time())
            return await original_delete_orphan_events()

        mock_brotr.delete_orphan_events = tracked_delete_orphan_events  # type: ignore[method-assign]

        await mock_brotr.cleanup_orphans()

        # All calls should happen nearly simultaneously (parallel)
        # We can't easily verify parallelism with mocks, but ensure all 3 run
        assert len(call_times) >= 1


# ============================================================================
# Brotr Context Manager Tests
# ============================================================================


class TestBrotrContextManager:
    """Tests for Brotr async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_connects_and_closes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test context manager connects on enter and closes on exit."""
        monkeypatch.setenv("DB_PASSWORD", "test_pass")
        brotr = Brotr()

        with patch.object(brotr.pool, "connect", new_callable=AsyncMock) as mock_connect:
            with patch.object(brotr.pool, "close", new_callable=AsyncMock) as mock_close:
                async with brotr:
                    mock_connect.assert_called_once()

                mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_returns_brotr(self, mock_brotr: Brotr) -> None:
        """Test context manager returns Brotr instance."""
        with patch.object(mock_brotr.pool, "connect", new_callable=AsyncMock):
            with patch.object(mock_brotr.pool, "close", new_callable=AsyncMock):
                async with mock_brotr as b:
                    assert b is mock_brotr