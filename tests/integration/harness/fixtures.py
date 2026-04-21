"""Shared pytest fixtures for the integration harness."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from testcontainers.postgres import PostgresContainer

from tests.integration.harness.brotr import PgDsn
from tests.integration.harness.postgres import (
    ensure_docker_available,
    ensure_testcontainers_environment,
)


if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(scope="session")
def pg_container() -> Iterator[PostgresContainer]:
    """Spawn an ephemeral PostgreSQL 18 container for the test session."""
    ensure_docker_available()
    ensure_testcontainers_environment()
    with PostgresContainer("postgres:18-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def pg_dsn(pg_container: PostgresContainer) -> PgDsn:
    """Extract connection parameters from the running container."""
    return {
        "host": pg_container.get_container_host_ip(),
        "port": int(pg_container.get_exposed_port(5432)),
        "database": pg_container.dbname,
        "user": pg_container.username,
        "password": pg_container.password,
    }
