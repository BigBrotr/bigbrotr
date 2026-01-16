"""
Unit tests for services.seeder module.

Tests:
- Configuration models (SeedConfig, SeederConfig)
- Seeder service initialization
- Relay seeding from file
"""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.brotr import Brotr
from services.seeder import (
    SeedConfig,
    Seeder,
    SeederConfig,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_seeder_brotr(mock_brotr: Brotr) -> Brotr:
    """Create a Brotr mock configured for seeder tests."""
    # Default successful responses
    mock_brotr.pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]
    mock_brotr.pool._mock_connection.execute = AsyncMock()  # type: ignore[attr-defined]
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


# ============================================================================
# Seed Relays Tests
# ============================================================================


class TestSeedRelays:
    """Tests for relay seeding."""

    @pytest.mark.asyncio
    async def test_seed_file_not_found(self, mock_seeder_brotr: Brotr) -> None:
        """Test seeding with non-existent file."""
        config = SeederConfig(seed=SeedConfig(file_path="nonexistent/file.txt"))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder._seed()  # Should not raise, logs warning

    @pytest.mark.asyncio
    async def test_seed_success_as_candidates(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test successful relay seeding as validation candidates."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay1.example.com\nwss://relay2.example.com\n")

        # Mock fetch to return both URLs as new
        mock_seeder_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {"url": "wss://relay1.example.com"},
                {"url": "wss://relay2.example.com"},
            ]
        )
        mock_seeder_brotr.upsert_service_data = AsyncMock(return_value=2)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file), to_validate=True))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder._seed()

        # Verify upsert_service_data was called
        mock_seeder_brotr.upsert_service_data.assert_called()

    @pytest.mark.asyncio
    async def test_seed_success_as_relays(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test successful relay seeding directly into relays table."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay1.example.com\nwss://relay2.example.com\n")

        mock_seeder_brotr.insert_relays = AsyncMock(return_value=2)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file), to_validate=False))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder._seed()

        # Verify insert_relays was called
        mock_seeder_brotr.insert_relays.assert_called()

    @pytest.mark.asyncio
    async def test_seed_skips_comments_and_empty(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test seeding skips comments and empty lines."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("# Comment\n\nwss://relay.example.com\n# Another comment\n")

        # Mock fetch to return the URL as new
        mock_seeder_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"url": "wss://relay.example.com"}]
        )
        mock_seeder_brotr.upsert_service_data = AsyncMock(return_value=1)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder._seed()

    @pytest.mark.asyncio
    async def test_seed_skips_invalid_urls(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test seeding skips invalid relay URLs."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("invalid-url\nwss://valid.relay.com\nnot-a-relay\n")

        # Mock fetch to return the valid URL as new
        mock_seeder_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"url": "wss://valid.relay.com"}]
        )
        mock_seeder_brotr.upsert_service_data = AsyncMock(return_value=1)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder._seed()

    @pytest.mark.asyncio
    async def test_seed_empty_file(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test seeding with empty file."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("")

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder._seed()  # Should not raise

    @pytest.mark.asyncio
    async def test_seed_all_exist(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test seeding when all relays already exist."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay.example.com\n")

        # Mock fetch to return empty (all relays already exist)
        mock_seeder_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[]
        )

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder._seed()  # Should not raise


# ============================================================================
# Parse Seed File Tests
# ============================================================================


class TestParseSeedFile:
    """Tests for Seeder._parse_seed_file() method."""

    def test_parse_valid_relays(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test parsing valid relay URLs."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("wss://relay1.example.com\nwss://relay2.example.com\n")

        seeder = Seeder(brotr=mock_seeder_brotr)
        relays = seeder._parse_seed_file(seed_file)

        assert len(relays) == 2
        urls = [r.url for r in relays]
        assert "wss://relay1.example.com" in urls
        assert "wss://relay2.example.com" in urls

    def test_parse_skips_comments(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test parsing skips comment lines."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("# This is a comment\nwss://relay.example.com\n# Another comment\n")

        seeder = Seeder(brotr=mock_seeder_brotr)
        relays = seeder._parse_seed_file(seed_file)

        assert len(relays) == 1
        assert relays[0].url == "wss://relay.example.com"

    def test_parse_skips_empty_lines(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test parsing skips empty lines."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("\n\nwss://relay.example.com\n\n")

        seeder = Seeder(brotr=mock_seeder_brotr)
        relays = seeder._parse_seed_file(seed_file)

        assert len(relays) == 1

    def test_parse_skips_invalid_urls(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test parsing skips invalid URLs."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("invalid-url\nwss://valid.relay.com\nnot-a-relay\n")

        seeder = Seeder(brotr=mock_seeder_brotr)
        relays = seeder._parse_seed_file(seed_file)

        assert len(relays) == 1
        assert relays[0].url == "wss://valid.relay.com"


# ============================================================================
# Run Tests
# ============================================================================


class TestSeederRun:
    """Tests for Seeder.run() method."""

    @pytest.mark.asyncio
    async def test_run_file_missing(self, mock_seeder_brotr: Brotr) -> None:
        """Test run with seed file missing."""
        config = SeederConfig(seed=SeedConfig(file_path="nonexistent.txt"))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder.run()  # Should not raise, logs warning

    @pytest.mark.asyncio
    async def test_run_success(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test run completes successfully."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay.example.com\n")

        mock_seeder_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"url": "wss://relay.example.com"}]
        )
        mock_seeder_brotr.upsert_service_data = AsyncMock(return_value=1)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder.run()  # Should complete without error
