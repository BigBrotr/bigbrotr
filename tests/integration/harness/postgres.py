"""PostgreSQL container lifecycle helpers for integration tests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import docker
import pytest
from docker.errors import DockerException


DOCKER_REQUIRED_MESSAGE = (
    "Docker is required to run integration tests. "
    "Start a Docker daemon or run the unit test suite instead."
)
TESTCONTAINERS_RYUK_DISABLED_ENV = "TESTCONTAINERS_RYUK_DISABLED"
TESTCONTAINERS_DOCKER_CONFIG_ENV = "DOCKER_CONFIG"

_docker_config_dir: Path | None = None


def ensure_docker_available() -> None:
    """Fail fast with a clear message when Docker is unavailable."""
    try:
        client = docker.from_env()
        try:
            client.ping()
        finally:
            client.close()
    except (DockerException, OSError) as exc:
        pytest.fail(f"{DOCKER_REQUIRED_MESSAGE} Original error: {exc}", pytrace=False)


def ensure_testcontainers_environment(config_dir: Path | None = None) -> None:
    """Prepare a deterministic Docker environment for public testcontainers pulls."""
    global _docker_config_dir  # noqa: PLW0603

    os.environ.setdefault(TESTCONTAINERS_RYUK_DISABLED_ENV, "true")

    if TESTCONTAINERS_DOCKER_CONFIG_ENV in os.environ:
        return

    if _docker_config_dir is None:
        target = config_dir or Path(tempfile.mkdtemp(prefix="bigbrotr-docker-config-"))
        target.mkdir(parents=True, exist_ok=True)
        (target / "config.json").write_text("{}")
        _docker_config_dir = target

    os.environ[TESTCONTAINERS_DOCKER_CONFIG_ENV] = str(_docker_config_dir)
