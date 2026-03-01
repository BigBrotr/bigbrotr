"""Shared fixtures and helpers for services.validator test package."""

from unittest.mock import AsyncMock

import pytest

from bigbrotr.core.brotr import Brotr


def make_candidate_row(url: str, network: str = "clearnet", failures: int = 0) -> dict:
    """Create a mock candidate row from database."""
    return {
        "service_name": "validator",
        "state_type": "candidate",
        "state_key": url,
        "state_value": {"network": network, "failures": failures},
        "updated_at": 1700000000,
    }


@pytest.fixture
def mock_validator_brotr(mock_brotr: Brotr) -> Brotr:
    """Create a mock Brotr instance for validator tests."""
    # Mock additional methods needed by Validator
    mock_brotr.insert_relay = AsyncMock()
    mock_brotr.delete_service_state = AsyncMock()
    mock_brotr.upsert_service_state = AsyncMock()
    return mock_brotr
