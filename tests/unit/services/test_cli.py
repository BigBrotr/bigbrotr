"""
Unit tests for services.__main__ CLI module.

Tests:
- parse_args argument parsing
- setup_logging configuration
- load_brotr loading
- run_service execution
- SERVICE_REGISTRY completeness
"""

import logging
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


# ============================================================================
# SERVICE_REGISTRY Tests
# ============================================================================


class TestServiceRegistry:
    """Tests for SERVICE_REGISTRY."""

    def test_all_services_registered(self) -> None:
        """Test all expected services are in registry."""
        expected = {"seeder", "finder", "validator", "monitor", "synchronizer"}
        assert set(SERVICE_REGISTRY.keys()) == expected

    def test_seeder_is_oneshot(self) -> None:
        """Test seeder is marked as oneshot."""
        _, _, is_oneshot = SERVICE_REGISTRY["seeder"]
        assert is_oneshot is True

    def test_continuous_services_not_oneshot(self) -> None:
        """Test continuous services are not oneshot."""
        for name in ["finder", "validator", "monitor", "synchronizer"]:
            _, _, is_oneshot = SERVICE_REGISTRY[name]
            assert is_oneshot is False, f"{name} should not be oneshot"

    def test_service_config_paths(self) -> None:
        """Test each service has correct config path."""
        for name, (_, config_path, _) in SERVICE_REGISTRY.items():
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

        for name, (service_class, _, _) in SERVICE_REGISTRY.items():
            assert service_class == expected_classes[name]


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
            is_oneshot=True,
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
            is_oneshot=True,
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
                is_oneshot=True,
            )

        assert result == 1


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

        # Mock run_service to avoid complex service instantiation
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
