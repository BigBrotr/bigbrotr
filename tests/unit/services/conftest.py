from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.core.brotr import Brotr


@pytest.fixture
def mock_brotr_for_cli(mock_brotr: Brotr) -> Brotr:
    mock_brotr._pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]
    mock_brotr._pool._mock_connection.execute = AsyncMock()  # type: ignore[attr-defined]
    return mock_brotr


@pytest.fixture
def mock_metrics_server() -> MagicMock:
    server = MagicMock()
    server.stop = AsyncMock()
    return server
