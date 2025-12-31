"""
Unit tests for services.validator module.

Tests:
- Configuration models
- Validator service initialization
- Candidate selection (probabilistic weighting)
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.brotr import Brotr, BrotrConfig
from services.validator import (
    ConcurrencyConfig,
    Validator,
    ValidatorConfig,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_validator_brotr(mock_brotr: Brotr) -> Brotr:
    """Create a Brotr mock configured for validator tests."""
    mock_batch_config = MagicMock()
    mock_batch_config.max_batch_size = 100
    mock_config = MagicMock(spec=BrotrConfig)
    mock_config.batch = mock_batch_config
    mock_brotr._config = mock_config
    mock_brotr.get_service_data = AsyncMock(return_value=[])
    mock_brotr.upsert_service_data = AsyncMock()
    mock_brotr.delete_service_data = AsyncMock()
    mock_brotr.insert_relays = AsyncMock(return_value=1)
    return mock_brotr


# ============================================================================
# ValidatorConfig Tests
# ============================================================================


class TestValidatorConfig:
    """Tests for ValidatorConfig."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = ValidatorConfig()

        assert config.interval == 300.0
        assert config.connection_timeout == 10.0
        assert config.max_candidates_per_run is None
        assert config.concurrency.max_parallel == 10
        assert config.tor.enabled is True  # TorConfig defaults to enabled=True

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = ValidatorConfig(
            interval=600.0,
            connection_timeout=15.0,
            max_candidates_per_run=50,
        )

        assert config.interval == 600.0
        assert config.connection_timeout == 15.0
        assert config.max_candidates_per_run == 50

    def test_interval_minimum(self) -> None:
        """Test interval minimum constraint."""
        with pytest.raises(ValueError):
            ValidatorConfig(interval=30.0)

    def test_connection_timeout_bounds(self) -> None:
        """Test connection timeout bounds."""
        with pytest.raises(ValueError):
            ValidatorConfig(connection_timeout=0.5)

        with pytest.raises(ValueError):
            ValidatorConfig(connection_timeout=100.0)


# ============================================================================
# ConcurrencyConfig Tests
# ============================================================================


class TestConcurrencyConfig:
    """Tests for ConcurrencyConfig."""

    def test_default_values(self) -> None:
        """Test default concurrency values."""
        config = ConcurrencyConfig()
        assert config.max_parallel == 10

    def test_custom_values(self) -> None:
        """Test custom concurrency values."""
        config = ConcurrencyConfig(max_parallel=25)
        assert config.max_parallel == 25

    def test_max_parallel_bounds(self) -> None:
        """Test max_parallel validation bounds."""
        # Test minimum bound
        with pytest.raises(ValueError):
            ConcurrencyConfig(max_parallel=0)

        # Test maximum bound
        with pytest.raises(ValueError):
            ConcurrencyConfig(max_parallel=101)

        # Test valid edge cases
        config_min = ConcurrencyConfig(max_parallel=1)
        assert config_min.max_parallel == 1

        config_max = ConcurrencyConfig(max_parallel=100)
        assert config_max.max_parallel == 100


# ============================================================================
# Validator Service Tests
# ============================================================================


class TestValidator:
    """Tests for Validator service."""

    def test_init_default_config(self, mock_validator_brotr: Brotr) -> None:
        """Test initialization with default config."""
        validator = Validator(brotr=mock_validator_brotr)

        assert validator._config.interval == 300.0
        assert validator._config.connection_timeout == 10.0

    def test_init_custom_config(self, mock_validator_brotr: Brotr) -> None:
        """Test initialization with custom config."""
        config = ValidatorConfig(interval=600.0, connection_timeout=20.0)
        validator = Validator(brotr=mock_validator_brotr, config=config)

        assert validator._config.interval == 600.0
        assert validator._config.connection_timeout == 20.0


# ============================================================================
# Candidate Selection Tests
# ============================================================================


class TestCandidateSelection:
    """Tests for candidate selection logic."""

    def test_select_all_when_no_limit(self, mock_validator_brotr: Brotr) -> None:
        """Test all candidates are selected when no limit is set."""
        config = ValidatorConfig(max_candidates_per_run=None)
        validator = Validator(brotr=mock_validator_brotr, config=config)

        candidates = [
            {"key": "wss://relay1.com", "value": {"retries": 0}, "updated_at": 1000},
            {"key": "wss://relay2.com", "value": {"retries": 1}, "updated_at": 1001},
            {"key": "wss://relay3.com", "value": {"retries": 2}, "updated_at": 1002},
        ]

        selected = validator._select_candidates(candidates)
        assert len(selected) == 3

    def test_select_all_when_under_limit(self, mock_validator_brotr: Brotr) -> None:
        """Test all candidates are selected when under limit."""
        config = ValidatorConfig(max_candidates_per_run=10)
        validator = Validator(brotr=mock_validator_brotr, config=config)

        candidates = [
            {"key": "wss://relay1.com", "value": {"retries": 0}, "updated_at": 1000},
            {"key": "wss://relay2.com", "value": {"retries": 1}, "updated_at": 1001},
        ]

        selected = validator._select_candidates(candidates)
        assert len(selected) == 2

    def test_select_respects_limit(self, mock_validator_brotr: Brotr) -> None:
        """Test selection respects limit."""
        config = ValidatorConfig(max_candidates_per_run=2)
        validator = Validator(brotr=mock_validator_brotr, config=config)

        candidates = [
            {"key": "wss://relay1.com", "value": {"retries": 0}, "updated_at": 1000},
            {"key": "wss://relay2.com", "value": {"retries": 1}, "updated_at": 1001},
            {"key": "wss://relay3.com", "value": {"retries": 2}, "updated_at": 1002},
            {"key": "wss://relay4.com", "value": {"retries": 3}, "updated_at": 1003},
        ]

        selected = validator._select_candidates(candidates)
        assert len(selected) == 2

    def test_probabilistic_selection_favors_low_retries(self, mock_validator_brotr: Brotr) -> None:
        """Test that candidates with fewer retries are more likely to be selected."""
        config = ValidatorConfig(max_candidates_per_run=1)
        validator = Validator(brotr=mock_validator_brotr, config=config)

        # Create candidates with very different retry counts
        candidates = [
            {"key": "wss://low.com", "value": {"retries": 0}, "updated_at": 1000},
            {"key": "wss://high1.com", "value": {"retries": 100}, "updated_at": 1001},
            {"key": "wss://high2.com", "value": {"retries": 100}, "updated_at": 1002},
            {"key": "wss://high3.com", "value": {"retries": 100}, "updated_at": 1003},
        ]

        # Run selection many times and count how often "low" is selected
        low_selected_count = 0
        iterations = 100

        for _ in range(iterations):
            selected = validator._select_candidates(candidates)
            if selected[0]["key"] == "wss://low.com":
                low_selected_count += 1

        # With weight = 1/(retries+1), "low" has weight 1.0 and each "high" has weight 0.01
        # Expected probability for "low" is 1.0 / (1.0 + 0.01*3) ≈ 97%
        # With 100 iterations, we expect ~97 selections of "low"
        assert low_selected_count > 80, f"Expected >80, got {low_selected_count}"

    def test_empty_value_defaults_to_zero_retries(self, mock_validator_brotr: Brotr) -> None:
        """Test that empty value defaults to 0 retries."""
        config = ValidatorConfig(max_candidates_per_run=None)
        validator = Validator(brotr=mock_validator_brotr, config=config)

        candidates = [
            {"key": "wss://relay1.com", "value": {}, "updated_at": 1000},
        ]

        # Should not raise, and candidate should be included
        selected = validator._select_candidates(candidates)
        assert len(selected) == 1
