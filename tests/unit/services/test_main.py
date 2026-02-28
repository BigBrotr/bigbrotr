"""
Unit tests for bigbrotr.__main__ CLI module.

Tests:
- parse_args argument parsing
- setup_logging configuration
- _load_yaml_dict loading
- _apply_pool_overrides merging
- run_service execution
- SERVICE_REGISTRY completeness
- Signal handling
- Metrics server integration
"""

import logging
import signal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bigbrotr.__main__ import (
    CONFIG_BASE,
    CORE_CONFIG,
    SERVICE_REGISTRY,
    ServiceEntry,
    _apply_pool_overrides,
    _load_yaml_dict,
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
    """Create a Brotr mock configured for CLI tests."""
    mock_brotr._pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]
    mock_brotr._pool._mock_connection.execute = AsyncMock()  # type: ignore[attr-defined]
    return mock_brotr


@pytest.fixture
def mock_metrics_server() -> MagicMock:
    """Create a mock metrics server."""
    server = MagicMock()
    server.stop = AsyncMock()
    return server


# ============================================================================
# Configuration Constants Tests
# ============================================================================


class TestConfigConstants:
    """Tests for configuration constants."""

    def test_config_base_path(self) -> None:
        """Test CONFIG_BASE is correctly defined."""
        assert Path("config") == CONFIG_BASE

    def test_core_config_path(self) -> None:
        """Test CORE_CONFIG is correctly defined."""
        assert Path("config/brotr.yaml") == CORE_CONFIG

    def test_config_base_is_path(self) -> None:
        """Test CONFIG_BASE is a Path object."""
        assert isinstance(CONFIG_BASE, Path)

    def test_core_config_is_path(self) -> None:
        """Test CORE_CONFIG is a Path object."""
        assert isinstance(CORE_CONFIG, Path)


# ============================================================================
# SERVICE_REGISTRY Tests
# ============================================================================


class TestServiceRegistry:
    """Tests for SERVICE_REGISTRY."""

    def test_all_services_registered(self) -> None:
        """Test all expected services are in registry."""
        expected = {
            "seeder",
            "finder",
            "validator",
            "monitor",
            "synchronizer",
            "refresher",
            "api",
            "dvm",
        }
        assert set(SERVICE_REGISTRY.keys()) == expected

    def test_service_config_paths(self) -> None:
        """Test each service has correct config path."""
        for name, (_, config_path) in SERVICE_REGISTRY.items():
            expected = CONFIG_BASE / "services" / f"{name}.yaml"
            assert config_path == expected, f"{name} config path mismatch"

    def test_service_classes_are_importable(self) -> None:
        """Test all service classes are valid."""
        from bigbrotr.services import (
            Api,
            Dvm,
            Finder,
            Monitor,
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
            "synchronizer": Synchronizer,
            "api": Api,
            "dvm": Dvm,
        }

        for name, (service_class, _) in SERVICE_REGISTRY.items():
            assert service_class == expected_classes[name]

    def test_registry_entries_are_service_entry(self) -> None:
        """Test registry entries are ServiceEntry NamedTuples."""
        for name, entry in SERVICE_REGISTRY.items():
            assert isinstance(entry, ServiceEntry), f"{name} should be a ServiceEntry"

    def test_registry_not_empty(self) -> None:
        """Test registry is not empty."""
        assert len(SERVICE_REGISTRY) > 0

    def test_service_classes_are_base_service_subclasses(self) -> None:
        """Test all service classes inherit from BaseService."""
        from bigbrotr.core.base_service import BaseService

        for name, (service_class, _) in SERVICE_REGISTRY.items():
            assert issubclass(service_class, BaseService), (
                f"{name} should be a BaseService subclass"
            )

    def test_config_paths_are_yaml_files(self) -> None:
        """Test all config paths end with .yaml."""
        for name, (_, config_path) in SERVICE_REGISTRY.items():
            assert config_path.suffix == ".yaml", f"{name} config should be .yaml file"


# ============================================================================
# parse_args Tests
# ============================================================================


class TestParseArgs:
    """Tests for parse_args function."""

    def test_service_required(self) -> None:
        """Test service argument is required."""
        with patch("sys.argv", ["prog"]), pytest.raises(SystemExit):
            parse_args()

    def test_valid_service(self) -> None:
        """Test parsing with valid service."""
        with patch("sys.argv", ["prog", "finder"]):
            args = parse_args()
            assert args.service == "finder"

    def test_invalid_service_rejected(self) -> None:
        """Test invalid service is rejected."""
        with patch("sys.argv", ["prog", "invalid"]), pytest.raises(SystemExit):
            parse_args()

    def test_all_services_accepted(self) -> None:
        """Test all registered services are accepted."""
        for service_name in SERVICE_REGISTRY:
            with patch("sys.argv", ["prog", service_name]):
                args = parse_args()
                assert args.service == service_name

    def test_config_option(self) -> None:
        """Test --config option."""
        with patch("sys.argv", ["prog", "finder", "--config", "custom/config.yaml"]):
            args = parse_args()
            assert args.config == Path("custom/config.yaml")

    def test_config_option_default_is_none(self) -> None:
        """Test --config default is None."""
        with patch("sys.argv", ["prog", "finder"]):
            args = parse_args()
            assert args.config is None

    def test_brotr_config_default(self) -> None:
        """Test --brotr-config default."""
        with patch("sys.argv", ["prog", "finder"]):
            args = parse_args()
            assert args.brotr_config == CORE_CONFIG

    def test_brotr_config_custom(self) -> None:
        """Test --brotr-config custom value."""
        with patch("sys.argv", ["prog", "finder", "--brotr-config", "custom/brotr.yaml"]):
            args = parse_args()
            assert args.brotr_config == Path("custom/brotr.yaml")

    def test_log_level_default(self) -> None:
        """Test --log-level default is INFO."""
        with patch("sys.argv", ["prog", "finder"]):
            args = parse_args()
            assert args.log_level == "INFO"

    def test_log_level_choices(self) -> None:
        """Test --log-level valid choices."""
        for level in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            with patch("sys.argv", ["prog", "finder", "--log-level", level]):
                args = parse_args()
                assert args.log_level == level

    def test_log_level_invalid(self) -> None:
        """Test --log-level invalid choice rejected."""
        with (
            patch("sys.argv", ["prog", "finder", "--log-level", "INVALID"]),
            pytest.raises(SystemExit),
        ):
            parse_args()

    def test_log_level_case_sensitive(self) -> None:
        """Test --log-level is case sensitive."""
        with (
            patch("sys.argv", ["prog", "finder", "--log-level", "debug"]),
            pytest.raises(SystemExit),
        ):
            parse_args()

    def test_once_flag_default(self) -> None:
        """Test --once flag defaults to False."""
        with patch("sys.argv", ["prog", "finder"]):
            args = parse_args()
            assert args.once is False

    def test_once_flag_enabled(self) -> None:
        """Test --once flag when provided."""
        with patch("sys.argv", ["prog", "finder", "--once"]):
            args = parse_args()
            assert args.once is True

    def test_combined_arguments(self) -> None:
        """Test parsing with all arguments combined."""
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

    def test_argument_order_doesnt_matter(self) -> None:
        """Test arguments can be in any order."""
        with patch(
            "sys.argv",
            [
                "prog",
                "--log-level",
                "DEBUG",
                "--once",
                "validator",
                "--config",
                "test.yaml",
            ],
        ):
            args = parse_args()
            assert args.service == "validator"
            assert args.log_level == "DEBUG"
            assert args.once is True
            assert args.config == Path("test.yaml")


# ============================================================================
# setup_logging Tests
# ============================================================================


class TestSetupLogging:
    """Tests for setup_logging function."""

    def _cleanup_root_handlers(self) -> None:
        """Remove handlers added by setup_logging to avoid leaking state."""
        from bigbrotr.core.logger import StructuredFormatter

        logging.root.handlers = [
            h for h in logging.root.handlers if not isinstance(h.formatter, StructuredFormatter)
        ]

    def test_debug_level(self) -> None:
        """Test DEBUG log level configuration."""
        setup_logging("DEBUG")
        assert logging.root.level == logging.DEBUG
        self._cleanup_root_handlers()

    def test_info_level(self) -> None:
        """Test INFO log level configuration."""
        setup_logging("INFO")
        assert logging.root.level == logging.INFO
        self._cleanup_root_handlers()

    def test_warning_level(self) -> None:
        """Test WARNING log level configuration."""
        setup_logging("WARNING")
        assert logging.root.level == logging.WARNING
        self._cleanup_root_handlers()

    def test_error_level(self) -> None:
        """Test ERROR log level configuration."""
        setup_logging("ERROR")
        assert logging.root.level == logging.ERROR
        self._cleanup_root_handlers()

    def test_structured_formatter_installed(self) -> None:
        """Test that StructuredFormatter is installed on the root handler."""
        from bigbrotr.core.logger import StructuredFormatter

        setup_logging("INFO")
        structured_handlers = [
            h for h in logging.root.handlers if isinstance(h.formatter, StructuredFormatter)
        ]
        assert len(structured_handlers) >= 1
        self._cleanup_root_handlers()

    def test_handler_is_stream_handler(self) -> None:
        """Test that the added handler is a StreamHandler."""
        from bigbrotr.core.logger import StructuredFormatter

        setup_logging("INFO")
        structured_handlers = [
            h for h in logging.root.handlers if isinstance(h.formatter, StructuredFormatter)
        ]
        assert all(isinstance(h, logging.StreamHandler) for h in structured_handlers)
        self._cleanup_root_handlers()


# ============================================================================
# _load_yaml_dict Tests
# ============================================================================


class TestLoadYamlDict:
    """Tests for _load_yaml_dict function."""

    def test_load_from_existing_file(self, tmp_path: Path) -> None:
        """Test loading dict from existing YAML file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("key: value\nnested:\n  a: 1\n")
        result = _load_yaml_dict(config_file)
        assert result == {"key": "value", "nested": {"a": 1}}

    def test_load_from_nonexistent_file(self, tmp_path: Path) -> None:
        """Test loading returns empty dict when file doesn't exist."""
        config_file = tmp_path / "nonexistent.yaml"
        result = _load_yaml_dict(config_file)
        assert result == {}

    def test_load_empty_file(self, tmp_path: Path) -> None:
        """Test loading returns empty dict for empty YAML file."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")
        result = _load_yaml_dict(config_file)
        assert result == {}

    def test_load_preserves_types(self, tmp_path: Path) -> None:
        """Test loading preserves YAML types correctly."""
        config_file = tmp_path / "typed.yaml"
        config_file.write_text("count: 42\nenabled: true\nratio: 3.14\nname: test\n")
        result = _load_yaml_dict(config_file)
        assert result == {"count": 42, "enabled": True, "ratio": 3.14, "name": "test"}


# ============================================================================
# _apply_pool_overrides Tests
# ============================================================================


class TestApplyPoolOverrides:
    """Tests for _apply_pool_overrides function."""

    def test_no_overrides_sets_application_name(self) -> None:
        """Test application_name is set to service_name without overrides."""
        brotr_dict: dict = {}
        _apply_pool_overrides(brotr_dict, None, "monitor")
        assert brotr_dict["pool"]["server_settings"]["application_name"] == "monitor"

    def test_no_overrides_preserves_existing_application_name(self) -> None:
        """Test existing application_name is not overwritten without overrides."""
        brotr_dict: dict = {"pool": {"server_settings": {"application_name": "custom"}}}
        _apply_pool_overrides(brotr_dict, None, "monitor")
        assert brotr_dict["pool"]["server_settings"]["application_name"] == "custom"

    def test_full_overrides(self) -> None:
        """Test all override fields are applied correctly."""
        brotr_dict: dict = {"pool": {"database": {"host": "pgbouncer"}}}
        overrides = {
            "user": "bigbrotr_writer",
            "password_env": "DB_WRITER_PASSWORD",  # pragma: allowlist secret
            "min_size": 1,
            "max_size": 3,
        }
        _apply_pool_overrides(brotr_dict, overrides, "monitor")

        assert brotr_dict["pool"]["database"]["user"] == "bigbrotr_writer"
        assert brotr_dict["pool"]["database"]["password_env"] == "DB_WRITER_PASSWORD"
        assert brotr_dict["pool"]["database"]["host"] == "pgbouncer"
        assert brotr_dict["pool"]["limits"]["min_size"] == 1
        assert brotr_dict["pool"]["limits"]["max_size"] == 3
        assert brotr_dict["pool"]["server_settings"]["application_name"] == "monitor"

    def test_partial_override_only_min_size(self) -> None:
        """Test partial override with only min_size."""
        brotr_dict: dict = {"pool": {"database": {"host": "pgbouncer", "user": "admin"}}}
        overrides = {"min_size": 2}
        _apply_pool_overrides(brotr_dict, overrides, "finder")

        assert brotr_dict["pool"]["database"]["user"] == "admin"
        assert brotr_dict["pool"]["limits"]["min_size"] == 2
        assert "max_size" not in brotr_dict["pool"]["limits"]
        assert brotr_dict["pool"]["server_settings"]["application_name"] == "finder"

    def test_explicit_application_name_overrides_service_name(self) -> None:
        """Test explicit application_name in overrides takes precedence."""
        brotr_dict: dict = {}
        overrides = {"application_name": "my_custom_app"}
        _apply_pool_overrides(brotr_dict, overrides, "monitor")
        assert brotr_dict["pool"]["server_settings"]["application_name"] == "my_custom_app"

    def test_empty_overrides_dict(self) -> None:
        """Test empty overrides dict behaves like None."""
        brotr_dict: dict = {}
        _apply_pool_overrides(brotr_dict, {}, "seeder")
        assert brotr_dict["pool"]["server_settings"]["application_name"] == "seeder"
        assert "database" not in brotr_dict["pool"]
        assert "limits" not in brotr_dict["pool"]

    def test_empty_brotr_dict(self) -> None:
        """Test overrides work with empty brotr_dict."""
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
    """Tests for run_service function."""

    async def test_oneshot_service_success(self, mock_brotr_for_cli: Brotr) -> None:
        """Test oneshot service completes successfully."""
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

    async def test_oneshot_service_empty_dict(self, mock_brotr_for_cli: Brotr) -> None:
        """Test oneshot service with empty dict uses defaults."""
        from bigbrotr.services.seeder import Seeder

        result = await run_service(
            service_name="seeder",
            service_class=Seeder,
            brotr=mock_brotr_for_cli,
            service_dict={},
            once=True,
        )

        assert result == 0

    async def test_oneshot_service_failure(self, mock_brotr_for_cli: Brotr) -> None:
        """Test oneshot service failure returns 1."""
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

    async def test_continuous_service_success(self, mock_brotr_for_cli: Brotr) -> None:
        """Test continuous service with once=False runs via run_forever."""
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

    async def test_continuous_service_failure(self, mock_brotr_for_cli: Brotr) -> None:
        """Test continuous service failure returns 1."""
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

    async def test_continuous_service_starts_metrics_server(
        self, mock_brotr_for_cli: Brotr, mock_metrics_server: MagicMock
    ) -> None:
        """Test continuous service starts metrics server."""
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

    async def test_continuous_service_stops_metrics_server_on_failure(
        self, mock_brotr_for_cli: Brotr, mock_metrics_server: MagicMock
    ) -> None:
        """Test metrics server is stopped even on service failure."""
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
        """Test oneshot mode does not start metrics server."""
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
    """Tests for signal handling in run_service."""

    async def test_signal_handler_registered(
        self, mock_brotr_for_cli: Brotr, mock_metrics_server: MagicMock
    ) -> None:
        """Test signal handlers are registered for continuous mode."""
        from bigbrotr.services.finder import Finder

        service_dict = {
            "interval": 60.0,
            "max_consecutive_failures": 5,
            "discovery": {"enabled_sources": []},
        }

        with (
            patch.object(Finder, "run_forever", AsyncMock()),
            patch(
                "bigbrotr.__main__.start_metrics_server",
                AsyncMock(return_value=mock_metrics_server),
            ),
            patch("signal.signal") as mock_signal,
        ):
            await run_service(
                service_name="finder",
                service_class=Finder,
                brotr=mock_brotr_for_cli,
                service_dict=service_dict,
                once=False,
            )

            # Check SIGINT and SIGTERM handlers were registered
            sigint_call = any(call[0][0] == signal.SIGINT for call in mock_signal.call_args_list)
            sigterm_call = any(call[0][0] == signal.SIGTERM for call in mock_signal.call_args_list)
            assert sigint_call, "SIGINT handler should be registered"
            assert sigterm_call, "SIGTERM handler should be registered"


# ============================================================================
# main Tests
# ============================================================================


class TestMain:
    """Tests for main function."""

    async def test_main_with_seeder(self, mock_brotr_for_cli: Brotr, tmp_path: Path) -> None:
        """Test main function with seeder service."""
        config_file = tmp_path / "seeder.yaml"
        config_file.write_text("""
seed:
  file_path: nonexistent.txt
""")

        brotr_config = tmp_path / "brotr.yaml"
        brotr_config.write_text("""
pool:
  database:
    host: localhost
    port: 5432
    database: testdb
    user: testuser
""")

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
        """Test main handles connection error."""
        brotr_config = tmp_path / "brotr.yaml"
        brotr_config.write_text("""
pool:
  database:
    host: localhost
    port: 5432
    database: testdb
    user: testuser
""")

        mock_brotr = MagicMock(spec=Brotr)
        mock_brotr.__aenter__ = AsyncMock(side_effect=ConnectionError("Cannot connect"))
        mock_brotr.__aexit__ = AsyncMock()

        with (
            patch(
                "sys.argv",
                [
                    "prog",
                    "seeder",
                    "--brotr-config",
                    str(brotr_config),
                ],
            ),
            patch("bigbrotr.__main__.Brotr.from_dict", return_value=mock_brotr),
        ):
            result = await main()

        assert result == 1

    async def test_main_keyboard_interrupt(self, mock_brotr_for_cli: Brotr, tmp_path: Path) -> None:
        """Test main handles KeyboardInterrupt."""
        brotr_config = tmp_path / "brotr.yaml"
        brotr_config.write_text("""
pool:
  database:
    host: localhost
    port: 5432
    database: testdb
    user: testuser
""")

        with (
            patch(
                "sys.argv",
                [
                    "prog",
                    "seeder",
                    "--brotr-config",
                    str(brotr_config),
                ],
            ),
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
        """Test main uses default config path when --config not specified."""
        brotr_config = tmp_path / "brotr.yaml"
        brotr_config.write_text("""
pool:
  database:
    host: localhost
    port: 5432
    database: testdb
    user: testuser
""")

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
                    "--brotr-config",
                    str(brotr_config),
                    "--once",
                ],
            ),
            patch("bigbrotr.__main__.Brotr.from_dict", return_value=mock_brotr_for_cli),
            patch("bigbrotr.__main__.run_service", AsyncMock(side_effect=capture_run_service)),
        ):
            await main()

        # Default config file doesn't exist in tmp, so service_dict should be empty
        assert captured_service_dict == {}

    async def test_main_uses_custom_config_when_specified(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path
    ) -> None:
        """Test main uses custom config path when --config specified."""
        brotr_config = tmp_path / "brotr.yaml"
        brotr_config.write_text("""
pool:
  database:
    host: localhost
    port: 5432
    database: testdb
    user: testuser
""")

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
        """Test main calls setup_logging with correct level."""
        brotr_config = tmp_path / "brotr.yaml"
        brotr_config.write_text("""
pool:
  database:
    host: localhost
    port: 5432
    database: testdb
    user: testuser
""")

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
        """Test main passes correct service class to run_service."""
        from bigbrotr.services import (
            Finder,
            Monitor,
            Refresher,
            Seeder,
            Synchronizer,
            Validator,
        )

        brotr_config = tmp_path / "brotr.yaml"
        brotr_config.write_text("""
pool:
  database:
    host: localhost
    port: 5432
    database: testdb
    user: testuser
""")

        expected_classes = {
            "seeder": Seeder,
            "finder": Finder,
            "validator": Validator,
            "monitor": Monitor,
            "refresher": Refresher,
            "synchronizer": Synchronizer,
        }

        # Test a representative service to verify class lookup works
        mock_run = AsyncMock(return_value=0)
        with (
            patch(
                "sys.argv",
                [
                    "prog",
                    "monitor",
                    "--brotr-config",
                    str(brotr_config),
                    "--once",
                ],
            ),
            patch("bigbrotr.__main__.Brotr.from_dict", return_value=mock_brotr_for_cli),
            patch("bigbrotr.__main__.run_service", mock_run),
        ):
            result = await main()
            assert result == 0
            mock_run.assert_called_once()

            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["service_name"] == "monitor"
            assert call_kwargs["service_class"] == expected_classes["monitor"]

    def test_registry_classes_match_imports(self) -> None:
        """Test SERVICE_REGISTRY has correct classes for all services."""
        from bigbrotr.services import (
            Api,
            Dvm,
            Finder,
            Monitor,
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
            "synchronizer": Synchronizer,
            "api": Api,
            "dvm": Dvm,
        }

        for service_name, (service_class, _) in SERVICE_REGISTRY.items():
            assert service_class == expected_classes[service_name], (
                f"Registry class mismatch for {service_name}"
            )

    async def test_main_extracts_pool_overrides(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path
    ) -> None:
        """Test main extracts pool section from service config and applies overrides."""
        brotr_config = tmp_path / "brotr.yaml"
        brotr_config.write_text("""
pool:
  database:
    host: pgbouncer
    database: bigbrotr
""")

        service_config = tmp_path / "monitor.yaml"
        service_config.write_text("""
pool:
  user: bigbrotr_writer
  password_env: DB_WRITER_PASSWORD  # pragma: allowlist secret
  min_size: 1
  max_size: 3
metrics:
  enabled: true
""")

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

        # pool section should be stripped from service_dict
        assert "pool" not in captured_service_dict
        assert captured_service_dict == {"metrics": {"enabled": True}}

        # Brotr.from_dict should receive merged config
        brotr_call_dict = mock_from_dict.call_args[0][0]
        assert brotr_call_dict["pool"]["database"]["user"] == "bigbrotr_writer"
        assert brotr_call_dict["pool"]["database"]["password_env"] == "DB_WRITER_PASSWORD"
        assert brotr_call_dict["pool"]["database"]["host"] == "pgbouncer"
        assert brotr_call_dict["pool"]["limits"]["min_size"] == 1
        assert brotr_call_dict["pool"]["limits"]["max_size"] == 3
        assert brotr_call_dict["pool"]["server_settings"]["application_name"] == "monitor"

    async def test_main_auto_application_name_without_pool_overrides(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path
    ) -> None:
        """Test application_name is set to service name even without pool overrides."""
        brotr_config = tmp_path / "brotr.yaml"
        brotr_config.write_text("""
pool:
  database:
    host: pgbouncer
""")

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


# ============================================================================
# Integration Tests
# ============================================================================


class TestCLIIntegration:
    """Integration tests for CLI module."""

    async def test_full_workflow_seeder_oneshot(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path
    ) -> None:
        """Test full workflow: parse args -> load config -> run service (oneshot)."""
        config_file = tmp_path / "seeder.yaml"
        config_file.write_text("""
seed:
  file_path: nonexistent.txt
""")

        brotr_config = tmp_path / "brotr.yaml"
        brotr_config.write_text("""
pool:
  database:
    host: localhost
    port: 5432
    database: testdb
    user: testuser
""")

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
                    "--log-level",
                    "ERROR",
                    "--once",
                ],
            ),
            patch("bigbrotr.__main__.Brotr.from_dict", return_value=mock_brotr_for_cli),
        ):
            result = await main()

        assert result == 0

    def test_argument_help_text(self) -> None:
        """Test help text is available."""
        import io

        with (
            patch("sys.argv", ["prog", "--help"]),
            pytest.raises(SystemExit) as exc_info,
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            parse_args()

        assert exc_info.value.code == 0
