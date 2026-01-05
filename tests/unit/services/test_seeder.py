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

        assert config.file_path == "seed_relays.txt"

    def test_custom_values(self) -> None:
        """Test custom seed configuration."""
        config = SeedConfig(file_path="custom/path.txt")

        assert config.file_path == "custom/path.txt"


# ============================================================================
# SeederConfig Tests
# ============================================================================


class TestSeederConfig:
    """Tests for SeederConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default configuration."""
        config = SeederConfig()

        assert config.seed.file_path == "seed_relays.txt"

    def test_custom_nested_config(self) -> None:
        """Test custom nested configuration."""
        config = SeederConfig(
            seed=SeedConfig(file_path="custom/path.txt"),
        )

        assert config.seed.file_path == "custom/path.txt"


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
        assert seeder.config.seed.file_path == "seed_relays.txt"

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
            "seed": {"file_path": "custom/path.txt"},
        }
        seeder = Seeder.from_dict(data, brotr=mock_seeder_brotr)

        assert seeder.config.seed.file_path == "custom/path.txt"


# ============================================================================
# Seed Relays Tests
# ============================================================================


class TestSeedRelays:
    """Tests for relay seeding."""

    @pytest.mark.asyncio
    async def test_seed_relays_file_not_found(self, mock_seeder_brotr: Brotr) -> None:
        """Test seeding with non-existent file."""
        config = SeederConfig(seed=SeedConfig(file_path="nonexistent/file.txt"))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder._seed_relays()  # Should not raise, logs warning

    @pytest.mark.asyncio
    async def test_seed_relays_success(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test successful relay seeding."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay1.example.com\nwss://relay2.example.com\n")

        # Mock fetch to return both URLs as new
        mock_seeder_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {"url": "wss://relay1.example.com"},
                {"url": "wss://relay2.example.com"},
            ]
        )

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder._seed_relays()

    @pytest.mark.asyncio
    async def test_seed_relays_skips_comments_and_empty(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test seeding skips comments and empty lines."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("# Comment\n\nwss://relay.example.com\n# Another comment\n")

        # Mock fetch to return the URL as new
        mock_seeder_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"url": "wss://relay.example.com"}]
        )

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder._seed_relays()

    @pytest.mark.asyncio
    async def test_seed_relays_skips_invalid_urls(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test seeding skips invalid relay URLs."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("invalid-url\nwss://valid.relay.com\nnot-a-relay\n")

        # Mock fetch to return the valid URL as new
        mock_seeder_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"url": "wss://valid.relay.com"}]
        )

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder._seed_relays()

    @pytest.mark.asyncio
    async def test_seed_relays_empty_file(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test seeding with empty file."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("")

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder._seed_relays()  # Should not raise

    @pytest.mark.asyncio
    async def test_seed_relays_all_exist(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test seeding when all relays already exist."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay.example.com\n")

        # Mock fetch to return empty (all relays already exist)
        mock_seeder_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[]
        )

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder._seed_relays()  # Should not raise


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
