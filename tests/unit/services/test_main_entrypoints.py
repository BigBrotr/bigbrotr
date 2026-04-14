from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from bigbrotr.__main__ import cli, main
from bigbrotr.core.brotr import Brotr


_PASSWORD_ENV = "DB_WRITER_PASSWORD"  # pragma: allowlist secret


def _write_brotr_config(path: Path, content: str) -> None:
    path.write_text(content)


class TestMain:
    async def test_main_oneshot_success(self, mock_brotr_for_cli: Brotr, tmp_path: Path) -> None:
        config_file = tmp_path / "seeder.yaml"
        config_file.write_text("seed:\n  file_path: nonexistent.txt\n")

        brotr_config = tmp_path / "brotr.yaml"
        _write_brotr_config(
            brotr_config,
            "pool:\n  database:\n    host: localhost\n    port: 5432\n"
            "    database: testdb\n    user: testuser\n",
        )

        with (
            patch(
                "sys.argv",
                [
                    "prog",
                    "seeder",
                    "--config",
                    str(config_file),
                    "--brotr-config",
                    str(brotr_config),
                    "--once",
                ],
            ),
            patch("bigbrotr.__main__.Brotr.from_dict", return_value=mock_brotr_for_cli),
            patch("bigbrotr.__main__.run_service", AsyncMock(return_value=0)),
        ):
            result = await main()

        assert result == 0

    async def test_main_connection_error(self, tmp_path: Path) -> None:
        brotr_config = tmp_path / "brotr.yaml"
        _write_brotr_config(
            brotr_config,
            "pool:\n  database:\n    host: localhost\n    port: 5432\n"
            "    database: testdb\n    user: testuser\n",
        )

        mock_brotr = AsyncMock(spec=Brotr)
        mock_brotr.__aenter__.side_effect = ConnectionError("Cannot connect")

        with (
            patch("sys.argv", ["prog", "seeder", "--brotr-config", str(brotr_config)]),
            patch("bigbrotr.__main__.Brotr.from_dict", return_value=mock_brotr),
        ):
            result = await main()

        assert result == 1

    async def test_main_keyboard_interrupt(self, mock_brotr_for_cli: Brotr, tmp_path: Path) -> None:
        brotr_config = tmp_path / "brotr.yaml"
        _write_brotr_config(
            brotr_config,
            "pool:\n  database:\n    host: localhost\n    port: 5432\n"
            "    database: testdb\n    user: testuser\n",
        )

        with (
            patch("sys.argv", ["prog", "seeder", "--brotr-config", str(brotr_config)]),
            patch("bigbrotr.__main__.Brotr.from_dict", return_value=mock_brotr_for_cli),
            patch("bigbrotr.__main__.run_service", AsyncMock(side_effect=KeyboardInterrupt)),
        ):
            result = await main()

        assert result == 130

    async def test_main_uses_default_config_when_not_specified(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path
    ) -> None:
        brotr_config = tmp_path / "brotr.yaml"
        _write_brotr_config(
            brotr_config,
            "pool:\n  database:\n    host: localhost\n    port: 5432\n"
            "    database: testdb\n    user: testuser\n",
        )

        captured_service_dict: dict[str, Any] | None = None

        async def capture_run_service(*args: object, **kwargs: Any) -> int:
            nonlocal captured_service_dict
            captured_service_dict = kwargs.get("service_dict")
            return 0

        with (
            patch(
                "sys.argv",
                ["prog", "finder", "--brotr-config", str(brotr_config), "--once"],
            ),
            patch("bigbrotr.__main__.Brotr.from_dict", return_value=mock_brotr_for_cli),
            patch("bigbrotr.__main__.run_service", AsyncMock(side_effect=capture_run_service)),
        ):
            await main()

        assert captured_service_dict == {}

    async def test_main_uses_custom_config_when_specified(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path
    ) -> None:
        brotr_config = tmp_path / "brotr.yaml"
        _write_brotr_config(
            brotr_config,
            "pool:\n  database:\n    host: localhost\n    port: 5432\n"
            "    database: testdb\n    user: testuser\n",
        )

        custom_config = tmp_path / "custom_finder.yaml"
        custom_config.write_text("interval: 120.0\n")

        captured_service_dict: dict[str, Any] | None = None

        async def capture_run_service(*args: object, **kwargs: Any) -> int:
            nonlocal captured_service_dict
            captured_service_dict = kwargs.get("service_dict")
            return 0

        with (
            patch(
                "sys.argv",
                [
                    "prog",
                    "finder",
                    "--config",
                    str(custom_config),
                    "--brotr-config",
                    str(brotr_config),
                    "--once",
                ],
            ),
            patch("bigbrotr.__main__.Brotr.from_dict", return_value=mock_brotr_for_cli),
            patch("bigbrotr.__main__.run_service", AsyncMock(side_effect=capture_run_service)),
        ):
            await main()

        assert captured_service_dict == {"interval": 120.0}

    async def test_main_calls_setup_logging(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path
    ) -> None:
        brotr_config = tmp_path / "brotr.yaml"
        _write_brotr_config(
            brotr_config,
            "pool:\n  database:\n    host: localhost\n    port: 5432\n"
            "    database: testdb\n    user: testuser\n",
        )

        with (
            patch(
                "sys.argv",
                [
                    "prog",
                    "seeder",
                    "--brotr-config",
                    str(brotr_config),
                    "--log-level",
                    "DEBUG",
                    "--once",
                ],
            ),
            patch("bigbrotr.__main__.Brotr.from_dict", return_value=mock_brotr_for_cli),
            patch("bigbrotr.__main__.run_service", AsyncMock(return_value=0)),
            patch("bigbrotr.__main__.setup_logging") as mock_setup,
        ):
            await main()

        mock_setup.assert_called_once_with("DEBUG")

    async def test_main_passes_correct_service_class(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path
    ) -> None:
        from bigbrotr.services import Monitor

        brotr_config = tmp_path / "brotr.yaml"
        _write_brotr_config(
            brotr_config,
            "pool:\n  database:\n    host: localhost\n    port: 5432\n"
            "    database: testdb\n    user: testuser\n",
        )

        mock_run = AsyncMock(return_value=0)
        with (
            patch(
                "sys.argv",
                ["prog", "monitor", "--brotr-config", str(brotr_config), "--once"],
            ),
            patch("bigbrotr.__main__.Brotr.from_dict", return_value=mock_brotr_for_cli),
            patch("bigbrotr.__main__.run_service", mock_run),
        ):
            result = await main()
            assert result == 0
            mock_run.assert_called_once()

            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["service_name"] == "monitor"
            assert call_kwargs["service_class"] == Monitor

    async def test_main_extracts_pool_overrides(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path
    ) -> None:
        brotr_config = tmp_path / "brotr.yaml"
        _write_brotr_config(
            brotr_config,
            "pool:\n  database:\n    host: pgbouncer\n    database: bigbrotr\n",
        )

        service_config = tmp_path / "monitor.yaml"
        service_config.write_text(
            "pool:\n  user: writer\n"
            f"  password_env: {_PASSWORD_ENV}\n"
            "  min_size: 1\n  max_size: 3\n"
            "metrics:\n  enabled: true\n"
        )

        captured_service_dict: dict[str, Any] | None = None

        async def capture_run_service(*args: object, **kwargs: Any) -> int:
            nonlocal captured_service_dict
            captured_service_dict = kwargs.get("service_dict")
            return 0

        with (
            patch(
                "sys.argv",
                [
                    "prog",
                    "monitor",
                    "--config",
                    str(service_config),
                    "--brotr-config",
                    str(brotr_config),
                    "--once",
                ],
            ),
            patch(
                "bigbrotr.__main__.Brotr.from_dict", return_value=mock_brotr_for_cli
            ) as mock_from_dict,
            patch("bigbrotr.__main__.run_service", AsyncMock(side_effect=capture_run_service)),
        ):
            await main()

        assert captured_service_dict is not None
        assert "pool" not in captured_service_dict
        assert captured_service_dict == {"metrics": {"enabled": True}}

        brotr_call_dict = mock_from_dict.call_args[0][0]
        assert brotr_call_dict["pool"]["database"]["user"] == "writer"
        assert brotr_call_dict["pool"]["database"]["password_env"] == _PASSWORD_ENV
        assert brotr_call_dict["pool"]["database"]["host"] == "pgbouncer"
        assert brotr_call_dict["pool"]["limits"]["min_size"] == 1
        assert brotr_call_dict["pool"]["limits"]["max_size"] == 3
        assert brotr_call_dict["pool"]["server_settings"]["application_name"] == "monitor"

    async def test_main_auto_application_name_without_pool_overrides(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path
    ) -> None:
        brotr_config = tmp_path / "brotr.yaml"
        _write_brotr_config(
            brotr_config,
            "pool:\n  database:\n    host: pgbouncer\n",
        )

        service_config = tmp_path / "finder.yaml"
        service_config.write_text("metrics:\n  enabled: true\n")

        with (
            patch(
                "sys.argv",
                [
                    "prog",
                    "finder",
                    "--config",
                    str(service_config),
                    "--brotr-config",
                    str(brotr_config),
                    "--once",
                ],
            ),
            patch(
                "bigbrotr.__main__.Brotr.from_dict", return_value=mock_brotr_for_cli
            ) as mock_from_dict,
            patch("bigbrotr.__main__.run_service", AsyncMock(return_value=0)),
        ):
            await main()

        brotr_call_dict = mock_from_dict.call_args[0][0]
        assert brotr_call_dict["pool"]["server_settings"]["application_name"] == "finder"

    async def test_main_nonexistent_brotr_config_still_uses_from_dict(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path
    ) -> None:
        brotr_config = tmp_path / "nonexistent_brotr.yaml"

        with (
            patch("sys.argv", ["prog", "seeder", "--brotr-config", str(brotr_config), "--once"]),
            patch(
                "bigbrotr.__main__.Brotr.from_dict", return_value=mock_brotr_for_cli
            ) as mock_from_dict,
            patch("bigbrotr.__main__.run_service", AsyncMock(return_value=0)),
        ):
            result = await main()

        assert result == 0
        mock_from_dict.assert_called_once()
        call_dict = mock_from_dict.call_args[0][0]
        assert call_dict["pool"]["server_settings"]["application_name"] == "seeder"


class TestCli:
    @pytest.mark.parametrize("return_code", [0, 1, 130])
    def test_cli_exits_with_main_return_code(self, return_code: int) -> None:
        with (
            patch("bigbrotr.__main__.main", lambda: None),
            patch("bigbrotr.__main__.asyncio.run", return_value=return_code),
            pytest.raises(SystemExit) as exc_info,
        ):
            cli()

        assert exc_info.value.code == return_code
