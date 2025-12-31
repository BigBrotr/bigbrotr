"""Tests for core.brotr module."""

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


class TestBrotrInsertEvents:
    """Brotr.insert_events() method."""

    @pytest.mark.asyncio
    async def test_empty_list(self, mock_brotr):
        inserted, skipped = await mock_brotr.insert_events([])
        assert inserted == 0
        assert skipped == 0

    @pytest.mark.asyncio
    async def test_single(self, mock_brotr, sample_event):
        inserted, skipped = await mock_brotr.insert_events([sample_event])
        assert inserted == 1

    @pytest.mark.asyncio
    async def test_multiple(self, mock_brotr, sample_events_batch):
        inserted, skipped = await mock_brotr.insert_events(sample_events_batch)
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

    @pytest.mark.asyncio
    async def test_delete_failed_candidates(self, mock_brotr):
        result = await mock_brotr.delete_failed_candidates(max_attempts=10)
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
