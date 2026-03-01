"""Unit tests for services.seeder configuration models."""

import pytest

from bigbrotr.services.seeder import SeedConfig, SeederConfig


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

    def test_empty_file_path_rejected(self) -> None:
        """Test that empty file_path is rejected."""
        with pytest.raises(ValueError):
            SeedConfig(file_path="")


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
