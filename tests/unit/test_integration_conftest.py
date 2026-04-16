import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from docker.errors import DockerException

from tests.integration.conftest import (
    _DOCKER_REQUIRED_MESSAGE,
    _PUBLIC_TRUNCATE_TABLES_SQL,
    _ensure_docker_available,
    _ensure_testcontainers_environment,
    _load_public_truncate_tables,
    _quote_identifier,
    _truncate_public_tables,
)


class TestEnsureDockerAvailable:
    def test_pings_docker_and_closes_client(self) -> None:
        client = MagicMock()

        with patch(
            "tests.integration.conftest.docker.from_env", return_value=client
        ) as mock_from_env:
            _ensure_docker_available()

        mock_from_env.assert_called_once_with()
        client.ping.assert_called_once_with()
        client.close.assert_called_once_with()

    def test_fails_with_clear_message_when_ping_fails(self) -> None:
        client = MagicMock()
        client.ping.side_effect = DockerException("daemon unavailable")

        with (
            patch("tests.integration.conftest.docker.from_env", return_value=client),
            pytest.raises(pytest.fail.Exception) as excinfo,
        ):
            _ensure_docker_available()

        assert _DOCKER_REQUIRED_MESSAGE in str(excinfo.value)
        assert "daemon unavailable" in str(excinfo.value)
        client.close.assert_called_once_with()

    def test_fails_with_clear_message_when_client_creation_fails(self) -> None:
        with (
            patch(
                "tests.integration.conftest.docker.from_env",
                side_effect=OSError("docker socket missing"),
            ),
            pytest.raises(pytest.fail.Exception) as excinfo,
        ):
            _ensure_docker_available()

        assert _DOCKER_REQUIRED_MESSAGE in str(excinfo.value)
        assert "docker socket missing" in str(excinfo.value)


class TestEnsureTestcontainersEnvironment:
    def test_sets_public_pull_defaults_when_not_already_configured(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "docker-config"

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("tests.integration.conftest._docker_config_dir", None),
        ):
            _ensure_testcontainers_environment(config_dir)

            assert os.environ["TESTCONTAINERS_RYUK_DISABLED"] == "true"
            assert os.environ["DOCKER_CONFIG"] == str(config_dir)
            assert (config_dir / "config.json").read_text() == "{}"

    def test_preserves_existing_environment_overrides(self, tmp_path: Path) -> None:
        existing_config = tmp_path / "existing"
        existing_config.mkdir()

        with (
            patch.dict(
                os.environ,
                {
                    "TESTCONTAINERS_RYUK_DISABLED": "false",
                    "DOCKER_CONFIG": str(existing_config),
                },
                clear=True,
            ),
            patch("tests.integration.conftest._docker_config_dir", None),
        ):
            _ensure_testcontainers_environment(tmp_path / "unused")

            assert os.environ["TESTCONTAINERS_RYUK_DISABLED"] == "false"
            assert os.environ["DOCKER_CONFIG"] == str(existing_config)
            assert not (tmp_path / "unused" / "config.json").exists()


class TestTruncateTableHelpers:
    def test_quote_identifier_escapes_double_quotes(self) -> None:
        assert _quote_identifier('table"name') == '"table""name"'

    async def test_load_public_truncate_tables_uses_catalog_query(self) -> None:
        conn = AsyncMock()
        conn.fetch.return_value = [
            {"relname": "event"},
            {"relname": "relay"},
            {"relname": "service_state"},
        ]

        table_names = await _load_public_truncate_tables(conn)

        conn.fetch.assert_awaited_once_with(_PUBLIC_TRUNCATE_TABLES_SQL)
        assert table_names == ("event", "relay", "service_state")

    async def test_truncate_public_tables_executes_dynamic_truncate(self) -> None:
        conn = AsyncMock()

        await _truncate_public_tables(conn, ("event", 'table"name'))

        conn.execute.assert_awaited_once_with('TRUNCATE "event", "table""name" CASCADE')

    async def test_truncate_public_tables_skips_empty_table_list(self) -> None:
        conn = AsyncMock()

        await _truncate_public_tables(conn, ())

        conn.execute.assert_not_awaited()
