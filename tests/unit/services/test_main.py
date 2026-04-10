import asyncio
import logging
import signal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bigbrotr.__main__ import (
    SERVICE_REGISTRY,
    ServiceEntry,
    _apply_pool_overrides,
    _load_yaml_dict,
    cli,
    main,
    parse_args,
    run_service,
    setup_logging,
)
from bigbrotr.core.brotr import Brotr


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_brotr_for_cli(mock_brotr: Brotr) -> Brotr:
    mock_brotr._pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]
    mock_brotr._pool._mock_connection.execute = AsyncMock()  # type: ignore[attr-defined]
    return mock_brotr


@pytest.fixture
def mock_metrics_server() -> MagicMock:
    server = MagicMock()
    server.stop = AsyncMock()
    return server


# ============================================================================
# SERVICE_REGISTRY Tests
# ============================================================================


class TestServiceRegistry:
    def test_all_services_registered(self) -> None:
        expected = {
            "seeder",
            "finder",
            "validator",
            "monitor",
            "synchronizer",
            "refresher",
            "ranker",
            "api",
            "dvm",
            "assertor",
        }
        assert set(SERVICE_REGISTRY.keys()) == expected

    def test_service_config_paths(self) -> None:
        from bigbrotr.__main__ import CONFIG_BASE

        for name, (_, config_path) in SERVICE_REGISTRY.items():
            expected = CONFIG_BASE / "services" / f"{name}.yaml"
            assert config_path == expected, f"{name} config path mismatch"

    def test_service_classes_are_base_service_subclasses(self) -> None:
        from bigbrotr.core.base_service import BaseService

        for name, (service_class, _) in SERVICE_REGISTRY.items():
            assert issubclass(service_class, BaseService), (
                f"{name} should be a BaseService subclass"
            )

    def test_registry_entries_are_service_entry(self) -> None:
        for name, entry in SERVICE_REGISTRY.items():
            assert isinstance(entry, ServiceEntry), f"{name} should be a ServiceEntry"

    def test_service_classes_match_expected(self) -> None:
        from bigbrotr.services import (
            Api,
            Assertor,
            Dvm,
            Finder,
            Monitor,
            Ranker,
            Refresher,
            Seeder,
            Synchronizer,
            Validator,
        )

        expected_classes = {
            "seeder": Seeder,
            "finder": Finder,
            "validator": Validator,
            "monitor": Monitor,
            "refresher": Refresher,
            "ranker": Ranker,
            "synchronizer": Synchronizer,
            "api": Api,
            "dvm": Dvm,
            "assertor": Assertor,
        }

        for name, (service_class, _) in SERVICE_REGISTRY.items():
            assert service_class == expected_classes[name]


# ============================================================================
# parse_args Tests
# ============================================================================


class TestParseArgs:
    def test_service_required(self) -> None:
        with patch("sys.argv", ["prog"]), pytest.raises(SystemExit):
            parse_args()

    def test_valid_service(self) -> None:
        with patch("sys.argv", ["prog", "finder"]):
            args = parse_args()
            assert args.service == "finder"

    def test_invalid_service_rejected(self) -> None:
        with patch("sys.argv", ["prog", "invalid"]), pytest.raises(SystemExit):
            parse_args()

    def test_all_services_accepted(self) -> None:
        for service_name in SERVICE_REGISTRY:
            with patch("sys.argv", ["prog", service_name]):
                args = parse_args()
                assert args.service == service_name

    def test_config_option(self) -> None:
        with patch("sys.argv", ["prog", "finder", "--config", "custom/config.yaml"]):
            args = parse_args()
            assert args.config == Path("custom/config.yaml")

    def test_config_option_default_is_none(self) -> None:
        with patch("sys.argv", ["prog", "finder"]):
            args = parse_args()
            assert args.config is None

    def test_brotr_config_default(self) -> None:
        from bigbrotr.__main__ import CORE_CONFIG

        with patch("sys.argv", ["prog", "finder"]):
            args = parse_args()
            assert args.brotr_config == CORE_CONFIG

    def test_brotr_config_custom(self) -> None:
        with patch("sys.argv", ["prog", "finder", "--brotr-config", "custom/brotr.yaml"]):
            args = parse_args()
            assert args.brotr_config == Path("custom/brotr.yaml")

    def test_log_level_default(self) -> None:
        with patch("sys.argv", ["prog", "finder"]):
            args = parse_args()
            assert args.log_level == "INFO"

    @pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR"])
    def test_log_level_choices(self, level: str) -> None:
        with patch("sys.argv", ["prog", "finder", "--log-level", level]):
            args = parse_args()
            assert args.log_level == level

    @pytest.mark.parametrize("invalid_level", ["INVALID", "debug", "info"])
    def test_log_level_invalid_rejected(self, invalid_level: str) -> None:
        with (
            patch("sys.argv", ["prog", "finder", "--log-level", invalid_level]),
            pytest.raises(SystemExit),
        ):
            parse_args()

    def test_once_flag_default(self) -> None:
        with patch("sys.argv", ["prog", "finder"]):
            args = parse_args()
            assert args.once is False

    def test_once_flag_enabled(self) -> None:
        with patch("sys.argv", ["prog", "finder", "--once"]):
            args = parse_args()
            assert args.once is True

    def test_combined_arguments(self) -> None:
        with patch(
            "sys.argv",
            [
                "prog",
                "monitor",
                "--config",
                "custom/monitor.yaml",
                "--brotr-config",
                "custom/brotr.yaml",
                "--log-level",
                "DEBUG",
                "--once",
            ],
        ):
            args = parse_args()
            assert args.service == "monitor"
            assert args.config == Path("custom/monitor.yaml")
            assert args.brotr_config == Path("custom/brotr.yaml")
            assert args.log_level == "DEBUG"
            assert args.once is True


# ============================================================================
# setup_logging Tests
# ============================================================================


class TestSetupLogging:
    def _cleanup_root_handlers(self) -> None:
        from bigbrotr.core.logger import StructuredFormatter

        logging.root.handlers = [
            h for h in logging.root.handlers if not isinstance(h.formatter, StructuredFormatter)
        ]

    @pytest.mark.parametrize(
        ("level_name", "level_value"),
        [
            ("DEBUG", logging.DEBUG),
            ("INFO", logging.INFO),
            ("WARNING", logging.WARNING),
            ("ERROR", logging.ERROR),
        ],
    )
    def test_log_level_configured(self, level_name: str, level_value: int) -> None:
        setup_logging(level_name)
        assert logging.root.level == level_value
        self._cleanup_root_handlers()

    def test_structured_formatter_installed(self) -> None:
        from bigbrotr.core.logger import StructuredFormatter

        setup_logging("INFO")
        structured_handlers = [
            h for h in logging.root.handlers if isinstance(h.formatter, StructuredFormatter)
        ]
        assert len(structured_handlers) >= 1
        assert all(isinstance(h, logging.StreamHandler) for h in structured_handlers)
        self._cleanup_root_handlers()


# ============================================================================
# _load_yaml_dict Tests
# ============================================================================


class TestLoadYamlDict:
    def test_load_from_existing_file(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text("key: value\nnested:\n  a: 1\n")
        result = _load_yaml_dict(config_file)
        assert result == {"key": "value", "nested": {"a": 1}}

    def test_load_from_nonexistent_file(self, tmp_path: Path) -> None:
        config_file = tmp_path / "nonexistent.yaml"
        result = _load_yaml_dict(config_file)
        assert result == {}

    def test_load_empty_file(self, tmp_path: Path) -> None:
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")
        result = _load_yaml_dict(config_file)
        assert result == {}

    def test_load_preserves_types(self, tmp_path: Path) -> None:
        config_file = tmp_path / "typed.yaml"
        config_file.write_text("count: 42\nenabled: true\nratio: 3.14\nname: test\n")
        result = _load_yaml_dict(config_file)
        assert result == {"count": 42, "enabled": True, "ratio": 3.14, "name": "test"}


# ============================================================================
# _apply_pool_overrides Tests
# ============================================================================


class TestApplyPoolOverrides:
    def test_no_overrides_sets_application_name(self) -> None:
        brotr_dict: dict = {}
        _apply_pool_overrides(brotr_dict, None, "monitor")
        assert brotr_dict["pool"]["server_settings"]["application_name"] == "monitor"

    def test_no_overrides_preserves_existing_application_name(self) -> None:
        brotr_dict: dict = {"pool": {"server_settings": {"application_name": "custom"}}}
        _apply_pool_overrides(brotr_dict, None, "monitor")
        assert brotr_dict["pool"]["server_settings"]["application_name"] == "custom"

    def test_full_overrides(self) -> None:
        brotr_dict: dict = {"pool": {"database": {"host": "pgbouncer"}}}
        overrides = {
            "user": "writer",
            "password_env": "DB_WRITER_PASSWORD",  # pragma: allowlist secret
            "min_size": 1,
            "max_size": 3,
        }
        _apply_pool_overrides(brotr_dict, overrides, "monitor")

        assert brotr_dict["pool"]["database"]["user"] == "writer"
        assert brotr_dict["pool"]["database"]["password_env"] == "DB_WRITER_PASSWORD"
        assert brotr_dict["pool"]["database"]["host"] == "pgbouncer"
        assert brotr_dict["pool"]["limits"]["min_size"] == 1
        assert brotr_dict["pool"]["limits"]["max_size"] == 3
        assert brotr_dict["pool"]["server_settings"]["application_name"] == "monitor"

    def test_partial_override_only_min_size(self) -> None:
        brotr_dict: dict = {"pool": {"database": {"host": "pgbouncer", "user": "admin"}}}
        overrides = {"min_size": 2}
        _apply_pool_overrides(brotr_dict, overrides, "finder")

        assert brotr_dict["pool"]["database"]["user"] == "admin"
        assert brotr_dict["pool"]["limits"]["min_size"] == 2
        assert "max_size" not in brotr_dict["pool"]["limits"]
        assert brotr_dict["pool"]["server_settings"]["application_name"] == "finder"

    def test_explicit_application_name_overrides_service_name(self) -> None:
        brotr_dict: dict = {}
        overrides = {"application_name": "my_custom_app"}
        _apply_pool_overrides(brotr_dict, overrides, "monitor")
        assert brotr_dict["pool"]["server_settings"]["application_name"] == "my_custom_app"

    def test_empty_overrides_dict(self) -> None:
        brotr_dict: dict = {}
        _apply_pool_overrides(brotr_dict, {}, "seeder")
        assert brotr_dict["pool"]["server_settings"]["application_name"] == "seeder"
        assert "database" not in brotr_dict["pool"]
        assert "limits" not in brotr_dict["pool"]

    def test_empty_brotr_dict(self) -> None:
        brotr_dict: dict = {}
        overrides = {"user": "writer", "min_size": 1, "max_size": 5}
        _apply_pool_overrides(brotr_dict, overrides, "synchronizer")

        assert brotr_dict["pool"]["database"]["user"] == "writer"
        assert brotr_dict["pool"]["limits"]["min_size"] == 1
        assert brotr_dict["pool"]["limits"]["max_size"] == 5
        assert brotr_dict["pool"]["server_settings"]["application_name"] == "synchronizer"


# ============================================================================
# run_service Tests
# ============================================================================


class TestRunService:
    async def test_oneshot_success(self, mock_brotr_for_cli: Brotr) -> None:
        from bigbrotr.services.seeder import Seeder

        service_dict = {"seed": {"file_path": "nonexistent.txt"}}

        result = await run_service(
            service_name="seeder",
            service_class=Seeder,
            brotr=mock_brotr_for_cli,
            service_dict=service_dict,
            once=True,
        )

        assert result == 0

    async def test_oneshot_empty_dict(self, mock_brotr_for_cli: Brotr) -> None:
        from bigbrotr.services.seeder import Seeder

        result = await run_service(
            service_name="seeder",
            service_class=Seeder,
            brotr=mock_brotr_for_cli,
            service_dict={},
            once=True,
        )

        assert result == 0

    async def test_oneshot_failure(self, mock_brotr_for_cli: Brotr) -> None:
        from bigbrotr.services.seeder import Seeder

        service_dict = {"seed": {"file_path": "nonexistent.txt"}}

        with patch.object(Seeder, "run", AsyncMock(side_effect=Exception("Test error"))):
            result = await run_service(
                service_name="seeder",
                service_class=Seeder,
                brotr=mock_brotr_for_cli,
                service_dict=service_dict,
                once=True,
            )

        assert result == 1

    async def test_continuous_success(self, mock_brotr_for_cli: Brotr) -> None:
        from bigbrotr.services.finder import Finder

        service_dict = {
            "interval": 60.0,
            "max_consecutive_failures": 5,
            "discovery": {"enabled_sources": []},
        }

        with patch.object(Finder, "run_forever", AsyncMock()):
            result = await run_service(
                service_name="finder",
                service_class=Finder,
                brotr=mock_brotr_for_cli,
                service_dict=service_dict,
                once=False,
            )

        assert result == 0

    async def test_continuous_failure(self, mock_brotr_for_cli: Brotr) -> None:
        from bigbrotr.services.finder import Finder

        service_dict = {
            "interval": 60.0,
            "max_consecutive_failures": 5,
            "discovery": {"enabled_sources": []},
        }

        with patch.object(Finder, "run_forever", AsyncMock(side_effect=Exception("Test error"))):
            result = await run_service(
                service_name="finder",
                service_class=Finder,
                brotr=mock_brotr_for_cli,
                service_dict=service_dict,
                once=False,
            )

        assert result == 1

    async def test_continuous_starts_and_stops_metrics_server(
        self, mock_brotr_for_cli: Brotr, mock_metrics_server: MagicMock
    ) -> None:
        from bigbrotr.services.finder import Finder

        service_dict = {
            "interval": 60.0,
            "max_consecutive_failures": 5,
            "discovery": {"enabled_sources": []},
            "metrics": {"enabled": True, "host": "127.0.0.1", "port": 9999},
        }

        with (
            patch.object(Finder, "run_forever", AsyncMock()),
            patch(
                "bigbrotr.__main__.start_metrics_server",
                AsyncMock(return_value=mock_metrics_server),
            ) as mock_start,
        ):
            await run_service(
                service_name="finder",
                service_class=Finder,
                brotr=mock_brotr_for_cli,
                service_dict=service_dict,
                once=False,
            )

            mock_start.assert_called_once()
            mock_metrics_server.stop.assert_called_once()

    async def test_continuous_stops_metrics_server_on_failure(
        self, mock_brotr_for_cli: Brotr, mock_metrics_server: MagicMock
    ) -> None:
        from bigbrotr.services.finder import Finder

        service_dict = {
            "interval": 60.0,
            "max_consecutive_failures": 5,
            "discovery": {"enabled_sources": []},
            "metrics": {"enabled": True},
        }

        with (
            patch.object(Finder, "run_forever", AsyncMock(side_effect=Exception("Test error"))),
            patch(
                "bigbrotr.__main__.start_metrics_server",
                AsyncMock(return_value=mock_metrics_server),
            ),
        ):
            await run_service(
                service_name="finder",
                service_class=Finder,
                brotr=mock_brotr_for_cli,
                service_dict=service_dict,
                once=False,
            )

            mock_metrics_server.stop.assert_called_once()

    async def test_oneshot_does_not_start_metrics_server(self, mock_brotr_for_cli: Brotr) -> None:
        from bigbrotr.services.seeder import Seeder

        service_dict = {
            "seed": {"file_path": "nonexistent.txt"},
            "metrics": {"enabled": True},
        }

        with patch("bigbrotr.__main__.start_metrics_server", AsyncMock()) as mock_start:
            await run_service(
                service_name="seeder",
                service_class=Seeder,
                brotr=mock_brotr_for_cli,
                service_dict=service_dict,
                once=True,
            )

            mock_start.assert_not_called()


# ============================================================================
# Signal Handling Tests
# ============================================================================


class TestSignalHandling:
    async def test_signal_handlers_registered_via_loop(
        self, mock_brotr_for_cli: Brotr, mock_metrics_server: MagicMock
    ) -> None:
        from bigbrotr.services.finder import Finder

        service_dict = {
            "interval": 60.0,
            "max_consecutive_failures": 5,
            "discovery": {"enabled_sources": []},
        }

        registered_signals: list[signal.Signals] = []
        loop = asyncio.get_running_loop()

        def tracking_add(sig, callback, *args):
            registered_signals.append(sig)
            # Don't actually register to avoid side effects

        with (
            patch.object(Finder, "run_forever", AsyncMock()),
            patch(
                "bigbrotr.__main__.start_metrics_server",
                AsyncMock(return_value=mock_metrics_server),
            ),
            patch.object(loop, "add_signal_handler", side_effect=tracking_add),
        ):
            await run_service(
                service_name="finder",
                service_class=Finder,
                brotr=mock_brotr_for_cli,
                service_dict=service_dict,
                once=False,
            )

        assert signal.SIGINT in registered_signals
        assert signal.SIGTERM in registered_signals

    async def test_signal_handler_calls_request_shutdown(
        self, mock_brotr_for_cli: Brotr, mock_metrics_server: MagicMock
    ) -> None:
        from bigbrotr.services.finder import Finder

        service_dict = {
            "interval": 60.0,
            "max_consecutive_failures": 5,
            "discovery": {"enabled_sources": []},
        }

        captured_callbacks: list = []

        def capture_add(sig, callback, *args):
            captured_callbacks.append((sig, callback, args))

        loop = asyncio.get_running_loop()

        with (
            patch.object(Finder, "run_forever", AsyncMock()),
            patch(
                "bigbrotr.__main__.start_metrics_server",
                AsyncMock(return_value=mock_metrics_server),
            ),
            patch.object(loop, "add_signal_handler", side_effect=capture_add),
            patch.object(Finder, "request_shutdown") as mock_shutdown,
        ):
            await run_service(
                service_name="finder",
                service_class=Finder,
                brotr=mock_brotr_for_cli,
                service_dict=service_dict,
                once=False,
            )

            # Invoke one of the captured signal callbacks
            assert len(captured_callbacks) == 2
            _, callback, args = captured_callbacks[0]
            callback(*args)
            mock_shutdown.assert_called_once()


# ============================================================================
# main Tests
# ============================================================================


class TestMain:
    async def test_main_oneshot_success(self, mock_brotr_for_cli: Brotr, tmp_path: Path) -> None:
        config_file = tmp_path / "seeder.yaml"
        config_file.write_text("seed:\n  file_path: nonexistent.txt\n")

        brotr_config = tmp_path / "brotr.yaml"
        brotr_config.write_text(
            "pool:\n  database:\n    host: localhost\n    port: 5432\n"
            "    database: testdb\n    user: testuser\n"
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
        brotr_config.write_text(
            "pool:\n  database:\n    host: localhost\n    port: 5432\n"
            "    database: testdb\n    user: testuser\n"
        )

        mock_brotr = MagicMock(spec=Brotr)
        mock_brotr.__aenter__ = AsyncMock(side_effect=ConnectionError("Cannot connect"))
        mock_brotr.__aexit__ = AsyncMock()

        with (
            patch("sys.argv", ["prog", "seeder", "--brotr-config", str(brotr_config)]),
            patch("bigbrotr.__main__.Brotr.from_dict", return_value=mock_brotr),
        ):
            result = await main()

        assert result == 1

    async def test_main_keyboard_interrupt(self, mock_brotr_for_cli: Brotr, tmp_path: Path) -> None:
        brotr_config = tmp_path / "brotr.yaml"
        brotr_config.write_text(
            "pool:\n  database:\n    host: localhost\n    port: 5432\n"
            "    database: testdb\n    user: testuser\n"
        )

        with (
            patch("sys.argv", ["prog", "seeder", "--brotr-config", str(brotr_config)]),
            patch("bigbrotr.__main__.Brotr.from_dict", return_value=mock_brotr_for_cli),
            patch(
                "bigbrotr.__main__.run_service",
                AsyncMock(side_effect=KeyboardInterrupt),
            ),
        ):
            result = await main()

        assert result == 130

    async def test_main_uses_default_config_when_not_specified(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path
    ) -> None:
        brotr_config = tmp_path / "brotr.yaml"
        brotr_config.write_text(
            "pool:\n  database:\n    host: localhost\n    port: 5432\n"
            "    database: testdb\n    user: testuser\n"
        )

        captured_service_dict = None

        async def capture_run_service(*args, **kwargs):
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
        brotr_config.write_text(
            "pool:\n  database:\n    host: localhost\n    port: 5432\n"
            "    database: testdb\n    user: testuser\n"
        )

        custom_config = tmp_path / "custom_finder.yaml"
        custom_config.write_text("interval: 120.0\n")

        captured_service_dict = None

        async def capture_run_service(*args, **kwargs):
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
        brotr_config.write_text(
            "pool:\n  database:\n    host: localhost\n    port: 5432\n"
            "    database: testdb\n    user: testuser\n"
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
        brotr_config.write_text(
            "pool:\n  database:\n    host: localhost\n    port: 5432\n"
            "    database: testdb\n    user: testuser\n"
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
        brotr_config.write_text("pool:\n  database:\n    host: pgbouncer\n    database: bigbrotr\n")

        service_config = tmp_path / "monitor.yaml"
        service_config.write_text(
            "pool:\n  user: writer\n"
            "  password_env: DB_WRITER_PASSWORD  # pragma: allowlist secret\n"
            "  min_size: 1\n  max_size: 3\n"
            "metrics:\n  enabled: true\n"
        )

        captured_service_dict = None

        async def capture_run_service(*args, **kwargs):
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

        assert "pool" not in captured_service_dict
        assert captured_service_dict == {"metrics": {"enabled": True}}

        brotr_call_dict = mock_from_dict.call_args[0][0]
        assert brotr_call_dict["pool"]["database"]["user"] == "writer"
        assert brotr_call_dict["pool"]["database"]["password_env"] == "DB_WRITER_PASSWORD"
        assert brotr_call_dict["pool"]["database"]["host"] == "pgbouncer"
        assert brotr_call_dict["pool"]["limits"]["min_size"] == 1
        assert brotr_call_dict["pool"]["limits"]["max_size"] == 3
        assert brotr_call_dict["pool"]["server_settings"]["application_name"] == "monitor"

    async def test_main_auto_application_name_without_pool_overrides(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path
    ) -> None:
        brotr_config = tmp_path / "brotr.yaml"
        brotr_config.write_text("pool:\n  database:\n    host: pgbouncer\n")

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
        # _apply_pool_overrides always populates brotr_dict with application_name,
        # so from_dict is always called even when the config file is missing
        mock_from_dict.assert_called_once()
        call_dict = mock_from_dict.call_args[0][0]
        assert call_dict["pool"]["server_settings"]["application_name"] == "seeder"


# ============================================================================
# cli Tests
# ============================================================================


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
