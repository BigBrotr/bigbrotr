"""Shared fixtures and helpers for services.seeder test package."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.core.brotr import Brotr, BrotrConfig


@pytest.fixture
def mock_seeder_brotr(mock_brotr: Brotr) -> Brotr:
    """Create a Brotr mock configured for seeder tests."""
    # Default successful responses
    mock_brotr._pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]
    mock_brotr._pool._mock_connection.execute = AsyncMock()  # type: ignore[attr-defined]

    # Setup config with batch settings
    mock_batch_config = MagicMock()
    mock_batch_config.max_size = 100
    mock_config = MagicMock(spec=BrotrConfig)
    mock_config.batch = mock_batch_config
    mock_config.timeouts = MagicMock()
    mock_config.timeouts.query = 30.0
    mock_brotr._config = mock_config

    return mock_brotr
