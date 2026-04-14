from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from docker.errors import DockerException

from tests.integration.conftest import (
    _DOCKER_REQUIRED_MESSAGE,
    _PUBLIC_TRUNCATE_TABLES_SQL,
    _ensure_docker_available,
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
