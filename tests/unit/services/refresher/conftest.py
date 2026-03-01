"""Shared fixtures and helpers for services.refresher test package."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.core.brotr import Brotr, BrotrConfig


@pytest.fixture
def mock_refresher_brotr(mock_brotr: Brotr) -> Brotr:
    """Create a Brotr mock configured for refresher tests."""
    mock_brotr.refresh_materialized_view = AsyncMock()  # type: ignore[method-assign]

    mock_config = MagicMock(spec=BrotrConfig)
    mock_config.timeouts = MagicMock()
    mock_config.timeouts.refresh = None
    mock_brotr._config = mock_config

    return mock_brotr
