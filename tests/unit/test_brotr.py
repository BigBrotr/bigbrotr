"""
Unit tests for Brotr database interface.
"""

import os

import pytest
from pydantic import ValidationError

from core.brotr import (
    BatchConfig,
    Brotr,
    BrotrConfig,
    OperationTimeoutsConfig,
    StoredProceduresConfig,
)
from core.pool import Pool


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


class TestStoredProceduresConfig:
    """Tests for StoredProceduresConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default stored procedure names."""
        config = StoredProceduresConfig()

        assert config.insert_event == "insert_event"
        assert config.insert_relay == "insert_relay"
        assert config.insert_relay_metadata == "insert_relay_metadata"
        assert config.delete_orphan_events == "delete_orphan_events"
        assert config.delete_orphan_nip11 == "delete_orphan_nip11"
        assert config.delete_orphan_nip66 == "delete_orphan_nip66"

    def test_custom_values(self) -> None:
        """Test custom procedure names."""
        config = StoredProceduresConfig(
            insert_event="custom_insert_event",
            delete_orphan_events="custom_delete",
        )

        assert config.insert_event == "custom_insert_event"
        assert config.delete_orphan_events == "custom_delete"


class TestOperationTimeoutsConfig:
    """Tests for OperationTimeoutsConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default timeout values."""
        config = OperationTimeoutsConfig()

        assert config.query == 60.0
        assert config.procedure == 90.0
        assert config.batch == 120.0

    def test_custom_values(self) -> None:
        """Test custom timeout values."""
        config = OperationTimeoutsConfig(
            query=30.0,
            procedure=45.0,
            batch=60.0,
        )

        assert config.query == 30.0
        assert config.procedure == 45.0
        assert config.batch == 60.0


class TestBrotr:
    """Tests for Brotr class."""

    def test_init_with_defaults(self) -> None:
        """Test initialization with default values."""
        os.environ["DB_PASSWORD"] = "test_pass"
        brotr = Brotr()

        assert brotr.pool is not None
        assert brotr.config.batch.max_batch_size == 10000
        assert brotr.pool.is_connected is False

    def test_init_with_injected_pool(
        self, mock_connection_pool: Pool
    ) -> None:
        """Test initialization with injected pool."""
        config = BrotrConfig(batch=BatchConfig(max_batch_size=5000))
        brotr = Brotr(pool=mock_connection_pool, config=config)

        assert brotr.pool is mock_connection_pool
        assert brotr.config.batch.max_batch_size == 5000

    def test_init_with_custom_config(self) -> None:
        """Test initialization with custom configuration."""
        os.environ["DB_PASSWORD"] = "test_pass"
        config = BrotrConfig(
            batch=BatchConfig(max_batch_size=2000),
            timeouts=OperationTimeoutsConfig(
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

    def test_from_dict(self, brotr_config: dict) -> None:
        """Test creation from dictionary."""
        brotr_config["pool"]["database"]["password"] = "dict_pass"
        brotr = Brotr.from_dict(brotr_config)

        assert brotr.pool.config.database.host == "localhost"
        assert brotr.config.batch.max_batch_size == 500

    def test_validate_batch_size_success(self, mock_brotr: Brotr) -> None:
        """Test batch size validation passes for valid size."""
        items = [{"id": i} for i in range(100)]
        # Should not raise
        mock_brotr._validate_batch_size(items, "test_operation")

    def test_validate_batch_size_exceeds_max(self, mock_brotr: Brotr) -> None:
        """Test batch size validation fails when exceeding max."""
        # Default max is 10000
        items = [{"id": i} for i in range(15000)]

        with pytest.raises(ValueError) as exc_info:
            mock_brotr._validate_batch_size(items, "test_operation")

        assert "exceeds maximum" in str(exc_info.value)
        assert "15000" in str(exc_info.value)

    def test_repr(self, mock_brotr: Brotr) -> None:
        """Test string representation."""
        repr_str = repr(mock_brotr)

        assert "Brotr" in repr_str
        assert "localhost" in repr_str


class TestBrotrInsertEvents:
    """Tests for Brotr.insert_events() method."""

    @pytest.mark.asyncio
    async def test_insert_events_empty_list(self, mock_brotr: Brotr) -> None:
        """Test inserting empty list returns True."""
        result = await mock_brotr.insert_events([])
        assert result is True

    @pytest.mark.asyncio
    async def test_insert_events_single(
        self, mock_brotr: Brotr, sample_event: dict
    ) -> None:
        """Test inserting single event."""
        result = await mock_brotr.insert_events([sample_event])
        assert result is True

    @pytest.mark.asyncio
    async def test_insert_events_multiple(
        self, mock_brotr: Brotr, sample_event: dict
    ) -> None:
        """Test inserting multiple events."""
        events = []
        for i in range(10):
            event = sample_event.copy()
            event["event_id"] = f"{i:064d}"
            events.append(event)

        result = await mock_brotr.insert_events(events)
        assert result is True

    @pytest.mark.asyncio
    async def test_insert_events_batch_size_exceeded(
        self, sample_event: dict
    ) -> None:
        """Test insert fails when batch size exceeded."""
        os.environ["DB_PASSWORD"] = "test_pass"
        config = BrotrConfig(batch=BatchConfig(max_batch_size=5))
        brotr = Brotr(config=config)

        events = [sample_event.copy() for _ in range(10)]

        with pytest.raises(ValueError) as exc_info:
            await brotr.insert_events(events)

        assert "exceeds maximum" in str(exc_info.value)


class TestBrotrInsertRelays:
    """Tests for Brotr.insert_relays() method."""

    @pytest.mark.asyncio
    async def test_insert_relays_empty_list(self, mock_brotr: Brotr) -> None:
        """Test inserting empty list returns True."""
        result = await mock_brotr.insert_relays([])
        assert result is True

    @pytest.mark.asyncio
    async def test_insert_relays_single(
        self, mock_brotr: Brotr, sample_relay: dict
    ) -> None:
        """Test inserting single relay."""
        result = await mock_brotr.insert_relays([sample_relay])
        assert result is True

    @pytest.mark.asyncio
    async def test_insert_relays_multiple(
        self, mock_brotr: Brotr, sample_relay: dict
    ) -> None:
        """Test inserting multiple relays."""
        relays = []
        for i in range(10):
            relay = sample_relay.copy()
            relay["url"] = f"wss://relay{i}.example.com"
            relays.append(relay)

        result = await mock_brotr.insert_relays(relays)
        assert result is True


class TestBrotrInsertMetadata:
    """Tests for Brotr.insert_relay_metadata() method."""

    @pytest.mark.asyncio
    async def test_insert_metadata_empty_list(self, mock_brotr: Brotr) -> None:
        """Test inserting empty list returns True."""
        result = await mock_brotr.insert_relay_metadata([])
        assert result is True

    @pytest.mark.asyncio
    async def test_insert_metadata_single(
        self, mock_brotr: Brotr, sample_metadata: dict
    ) -> None:
        """Test inserting single metadata record."""
        result = await mock_brotr.insert_relay_metadata([sample_metadata])
        assert result is True

    @pytest.mark.asyncio
    async def test_insert_metadata_without_nip11(
        self, mock_brotr: Brotr, sample_metadata: dict
    ) -> None:
        """Test inserting metadata without NIP-11 data."""
        import copy
        metadata = copy.deepcopy(sample_metadata)
        del metadata["nip11"]  # Remove entirely rather than set to None

        result = await mock_brotr.insert_relay_metadata([metadata])
        assert result is True

    @pytest.mark.asyncio
    async def test_insert_metadata_without_nip66(
        self, mock_brotr: Brotr, sample_metadata: dict
    ) -> None:
        """Test inserting metadata without NIP-66 data."""
        import copy
        metadata = copy.deepcopy(sample_metadata)
        del metadata["nip66"]  # Remove entirely rather than set to None

        result = await mock_brotr.insert_relay_metadata([metadata])
        assert result is True


class TestBrotrCleanup:
    """Tests for Brotr cleanup operations."""

    @pytest.mark.asyncio
    async def test_delete_orphan_events(self, mock_brotr: Brotr) -> None:
        """Test delete_orphan_events returns count."""
        # Mock returns 1 from fetchval
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
        """Test cleanup_orphans returns dictionary."""
        result = await mock_brotr.cleanup_orphans()

        assert "events" in result
        assert "nip11" in result
        assert "nip66" in result
        assert result["events"] == 1
        assert result["nip11"] == 1
        assert result["nip66"] == 1
