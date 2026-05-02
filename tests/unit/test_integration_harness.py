import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from docker.errors import DockerException

from tests.integration.harness.postgres import (
    DOCKER_REQUIRED_MESSAGE,
    ensure_docker_available,
    ensure_testcontainers_environment,
)
from tests.integration.harness.schema import (
    PUBLIC_TRUNCATE_TABLES_SQL,
    DeploymentSchemaState,
    deployment_sql_dir,
    ensure_deployment_schema,
    load_public_truncate_tables,
    quote_identifier,
    strip_sql_comments,
    truncate_public_tables,
)


class TestEnsureDockerAvailable:
    def test_pings_docker_and_closes_client(self) -> None:
        client = MagicMock()

        with patch(
            "tests.integration.harness.postgres.docker.from_env", return_value=client
        ) as mock_from_env:
            ensure_docker_available()

        mock_from_env.assert_called_once_with()
        client.ping.assert_called_once_with()
        client.close.assert_called_once_with()

    def test_fails_with_clear_message_when_ping_fails(self) -> None:
        client = MagicMock()
        client.ping.side_effect = DockerException("daemon unavailable")

        with (
            patch("tests.integration.harness.postgres.docker.from_env", return_value=client),
            pytest.raises(pytest.fail.Exception) as excinfo,
        ):
            ensure_docker_available()

        assert DOCKER_REQUIRED_MESSAGE in str(excinfo.value)
        assert "daemon unavailable" in str(excinfo.value)
        client.close.assert_called_once_with()

    def test_fails_with_clear_message_when_client_creation_fails(self) -> None:
        with (
            patch(
                "tests.integration.harness.postgres.docker.from_env",
                side_effect=OSError("docker socket missing"),
            ),
            pytest.raises(pytest.fail.Exception) as excinfo,
        ):
            ensure_docker_available()

        assert DOCKER_REQUIRED_MESSAGE in str(excinfo.value)
        assert "docker socket missing" in str(excinfo.value)


class TestEnsureTestcontainersEnvironment:
    def test_sets_public_pull_defaults_when_not_already_configured(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "docker-config"

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("tests.integration.harness.postgres._docker_config_dir", None),
        ):
            ensure_testcontainers_environment(config_dir)

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
            patch("tests.integration.harness.postgres._docker_config_dir", None),
        ):
            ensure_testcontainers_environment(tmp_path / "unused")

            assert os.environ["TESTCONTAINERS_RYUK_DISABLED"] == "false"
            assert os.environ["DOCKER_CONFIG"] == str(existing_config)
            assert not (tmp_path / "unused" / "config.json").exists()


class TestSchemaHelpers:
    def test_strip_sql_comments_removes_block_and_line_comments(self) -> None:
        sql = """
        -- line
        SELECT 1;
        /* block */
        """

        assert strip_sql_comments(sql) == "SELECT 1;"

    def test_quote_identifier_escapes_double_quotes(self) -> None:
        assert quote_identifier('table"name') == '"table""name"'

    def test_deployment_sql_dir_resolves_built_in_init_path(self) -> None:
        expected = Path("deployments/bigbrotr/postgres/init")

        assert deployment_sql_dir("bigbrotr").as_posix().endswith(expected.as_posix())

    async def test_load_public_truncate_tables_uses_catalog_query(self) -> None:
        conn = AsyncMock()
        conn.fetch.return_value = [
            {"relname": "event"},
            {"relname": "relay"},
            {"relname": "service_state"},
        ]

        table_names = await load_public_truncate_tables(conn)

        conn.fetch.assert_awaited_once_with(PUBLIC_TRUNCATE_TABLES_SQL)
        assert table_names == ("event", "relay", "service_state")

    async def test_truncate_public_tables_executes_dynamic_truncate(self) -> None:
        conn = AsyncMock()

        await truncate_public_tables(conn, ("event", 'table"name'))

        conn.execute.assert_awaited_once_with('TRUNCATE "event", "table""name" CASCADE')

    async def test_truncate_public_tables_skips_empty_table_list(self) -> None:
        conn = AsyncMock()

        await truncate_public_tables(conn, ())

        conn.execute.assert_not_awaited()


class TestEnsureDeploymentSchema:
    async def test_bootstraps_new_deployment_and_caches_tables(self, tmp_path: Path) -> None:
        state = DeploymentSchemaState()
        conn = AsyncMock()
        sql_dir = tmp_path / "deployments" / "bigbrotr" / "postgres" / "init"
        sql_dir.mkdir(parents=True)
        (sql_dir / "01_schema.sql").write_text("-- comment only\n")
        (sql_dir / "02_tables.sql").write_text("SELECT 1;")

        with (
            patch(
                "tests.integration.harness.schema.deployment_sql_dir",
                return_value=sql_dir,
            ),
            patch(
                "tests.integration.harness.schema.load_public_truncate_tables",
                new=AsyncMock(return_value=("event", "relay")),
            ) as mock_tables,
        ):
            await ensure_deployment_schema(conn, "bigbrotr", state=state)

        assert conn.execute.await_args_list == [
            call("DROP SCHEMA public CASCADE"),
            call("CREATE SCHEMA public"),
            call("SELECT 1;"),
        ]
        mock_tables.assert_awaited_once_with(conn)
        assert state.current_deployment == "bigbrotr"
        assert state.deployment_tables == {"bigbrotr": ("event", "relay")}

    async def test_truncates_cached_tables_for_same_deployment(self) -> None:
        state = DeploymentSchemaState(
            current_deployment="bigbrotr",
            deployment_tables={"bigbrotr": ("event", "relay")},
        )
        conn = AsyncMock()

        with patch(
            "tests.integration.harness.schema.truncate_public_tables",
            new=AsyncMock(),
        ) as mock_truncate:
            await ensure_deployment_schema(conn, "bigbrotr", state=state)

        conn.execute.assert_not_awaited()
        mock_truncate.assert_awaited_once_with(conn, ("event", "relay"))

    async def test_loads_truncate_tables_when_same_deployment_cache_is_missing(self) -> None:
        state = DeploymentSchemaState(current_deployment="bigbrotr")
        conn = AsyncMock()

        with (
            patch(
                "tests.integration.harness.schema.load_public_truncate_tables",
                new=AsyncMock(return_value=("event",)),
            ) as mock_tables,
            patch(
                "tests.integration.harness.schema.truncate_public_tables",
                new=AsyncMock(),
            ) as mock_truncate,
        ):
            await ensure_deployment_schema(conn, "bigbrotr", state=state)

        mock_tables.assert_awaited_once_with(conn)
        mock_truncate.assert_awaited_once_with(conn, ("event",))
        assert state.deployment_tables == {"bigbrotr": ("event",)}
