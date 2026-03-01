"""Shared fixtures and helpers for services.dvm test package."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.services.common.catalog import (
    Catalog,
    ColumnSchema,
    TableSchema,
)
from bigbrotr.services.common.configs import TableConfig
from bigbrotr.services.dvm.configs import DvmConfig
from bigbrotr.services.dvm.service import Dvm


# Valid secp256k1 test key (DO NOT USE IN PRODUCTION)
VALID_HEX_KEY = (
    "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"  # pragma: allowlist secret
)


@pytest.fixture(autouse=True)
def _set_private_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set PRIVATE_KEY environment variable for all DVM tests."""
    monkeypatch.setenv("PRIVATE_KEY", VALID_HEX_KEY)


@pytest.fixture
def dvm_config() -> DvmConfig:
    """Minimal DVM config for testing."""
    return DvmConfig(
        interval=60.0,
        relays=["wss://relay.example.com"],
        kind=5050,
        max_page_size=100,
        tables={
            "relay": TableConfig(enabled=True),
            "premium_data": TableConfig(enabled=True, price=5000),
        },
    )


@pytest.fixture
def sample_dvm_catalog() -> Catalog:
    """Catalog pre-populated for DVM tests."""
    catalog = Catalog()
    catalog._tables = {
        "relay": TableSchema(
            name="relay",
            columns=(
                ColumnSchema(name="url", pg_type="text", nullable=False),
                ColumnSchema(name="network", pg_type="text", nullable=False),
            ),
            primary_key=("url",),
            is_view=False,
        ),
        "service_state": TableSchema(
            name="service_state",
            columns=(ColumnSchema(name="service_name", pg_type="text", nullable=False),),
            primary_key=("service_name",),
            is_view=False,
        ),
        "premium_data": TableSchema(
            name="premium_data",
            columns=(ColumnSchema(name="id", pg_type="integer", nullable=False),),
            primary_key=("id",),
            is_view=False,
        ),
    }
    return catalog


@pytest.fixture
def dvm_service(mock_brotr: Brotr, dvm_config: DvmConfig, sample_dvm_catalog: Catalog) -> Dvm:
    """Dvm service with mocked catalog and client."""
    service = Dvm(brotr=mock_brotr, config=dvm_config)
    service._catalog = sample_dvm_catalog
    return service


def _make_mock_event(
    event_id: str = "abc123",
    author_hex: str = "author_pubkey_hex",
    tags: list[list[str]] | None = None,
) -> MagicMock:
    """Create a mock Nostr event for testing."""
    event = MagicMock()
    event.id.return_value.to_hex.return_value = event_id
    event.author.return_value.to_hex.return_value = author_hex

    if tags is None:
        tags = [
            ["param", "table", "relay"],
            ["param", "limit", "10"],
        ]

    mock_tags = []
    for tag_values in tags:
        mock_tag = MagicMock()
        mock_tag.as_vec.return_value = tag_values
        mock_tags.append(mock_tag)

    tag_list = MagicMock()
    tag_list.to_vec.return_value = mock_tags
    event.tags.return_value = tag_list

    return event
