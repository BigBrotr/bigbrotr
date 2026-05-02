from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from tests.system.harness import RuntimeAddressPlan
from tests.system.harness.database import RuntimeDatabaseTarget, execute, fetch_rows, fetch_value


class TestRuntimeDatabaseTarget:
    def test_for_plan_uses_deterministic_admin_credentials(self, tmp_path: Path) -> None:
        plan = RuntimeAddressPlan.create("bigbrotr", tmp_path, "db-runtime-target")

        target = RuntimeDatabaseTarget.for_plan(plan)

        assert target.host == "127.0.0.1"
        assert target.port == plan.ports.db
        assert target.database == "bigbrotr"
        assert target.user == "admin"
        assert target.password

    def test_for_plan_rejects_unknown_role(self, tmp_path: Path) -> None:
        plan = RuntimeAddressPlan.create("lilbrotr", tmp_path, "db-runtime-target")

        with pytest.raises(ValueError, match="Unsupported runtime DB role"):
            RuntimeDatabaseTarget.for_plan(plan, role="auditor")


class TestRuntimeDatabaseQueries:
    async def test_fetch_rows_normalizes_records(self) -> None:
        connection = AsyncMock()
        connection.fetch.return_value = [{"url": "wss://relay.example.com", "network": "clearnet"}]
        fake_password = "pw"  # pragma: allowlist secret

        with patch(
            "tests.system.harness.database.asyncpg.connect",
            new=AsyncMock(return_value=connection),
        ) as mock_connect:
            rows = await fetch_rows(
                RuntimeDatabaseTarget(
                    host="127.0.0.1",
                    port=5432,
                    database="bigbrotr",
                    user="admin",
                    password=fake_password,
                ),
                "SELECT url, network FROM relay",
            )

        assert rows == ({"url": "wss://relay.example.com", "network": "clearnet"},)
        mock_connect.assert_awaited_once()
        connection.fetch.assert_awaited_once_with("SELECT url, network FROM relay")
        connection.close.assert_awaited_once()

    async def test_fetch_value_returns_scalar(self) -> None:
        connection = AsyncMock()
        connection.fetchval.return_value = 2
        fake_password = "pw"  # pragma: allowlist secret

        with patch(
            "tests.system.harness.database.asyncpg.connect",
            new=AsyncMock(return_value=connection),
        ):
            count = await fetch_value(
                RuntimeDatabaseTarget(
                    host="127.0.0.1",
                    port=5432,
                    database="bigbrotr",
                    user="admin",
                    password=fake_password,
                ),
                "SELECT COUNT(*) FROM relay",
            )

        assert count == 2
        connection.fetchval.assert_awaited_once_with("SELECT COUNT(*) FROM relay")
        connection.close.assert_awaited_once()

    async def test_execute_returns_driver_status(self) -> None:
        connection = AsyncMock()
        connection.execute.return_value = "INSERT 0 1"
        fake_password = "pw"  # pragma: allowlist secret

        with patch(
            "tests.system.harness.database.asyncpg.connect",
            new=AsyncMock(return_value=connection),
        ):
            status = await execute(
                RuntimeDatabaseTarget(
                    host="127.0.0.1",
                    port=5432,
                    database="bigbrotr",
                    user="admin",
                    password=fake_password,
                ),
                "INSERT INTO relay (url, network) VALUES ($1, $2)",
                "wss://relay.example.com",
                "clearnet",
            )

        assert status == "INSERT 0 1"
        connection.execute.assert_awaited_once_with(
            "INSERT INTO relay (url, network) VALUES ($1, $2)",
            "wss://relay.example.com",
            "clearnet",
        )
        connection.close.assert_awaited_once()
