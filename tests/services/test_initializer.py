"""
Unit tests for services.initializer module.

Tests:
- Configuration models (SeedConfig, InitializerConfig)
- Initializer service initialization
- Relay seeding from file
"""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.brotr import Brotr
from services.initializer import (
    Initializer,
    InitializerConfig,
    SeedConfig,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_initializer_brotr(mock_brotr: Brotr) -> Brotr:
    """Create a Brotr mock configured for initializer tests."""
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

        assert config.enabled is True
        assert config.file_path == "data/seed_relays.txt"

    def test_custom_values(self) -> None:
        """Test custom seed configuration."""
        config = SeedConfig(enabled=False, file_path="custom/path.txt")

        assert config.enabled is False
        assert config.file_path == "custom/path.txt"


# ============================================================================
# InitializerConfig Tests
# ============================================================================


class TestInitializerConfig:
    """Tests for InitializerConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default configuration."""
        config = InitializerConfig()

        assert config.seed.enabled is True

    def test_custom_nested_config(self) -> None:
        """Test custom nested configuration."""
        config = InitializerConfig(
            seed=SeedConfig(enabled=False),
        )

        assert config.seed.enabled is False


# ============================================================================
# Initializer Initialization Tests
# ============================================================================


class TestInitializerInit:
    """Tests for Initializer initialization."""

    def test_init_with_defaults(self, mock_initializer_brotr: Brotr) -> None:
        """Test initialization with default config."""
        initializer = Initializer(brotr=mock_initializer_brotr)

        assert initializer._brotr is mock_initializer_brotr
        assert initializer.SERVICE_NAME == "initializer"
        assert initializer.config.seed.enabled is True

    def test_init_with_custom_config(self, mock_initializer_brotr: Brotr) -> None:
        """Test initialization with custom config."""
        config = InitializerConfig(
            seed=SeedConfig(enabled=False),
        )
        initializer = Initializer(brotr=mock_initializer_brotr, config=config)

        assert initializer.config.seed.enabled is False

    def test_from_dict(self, mock_initializer_brotr: Brotr) -> None:
        """Test factory method from_dict."""
        data = {
            "seed": {"enabled": False},
        }
        initializer = Initializer.from_dict(data, brotr=mock_initializer_brotr)

        assert initializer.config.seed.enabled is False


# ============================================================================
# Seed Relays Tests
# ============================================================================


class TestSeedRelays:
    """Tests for relay seeding."""

    @pytest.mark.asyncio
    async def test_seed_relays_file_not_found(self, mock_initializer_brotr: Brotr) -> None:
        """Test seeding with non-existent file."""
        config = InitializerConfig(seed=SeedConfig(file_path="nonexistent/file.txt"))
        initializer = Initializer(brotr=mock_initializer_brotr, config=config)

        await initializer._seed_relays()  # Should not raise, logs warning

    @pytest.mark.asyncio
    async def test_seed_relays_success(self, mock_initializer_brotr: Brotr, tmp_path: Path) -> None:
        """Test successful relay seeding."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay1.example.com\nwss://relay2.example.com\n")

        # Mock fetch to return both URLs as new
        mock_initializer_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {"url": "relay1.example.com"},
                {"url": "relay2.example.com"},
            ]
        )

        config = InitializerConfig(seed=SeedConfig(file_path=str(seed_file)))
        initializer = Initializer(brotr=mock_initializer_brotr, config=config)

        await initializer._seed_relays()

    @pytest.mark.asyncio
    async def test_seed_relays_skips_comments_and_empty(
        self, mock_initializer_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test seeding skips comments and empty lines."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("# Comment\n\nwss://relay.example.com\n# Another comment\n")

        # Mock fetch to return the URL as new
        mock_initializer_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"url": "relay.example.com"}]
        )

        config = InitializerConfig(seed=SeedConfig(file_path=str(seed_file)))
        initializer = Initializer(brotr=mock_initializer_brotr, config=config)

        await initializer._seed_relays()

    @pytest.mark.asyncio
    async def test_seed_relays_skips_invalid_urls(
        self, mock_initializer_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test seeding skips invalid relay URLs."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("invalid-url\nwss://valid.relay.com\nnot-a-relay\n")

        # Mock fetch to return the valid URL as new
        mock_initializer_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"url": "valid.relay.com"}]
        )

        config = InitializerConfig(seed=SeedConfig(file_path=str(seed_file)))
        initializer = Initializer(brotr=mock_initializer_brotr, config=config)

        await initializer._seed_relays()

    @pytest.mark.asyncio
    async def test_seed_relays_empty_file(self, mock_initializer_brotr: Brotr, tmp_path: Path) -> None:
        """Test seeding with empty file."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("")

        config = InitializerConfig(seed=SeedConfig(file_path=str(seed_file)))
        initializer = Initializer(brotr=mock_initializer_brotr, config=config)

        await initializer._seed_relays()  # Should not raise

    @pytest.mark.asyncio
    async def test_seed_relays_all_exist(
        self, mock_initializer_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test seeding when all relays already exist."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay.example.com\n")

        # Mock fetch to return empty (all relays already exist)
        mock_initializer_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[]
        )

        config = InitializerConfig(seed=SeedConfig(file_path=str(seed_file)))
        initializer = Initializer(brotr=mock_initializer_brotr, config=config)

        await initializer._seed_relays()  # Should not raise


# ============================================================================
# Run Tests
# ============================================================================


class TestInitializerRun:
    """Tests for Initializer.run() method."""

    @pytest.mark.asyncio
    async def test_run_seed_disabled(self, mock_initializer_brotr: Brotr) -> None:
        """Test run with seed disabled."""
        config = InitializerConfig(seed=SeedConfig(enabled=False))
        initializer = Initializer(brotr=mock_initializer_brotr, config=config)

        await initializer.run()  # Should not raise

    @pytest.mark.asyncio
    async def test_run_seed_enabled_file_missing(self, mock_initializer_brotr: Brotr) -> None:
        """Test run with seed enabled but file missing."""
        config = InitializerConfig(seed=SeedConfig(file_path="nonexistent.txt"))
        initializer = Initializer(brotr=mock_initializer_brotr, config=config)

        await initializer.run()  # Should not raise, logs warning
