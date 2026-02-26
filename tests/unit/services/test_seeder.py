"""
Unit tests for services.seeder module.

Tests:
- Configuration models (SeedConfig, SeederConfig)
- Seeder service initialization
- Relay seeding from file
- Parse seed file functionality
- Batch processing logic
- Error handling
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from bigbrotr.core.brotr import Brotr, BrotrConfig
from bigbrotr.services.seeder import (
    SeedConfig,
    Seeder,
    SeederConfig,
)
from bigbrotr.services.seeder.utils import parse_seed_file


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_seeder_brotr(mock_brotr: Brotr) -> Brotr:
    """Create a Brotr mock configured for seeder tests."""
    # Default successful responses
    mock_brotr._pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]
    mock_brotr._pool._mock_connection.execute = AsyncMock()  # type: ignore[attr-defined]

    # Setup config with batch settings
    mock_batch_config = MagicMock()
    mock_batch_config.max_size = 100
    mock_config = MagicMock(spec=BrotrConfig)
    mock_config.batch = mock_batch_config
    mock_config.timeouts = MagicMock()
    mock_config.timeouts.query = 30.0
    mock_brotr._config = mock_config

    return mock_brotr


# ============================================================================
# SeedConfig Tests
# ============================================================================


class TestSeedConfig:
    """Tests for SeedConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default seed configuration."""
        config = SeedConfig()

        assert config.file_path == "static/seed_relays.txt"
        assert config.to_validate is True

    def test_custom_values(self) -> None:
        """Test custom seed configuration."""
        config = SeedConfig(file_path="custom/path.txt", to_validate=False)

        assert config.file_path == "custom/path.txt"
        assert config.to_validate is False

    def test_file_path_accepts_any_string(self) -> None:
        """Test file_path accepts any string value."""
        config = SeedConfig(file_path="/absolute/path/to/relays.txt")
        assert config.file_path == "/absolute/path/to/relays.txt"

        config2 = SeedConfig(file_path="relative/path.txt")
        assert config2.file_path == "relative/path.txt"

    def test_to_validate_boolean(self) -> None:
        """Test to_validate must be boolean."""
        config_true = SeedConfig(to_validate=True)
        assert config_true.to_validate is True

        config_false = SeedConfig(to_validate=False)
        assert config_false.to_validate is False


# ============================================================================
# SeederConfig Tests
# ============================================================================


class TestSeederConfig:
    """Tests for SeederConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default configuration (inherits from BaseServiceConfig)."""
        config = SeederConfig()

        assert config.seed.file_path == "static/seed_relays.txt"
        assert config.seed.to_validate is True
        assert config.interval == 300.0  # BaseServiceConfig default
        assert config.max_consecutive_failures == 5  # BaseServiceConfig default

    def test_custom_nested_config(self) -> None:
        """Test custom nested configuration."""
        config = SeederConfig(
            seed=SeedConfig(file_path="custom/path.txt", to_validate=False),
        )

        assert config.seed.file_path == "custom/path.txt"
        assert config.seed.to_validate is False

    def test_interval_from_base_config(self) -> None:
        """Test interval can be customized."""
        config = SeederConfig(interval=600.0)
        assert config.interval == 600.0

    def test_max_consecutive_failures_from_base_config(self) -> None:
        """Test max_consecutive_failures can be customized."""
        config = SeederConfig(max_consecutive_failures=10)
        assert config.max_consecutive_failures == 10

    def test_metrics_config_from_base(self) -> None:
        """Test metrics config is inherited from base."""
        config = SeederConfig()
        assert hasattr(config, "metrics")
        assert config.metrics.enabled is False  # Default

    def test_from_dict_nested(self) -> None:
        """Test creating config from dictionary."""
        data = {
            "seed": {"file_path": "test.txt", "to_validate": False},
            "interval": 120.0,
        }
        config = SeederConfig(**data)
        assert config.seed.file_path == "test.txt"
        assert config.interval == 120.0


# ============================================================================
# Seeder Initialization Tests
# ============================================================================


class TestSeederInit:
    """Tests for Seeder initialization."""

    def test_init_with_defaults(self, mock_seeder_brotr: Brotr) -> None:
        """Test initialization with default config."""
        seeder = Seeder(brotr=mock_seeder_brotr)

        assert seeder._brotr is mock_seeder_brotr
        assert seeder.SERVICE_NAME == "seeder"
        assert seeder.config.seed.file_path == "static/seed_relays.txt"

    def test_init_with_custom_config(self, mock_seeder_brotr: Brotr) -> None:
        """Test initialization with custom config."""
        config = SeederConfig(
            seed=SeedConfig(file_path="custom/path.txt"),
        )
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        assert seeder.config.seed.file_path == "custom/path.txt"

    def test_from_dict(self, mock_seeder_brotr: Brotr) -> None:
        """Test factory method from_dict."""
        data = {
            "seed": {"file_path": "custom/path.txt", "to_validate": False},
        }
        seeder = Seeder.from_dict(data, brotr=mock_seeder_brotr)

        assert seeder.config.seed.file_path == "custom/path.txt"
        assert seeder.config.seed.to_validate is False

    def test_service_name_class_attribute(self, mock_seeder_brotr: Brotr) -> None:
        """Test SERVICE_NAME class attribute."""
        assert Seeder.SERVICE_NAME == "seeder"
        seeder = Seeder(brotr=mock_seeder_brotr)
        assert seeder.SERVICE_NAME == "seeder"

    def test_config_class_attribute(self, mock_seeder_brotr: Brotr) -> None:
        """Test CONFIG_CLASS class attribute."""
        assert SeederConfig == Seeder.CONFIG_CLASS

    def test_logger_initialized(self, mock_seeder_brotr: Brotr) -> None:
        """Test logger is initialized."""
        seeder = Seeder(brotr=mock_seeder_brotr)
        assert seeder._logger is not None


# ============================================================================
# Seed Relays Tests
# ============================================================================


class TestSeedRelays:
    """Tests for relay seeding."""

    async def test_seed_file_not_found(self, mock_seeder_brotr: Brotr) -> None:
        """Test seeding with non-existent file."""
        config = SeederConfig(seed=SeedConfig(file_path="nonexistent/file.txt"))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder.seed()

    async def test_seed_success_as_candidates(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Seed relays as validation candidates (to_validate=True)."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay1.example.com\nwss://relay2.example.com\n")

        mock_seeder_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {"url": "wss://relay1.example.com"},
                {"url": "wss://relay2.example.com"},
            ]
        )
        mock_seeder_brotr.upsert_service_state = AsyncMock(return_value=2)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file), to_validate=True))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder.seed()

        mock_seeder_brotr.upsert_service_state.assert_called()

    async def test_seed_success_as_relays(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Seed relays directly into relays table (to_validate=False)."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay1.example.com\nwss://relay2.example.com\n")

        mock_seeder_brotr.insert_relay = AsyncMock(return_value=2)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file), to_validate=False))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder.seed()

        mock_seeder_brotr.insert_relay.assert_called()

    async def test_seed_skips_comments_and_empty(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test seeding skips comments and empty lines."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("# Comment\n\nwss://relay.example.com\n# Another comment\n")

        mock_seeder_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"url": "wss://relay.example.com"}]
        )
        mock_seeder_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder.seed()

    async def test_seed_skips_invalid_urls(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test seeding skips invalid relay URLs."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("invalid-url\nwss://valid.relay.com\nnot-a-relay\n")

        mock_seeder_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"url": "wss://valid.relay.com"}]
        )
        mock_seeder_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder.seed()

    async def test_seed_empty_file(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test seeding with empty file."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("")

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder.seed()

    async def test_seed_all_exist(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test seeding when all relays already exist."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay.example.com\n")

        mock_seeder_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[]
        )

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder.seed()


# ============================================================================
# Parse Seed File Tests
# ============================================================================


class TestParseSeedFile:
    """Tests for parse_seed_file() utility function."""

    def test_parse_valid_relays(self, tmp_path: Path) -> None:
        """Test parsing valid relay URLs."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("wss://relay1.example.com\nwss://relay2.example.com\n")

        relays = parse_seed_file(seed_file)

        assert len(relays) == 2
        urls = [r.url for r in relays]
        assert "wss://relay1.example.com" in urls
        assert "wss://relay2.example.com" in urls

    def test_parse_skips_comments(self, tmp_path: Path) -> None:
        """Test parsing skips comment lines."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("# This is a comment\nwss://relay.example.com\n# Another comment\n")

        relays = parse_seed_file(seed_file)

        assert len(relays) == 1
        assert relays[0].url == "wss://relay.example.com"

    def test_parse_skips_empty_lines(self, tmp_path: Path) -> None:
        """Test parsing skips empty lines."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("\n\nwss://relay.example.com\n\n")

        relays = parse_seed_file(seed_file)

        assert len(relays) == 1

    def test_parse_skips_invalid_urls(self, tmp_path: Path) -> None:
        """Test parsing skips invalid URLs."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("invalid-url\nwss://valid.relay.com\nnot-a-relay\n")

        relays = parse_seed_file(seed_file)

        assert len(relays) == 1
        assert relays[0].url == "wss://valid.relay.com"

    def test_parse_strips_whitespace(self, tmp_path: Path) -> None:
        """Test parsing strips leading/trailing whitespace."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("  wss://relay.example.com  \n")

        relays = parse_seed_file(seed_file)

        assert len(relays) == 1
        assert relays[0].url == "wss://relay.example.com"

    def test_parse_handles_tor_urls(self, tmp_path: Path) -> None:
        """Test parsing handles Tor .onion URLs."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("ws://example.onion\n")

        relays = parse_seed_file(seed_file)

        assert len(relays) == 1
        assert "onion" in relays[0].url

    def test_parse_handles_i2p_urls(self, tmp_path: Path) -> None:
        """Test parsing handles I2P .i2p URLs."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("ws://example.i2p\n")

        relays = parse_seed_file(seed_file)

        assert len(relays) == 1
        assert "i2p" in relays[0].url

    def test_parse_file_not_found(self, tmp_path: Path) -> None:
        """Test parsing returns empty list for non-existent file."""
        relays = parse_seed_file(tmp_path / "nonexistent.txt")
        assert relays == []

    def test_parse_permission_error(self, tmp_path: Path) -> None:
        """Test parsing returns empty list when file is not readable."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("wss://relay.example.com")
        seed_file.chmod(0o000)

        relays = parse_seed_file(seed_file)
        assert relays == []

        seed_file.chmod(0o644)

    def test_parse_is_a_directory_error(self, tmp_path: Path) -> None:
        """Test parsing returns empty list when path is a directory."""
        relays = parse_seed_file(tmp_path)
        assert relays == []

    def test_parse_unicode_decode_error(self, tmp_path: Path) -> None:
        """Test parsing returns empty list for non-UTF-8 file."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_bytes(b"\xff\xfe" + b"\x00" * 50)

        relays = parse_seed_file(seed_file)
        assert relays == []


# ============================================================================
# Seed As Candidates Tests
# ============================================================================


class TestSeedAsCandidates:
    """Tests for Seeder._seed_as_candidates() method."""

    async def test_seed_as_candidates_filters_existing(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test seeding filters relays that already exist in database."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("wss://new.relay.com\nwss://existing.relay.com\n")

        # Mock fetch to return only new relay (existing filtered out)
        mock_seeder_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"url": "wss://new.relay.com"}]
        )
        mock_seeder_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file), to_validate=True))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)
        relays = parse_seed_file(seed_file)

        await seeder._seed_as_candidates(relays)

        mock_seeder_brotr.upsert_service_state.assert_called()

    async def test_seed_as_candidates_includes_network_type(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test seeding includes network type in candidate data."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("wss://clearnet.relay.com\nws://example.onion\n")

        mock_seeder_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {"url": "wss://clearnet.relay.com"},
                {"url": "ws://example.onion"},
            ]
        )
        mock_seeder_brotr.upsert_service_state = AsyncMock(return_value=2)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file), to_validate=True))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)
        relays = parse_seed_file(seed_file)

        await seeder._seed_as_candidates(relays)

        call_args = mock_seeder_brotr.upsert_service_state.call_args[0][0]
        networks = [record.state_value["network"] for record in call_args]
        assert "clearnet" in networks
        assert "tor" in networks


# ============================================================================
# Seed As Relays Tests
# ============================================================================


class TestSeedAsRelays:
    """Tests for Seeder._seed_as_relays() method."""

    async def test_seed_as_relays_inserts_directly(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test seeding inserts relays directly into relays table."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("wss://relay1.example.com\nwss://relay2.example.com\n")

        mock_seeder_brotr.insert_relay = AsyncMock(return_value=2)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file), to_validate=False))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)
        relays = parse_seed_file(seed_file)

        await seeder._seed_as_relays(relays)

        mock_seeder_brotr.insert_relay.assert_called()

    async def test_seed_as_relays_batching(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test seeding batches large relay lists."""
        # Create a large relay list
        seed_file = tmp_path / "seed.txt"
        relay_urls = [f"wss://relay{i}.example.com" for i in range(250)]
        seed_file.write_text("\n".join(relay_urls))

        # Set small batch size to test batching
        mock_seeder_brotr.config.batch.max_size = 100
        mock_seeder_brotr.insert_relay = AsyncMock(return_value=100)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file), to_validate=False))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)
        relays = parse_seed_file(seed_file)

        await seeder._seed_as_relays(relays)

        assert mock_seeder_brotr.insert_relay.call_count >= 2


# ============================================================================
# Run Tests
# ============================================================================


class TestSeederRun:
    """Tests for Seeder.run() method."""

    async def test_run_file_missing(self, mock_seeder_brotr: Brotr) -> None:
        """Test run with seed file missing."""
        config = SeederConfig(seed=SeedConfig(file_path="nonexistent.txt"))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder.run()

    async def test_run_success(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test run completes successfully."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay.example.com\n")

        mock_seeder_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"url": "wss://relay.example.com"}]
        )
        mock_seeder_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder.run()

    async def test_run_logs_cycle_completion(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test run logs cycle completion."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay.example.com\n")

        mock_seeder_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"url": "wss://relay.example.com"}]
        )
        mock_seeder_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        with patch.object(seeder._logger, "info") as mock_log:
            await seeder.run()
            # Check that cycle_completed was logged
            log_messages = [call[0][0] for call in mock_log.call_args_list]
            assert "cycle_completed" in log_messages


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestSeederErrorHandling:
    """Tests for error handling in Seeder."""

    async def test_database_error_handled(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test database errors are handled gracefully."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("wss://relay.example.com\n")

        mock_seeder_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            side_effect=Exception("Database error")
        )

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        with pytest.raises(Exception, match="Database error"):
            await seeder.seed()

    async def test_postgres_error_in_seed_as_candidates(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """asyncpg.PostgresError in _seed_as_candidates returns 0."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("wss://relay.example.com\n")
        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file), to_validate=True))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        with patch(
            "bigbrotr.services.seeder.service.insert_candidates",
            new_callable=AsyncMock,
            side_effect=asyncpg.PostgresError("connection lost"),
        ):
            result = await seeder.seed()

        assert result == 0

    async def test_postgres_error_in_seed_as_relays(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """asyncpg.PostgresError in _seed_as_relays returns 0."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("wss://relay.example.com\n")
        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file), to_validate=False))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        with patch(
            "bigbrotr.services.seeder.service.insert_relays",
            new_callable=AsyncMock,
            side_effect=asyncpg.PostgresError("connection lost"),
        ):
            result = await seeder.seed()

        assert result == 0

    async def test_invalid_url_logged_not_raised(self, tmp_path: Path) -> None:
        """Test invalid URLs are logged but don't raise exceptions."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("invalid://not-a-valid-relay-url\nwss://valid.relay.com\n")

        relays = parse_seed_file(seed_file)
        assert len(relays) == 1
