"""Shared fixtures and helpers for services.api test package."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bigbrotr.core.brotr import Brotr
from bigbrotr.services.api.service import Api, ApiConfig
from bigbrotr.services.common.catalog import (
    Catalog,
    ColumnSchema,
    TableSchema,
)
from bigbrotr.services.common.configs import TableConfig


@pytest.fixture
def api_config() -> ApiConfig:
    """Minimal API config for testing."""
    return ApiConfig(
        interval=60.0,
        host="127.0.0.1",
        port=9999,
        max_page_size=100,
        default_page_size=10,
        tables={
            "relay": TableConfig(enabled=True),
            "relay_stats": TableConfig(enabled=True),
        },
    )


@pytest.fixture
def sample_catalog() -> Catalog:
    """Catalog pre-populated with test tables."""
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
        "relay_stats": TableSchema(
            name="relay_stats",
            columns=(
                ColumnSchema(name="url", pg_type="text", nullable=False),
                ColumnSchema(name="event_count", pg_type="bigint", nullable=False),
            ),
            primary_key=(),
            is_view=True,
        ),
        "service_state": TableSchema(
            name="service_state",
            columns=(ColumnSchema(name="service_name", pg_type="text", nullable=False),),
            primary_key=("service_name",),
            is_view=False,
        ),
    }
    return catalog


@pytest.fixture
def api_service(mock_brotr: Brotr, api_config: ApiConfig, sample_catalog: Catalog) -> Api:
    """Api service with mocked catalog."""
    service = Api(brotr=mock_brotr, config=api_config)
    service._catalog = sample_catalog
    return service


@pytest.fixture
def test_client(api_service: Api) -> TestClient:
    """FastAPI TestClient from the Api service."""
    app = api_service._build_app()
    return TestClient(app)
