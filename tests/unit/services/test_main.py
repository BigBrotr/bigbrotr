"""
Unit tests for services.__main__ CLI module.

Tests:
- parse_args argument parsing
- setup_logging configuration
- load_brotr loading
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

from core.brotr import Brotr
from services.__main__ import (
    CORE_CONFIG,
    SERVICE_REGISTRY,
    YAML_BASE,
    load_brotr,
    main,
    parse_args,
    run_service,
    setup_logging,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_brotr_for_cli(mock_brotr: Brotr) -> Brotr:
    """Create a Brotr mock configured for CLI tests."""
    mock_brotr.pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]
    mock_brotr.pool._mock_connection.execute = AsyncMock()  # type: ignore[attr-defined]
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

    def test_yaml_base_path(self) -> None:
        """Test YAML_BASE is correctly defined."""
        assert Path("yaml") == YAML_BASE

    def test_core_config_path(self) -> None:
        """Test CORE_CONFIG is correctly defined."""
        assert Path("yaml/core/brotr.yaml") == CORE_CONFIG

    def test_yaml_base_is_path(self) -> None:
        """Test YAML_BASE is a Path object."""
        assert isinstance(YAML_BASE, Path)

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
        expected = {"seeder", "finder", "validator", "monitor", "synchronizer"}
        assert set(SERVICE_REGISTRY.keys()) == expected

    def test_service_config_paths(self) -> None:
        """Test each service has correct config path."""
        for name, (_, config_path) in SERVICE_REGISTRY.items():
            expected = YAML_BASE / "services" / f"{name}.yaml"
            assert config_path == expected, f"{name} config path mismatch"

    def test_service_classes_are_importable(self) -> None:
        """Test all service classes are valid."""
        from services import Finder, Monitor, Seeder, Synchronizer, Validator

        expected_classes = {
            "seeder": Seeder,
            "finder": Finder,
            "validator": Validator,
            "monitor": Monitor,
            "synchronizer": Synchronizer,
        }

        for name, (service_class, _) in SERVICE_REGISTRY.items():
            assert service_class == expected_classes[name]

    def test_registry_is_two_tuple(self) -> None:
        """Test registry entries are 2-tuples (class, config_path)."""
        for name, entry in SERVICE_REGISTRY.items():
            assert len(entry) == 2, f"{name} should be 2-tuple (class, config_path)"

    def test_registry_not_empty(self) -> None:
        """Test registry is not empty."""
        assert len(SERVICE_REGISTRY) > 0

    def test_service_classes_are_base_service_subclasses(self) -> None:
        """Test all service classes inherit from BaseService."""
        from core.service import BaseService

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

    def test_debug_level(self) -> None:
        """Test DEBUG log level configuration."""
        with patch("logging.basicConfig") as mock_config:
            setup_logging("DEBUG")
            mock_config.assert_called_once()
            call_kwargs = mock_config.call_args[1]
            assert call_kwargs["level"] == logging.DEBUG

    def test_info_level(self) -> None:
        """Test INFO log level configuration."""
        with patch("logging.basicConfig") as mock_config:
            setup_logging("INFO")
            mock_config.assert_called_once()
            call_kwargs = mock_config.call_args[1]
            assert call_kwargs["level"] == logging.INFO

    def test_warning_level(self) -> None:
        """Test WARNING log level configuration."""
        with patch("logging.basicConfig") as mock_config:
            setup_logging("WARNING")
            mock_config.assert_called_once()
            call_kwargs = mock_config.call_args[1]
            assert call_kwargs["level"] == logging.WARNING

    def test_error_level(self) -> None:
        """Test ERROR log level configuration."""
        with patch("logging.basicConfig") as mock_config:
            setup_logging("ERROR")
            mock_config.assert_called_once()
            call_kwargs = mock_config.call_args[1]
            assert call_kwargs["level"] == logging.ERROR

    def test_format_configured(self) -> None:
        """Test log format is configured."""
        with patch("logging.basicConfig") as mock_config:
            setup_logging("INFO")
            call_kwargs = mock_config.call_args[1]
            assert "format" in call_kwargs
            assert "datefmt" in call_kwargs

    def test_format_includes_timestamp(self) -> None:
        """Test log format includes timestamp placeholder."""
        with patch("logging.basicConfig") as mock_config:
            setup_logging("INFO")
            call_kwargs = mock_config.call_args[1]
            assert "asctime" in call_kwargs["format"]

    def test_format_includes_level(self) -> None:
        """Test log format includes level placeholder."""
        with patch("logging.basicConfig") as mock_config:
            setup_logging("INFO")
            call_kwargs = mock_config.call_args[1]
            assert "levelname" in call_kwargs["format"]

    def test_date_format_configured(self) -> None:
        """Test date format is properly configured."""
        with patch("logging.basicConfig") as mock_config:
            setup_logging("INFO")
            call_kwargs = mock_config.call_args[1]
            # Date format should be ISO-like
            assert call_kwargs["datefmt"] == "%Y-%m-%d %H:%M:%S"


# ============================================================================
# load_brotr Tests
# ============================================================================


class TestLoadBrotr:
    """Tests for load_brotr function."""

    def test_load_from_existing_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading Brotr from existing config file."""
        monkeypatch.setenv("DB_PASSWORD", "testpass")
        config_file = tmp_path / "brotr.yaml"
        config_file.write_text("""
pool:
  database:
    host: localhost
    port: 5432
    database: testdb
    user: testuser
""")
        brotr = load_brotr(config_file)
        assert isinstance(brotr, Brotr)
        assert brotr.pool.config.database.host == "localhost"

    def test_load_from_nonexistent_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test loading Brotr when config file doesn't exist."""
        monkeypatch.setenv("DB_PASSWORD", "testpass")
        config_file = tmp_path / "nonexistent.yaml"
        brotr = load_brotr(config_file)
        assert isinstance(brotr, Brotr)

    def test_load_brotr_returns_brotr_instance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test load_brotr always returns a Brotr instance."""
        monkeypatch.setenv("DB_PASSWORD", "testpass")
        config_file = tmp_path / "nonexistent.yaml"
        result = load_brotr(config_file)
        assert isinstance(result, Brotr)

    def test_load_brotr_with_custom_pool_settings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test loading Brotr with custom pool settings."""
        monkeypatch.setenv("DB_PASSWORD", "testpass")
        config_file = tmp_path / "brotr.yaml"
        config_file.write_text("""
pool:
  database:
    host: customhost
    port: 5433
    database: customdb
    user: customuser
  pool:
    min_size: 5
    max_size: 20
""")
        brotr = load_brotr(config_file)
        assert brotr.pool.config.database.host == "customhost"
        assert brotr.pool.config.database.port == 5433
        assert brotr.pool.config.database.database == "customdb"


# ============================================================================
# run_service Tests
# ============================================================================


class TestRunService:
    """Tests for run_service function."""

    @pytest.mark.asyncio
    async def test_oneshot_service_success(self, mock_brotr_for_cli: Brotr, tmp_path: Path) -> None:
        """Test oneshot service completes successfully."""
        from services.seeder import Seeder

        # Create a minimal config file
        config_file = tmp_path / "seeder.yaml"
        config_file.write_text("""
seed:
  file_path: nonexistent.txt
""")

        result = await run_service(
            service_name="seeder",
            service_class=Seeder,
            brotr=mock_brotr_for_cli,
            config_path=config_file,
            once=True,
        )

        assert result == 0

    @pytest.mark.asyncio
    async def test_oneshot_service_config_not_found(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path
    ) -> None:
        """Test oneshot service with missing config uses defaults."""
        from services.seeder import Seeder

        config_file = tmp_path / "nonexistent.yaml"

        result = await run_service(
            service_name="seeder",
            service_class=Seeder,
            brotr=mock_brotr_for_cli,
            config_path=config_file,
            once=True,
        )

        assert result == 0

    @pytest.mark.asyncio
    async def test_oneshot_service_failure(self, mock_brotr_for_cli: Brotr, tmp_path: Path) -> None:
        """Test oneshot service failure returns 1."""
        from services.seeder import Seeder

        config_file = tmp_path / "seeder.yaml"
        config_file.write_text("""
seed:
  file_path: nonexistent.txt
""")

        # Patch the run method to raise an exception
        with patch.object(Seeder, "run", AsyncMock(side_effect=Exception("Test error"))):
            result = await run_service(
                service_name="seeder",
                service_class=Seeder,
                brotr=mock_brotr_for_cli,
                config_path=config_file,
                once=True,
            )

        assert result == 1

    @pytest.mark.asyncio
    async def test_continuous_service_success(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path
    ) -> None:
        """Test continuous service with once=False runs via run_forever."""
        from services.finder import Finder

        config_file = tmp_path / "finder.yaml"
        config_file.write_text("""
interval: 60.0
max_consecutive_failures: 5
discovery:
  enabled_sources: []
""")

        # Mock run_forever to immediately return
        with patch.object(Finder, "run_forever", AsyncMock()):
            result = await run_service(
                service_name="finder",
                service_class=Finder,
                brotr=mock_brotr_for_cli,
                config_path=config_file,
                once=False,
            )

        assert result == 0

    @pytest.mark.asyncio
    async def test_continuous_service_failure(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path
    ) -> None:
        """Test continuous service failure returns 1."""
        from services.finder import Finder

        config_file = tmp_path / "finder.yaml"
        config_file.write_text("""
interval: 60.0
max_consecutive_failures: 5
discovery:
  enabled_sources: []
""")

        # Mock run_forever to raise an exception
        with patch.object(Finder, "run_forever", AsyncMock(side_effect=Exception("Test error"))):
            result = await run_service(
                service_name="finder",
                service_class=Finder,
                brotr=mock_brotr_for_cli,
                config_path=config_file,
                once=False,
            )

        assert result == 1

    @pytest.mark.asyncio
    async def test_continuous_service_starts_metrics_server(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path, mock_metrics_server: MagicMock
    ) -> None:
        """Test continuous service starts metrics server."""
        from services.finder import Finder

        config_file = tmp_path / "finder.yaml"
        config_file.write_text("""
interval: 60.0
max_consecutive_failures: 5
discovery:
  enabled_sources: []
metrics:
  enabled: true
  host: "127.0.0.1"
  port: 9999
""")

        with (
            patch.object(Finder, "run_forever", AsyncMock()),
            patch(
                "services.__main__.start_metrics_server",
                AsyncMock(return_value=mock_metrics_server),
            ) as mock_start,
        ):
            await run_service(
                service_name="finder",
                service_class=Finder,
                brotr=mock_brotr_for_cli,
                config_path=config_file,
                once=False,
            )

            mock_start.assert_called_once()
            mock_metrics_server.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_continuous_service_stops_metrics_server_on_failure(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path, mock_metrics_server: MagicMock
    ) -> None:
        """Test metrics server is stopped even on service failure."""
        from services.finder import Finder

        config_file = tmp_path / "finder.yaml"
        config_file.write_text("""
interval: 60.0
max_consecutive_failures: 5
discovery:
  enabled_sources: []
metrics:
  enabled: true
""")

        with (
            patch.object(Finder, "run_forever", AsyncMock(side_effect=Exception("Test error"))),
            patch(
                "services.__main__.start_metrics_server",
                AsyncMock(return_value=mock_metrics_server),
            ),
        ):
            await run_service(
                service_name="finder",
                service_class=Finder,
                brotr=mock_brotr_for_cli,
                config_path=config_file,
                once=False,
            )

            mock_metrics_server.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_oneshot_does_not_start_metrics_server(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path
    ) -> None:
        """Test oneshot mode does not start metrics server."""
        from services.seeder import Seeder

        config_file = tmp_path / "seeder.yaml"
        config_file.write_text("""
seed:
  file_path: nonexistent.txt
metrics:
  enabled: true
""")

        with patch("services.__main__.start_metrics_server", AsyncMock()) as mock_start:
            await run_service(
                service_name="seeder",
                service_class=Seeder,
                brotr=mock_brotr_for_cli,
                config_path=config_file,
                once=True,
            )

            mock_start.assert_not_called()


# ============================================================================
# Signal Handling Tests
# ============================================================================


class TestSignalHandling:
    """Tests for signal handling in run_service."""

    @pytest.mark.asyncio
    async def test_signal_handler_registered(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path, mock_metrics_server: MagicMock
    ) -> None:
        """Test signal handlers are registered for continuous mode."""
        from services.finder import Finder

        config_file = tmp_path / "finder.yaml"
        config_file.write_text("""
interval: 60.0
max_consecutive_failures: 5
discovery:
  enabled_sources: []
""")

        with (
            patch.object(Finder, "run_forever", AsyncMock()),
            patch(
                "services.__main__.start_metrics_server",
                AsyncMock(return_value=mock_metrics_server),
            ),
            patch("signal.signal") as mock_signal,
        ):
            await run_service(
                service_name="finder",
                service_class=Finder,
                brotr=mock_brotr_for_cli,
                config_path=config_file,
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

    @pytest.mark.asyncio
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
            patch("services.__main__.load_brotr", return_value=mock_brotr_for_cli),
            patch("services.__main__.run_service", AsyncMock(return_value=0)),
        ):
            result = await main()

        assert result == 0

    @pytest.mark.asyncio
    async def test_main_connection_error(self, tmp_path: Path) -> None:
        """Test main handles connection error."""
        brotr_config = tmp_path / "brotr.yaml"
        brotr_config.write_text("""
pool:
  host: localhost
  port: 5432
  database: testdb
  user: testuser
""")

        mock_brotr = MagicMock(spec=Brotr)
        mock_pool = MagicMock()
        mock_pool.__aenter__ = AsyncMock(side_effect=ConnectionError("Cannot connect"))
        mock_pool.__aexit__ = AsyncMock()
        mock_brotr.pool = mock_pool

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
            patch("services.__main__.load_brotr", return_value=mock_brotr),
        ):
            result = await main()

        assert result == 1

    @pytest.mark.asyncio
    async def test_main_keyboard_interrupt(self, mock_brotr_for_cli: Brotr, tmp_path: Path) -> None:
        """Test main handles KeyboardInterrupt."""
        brotr_config = tmp_path / "brotr.yaml"
        brotr_config.write_text("""
pool:
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
            patch("services.__main__.load_brotr", return_value=mock_brotr_for_cli),
            patch(
                "services.__main__.run_service",
                AsyncMock(side_effect=KeyboardInterrupt),
            ),
        ):
            result = await main()

        assert result == 130

    @pytest.mark.asyncio
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

        captured_config_path = None

        async def capture_run_service(*args, **kwargs):
            nonlocal captured_config_path
            captured_config_path = kwargs.get("config_path")
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
            patch("services.__main__.load_brotr", return_value=mock_brotr_for_cli),
            patch("services.__main__.run_service", AsyncMock(side_effect=capture_run_service)),
        ):
            await main()

        expected_path = YAML_BASE / "services" / "finder.yaml"
        assert captured_config_path == expected_path

    @pytest.mark.asyncio
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
        custom_config.write_text("interval: 120.0")

        captured_config_path = None

        async def capture_run_service(*args, **kwargs):
            nonlocal captured_config_path
            captured_config_path = kwargs.get("config_path")
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
            patch("services.__main__.load_brotr", return_value=mock_brotr_for_cli),
            patch("services.__main__.run_service", AsyncMock(side_effect=capture_run_service)),
        ):
            await main()

        assert captured_config_path == custom_config

    @pytest.mark.asyncio
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
            patch("services.__main__.load_brotr", return_value=mock_brotr_for_cli),
            patch("services.__main__.run_service", AsyncMock(return_value=0)),
            patch("services.__main__.setup_logging") as mock_setup,
        ):
            await main()

        mock_setup.assert_called_once_with("DEBUG")

    @pytest.mark.asyncio
    async def test_main_passes_correct_service_class(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path
    ) -> None:
        """Test main passes correct service class to run_service."""
        from services import Finder, Monitor, Seeder, Synchronizer, Validator

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
            patch("services.__main__.load_brotr", return_value=mock_brotr_for_cli),
            patch("services.__main__.run_service", mock_run),
        ):
            result = await main()
            assert result == 0
            mock_run.assert_called_once()

            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["service_name"] == "monitor"
            assert call_kwargs["service_class"] == expected_classes["monitor"]

    def test_registry_classes_match_imports(self) -> None:
        """Test SERVICE_REGISTRY has correct classes for all services."""
        from services import Finder, Monitor, Seeder, Synchronizer, Validator

        expected_classes = {
            "seeder": Seeder,
            "finder": Finder,
            "validator": Validator,
            "monitor": Monitor,
            "synchronizer": Synchronizer,
        }

        for service_name, (service_class, _) in SERVICE_REGISTRY.items():
            assert service_class == expected_classes[service_name], (
                f"Registry class mismatch for {service_name}"
            )


# ============================================================================
# Integration Tests
# ============================================================================


class TestCLIIntegration:
    """Integration tests for CLI module."""

    @pytest.mark.asyncio
    async def test_full_workflow_seeder_oneshot(
        self, mock_brotr_for_cli: Brotr, tmp_path: Path
    ) -> None:
        """Test full workflow: parse args -> load brotr -> run service (oneshot)."""
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
            patch("services.__main__.load_brotr", return_value=mock_brotr_for_cli),
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
