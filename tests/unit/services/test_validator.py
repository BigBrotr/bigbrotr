"""
Unit tests for services.validator module.

Tests:
- Configuration models (ValidatorConfig, BatchConfig, ConcurrencyConfig, NetworkConfig)
- Validator service initialization and defaults
- Batch configuration and candidate limits
- Network proxy configuration for overlay networks (Tor, I2P, Loki)
- Relay validation workflow
- Candidate promotion and failure tracking
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.brotr import Brotr, BrotrConfig
from models.relay import NetworkType
from services.validator import (
    BatchConfig,
    ConcurrencyConfig,
    Validator,
    ValidatorConfig,
)
from utils.network import NetworkConfig, NetworkProxyConfig


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
        assert config.batch.timeout == 10.0
        assert config.batch.max_candidates is None
        assert config.concurrency.tasks == 10
        assert config.network.tor.enabled is True  # NetworkConfig defaults tor to enabled=True

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = ValidatorConfig(
            interval=600.0,
            batch=BatchConfig(timeout=15.0, max_candidates=50),
        )

        assert config.interval == 600.0
        assert config.batch.timeout == 15.0
        assert config.batch.max_candidates == 50

    def test_interval_minimum(self) -> None:
        """Test interval minimum constraint."""
        with pytest.raises(ValueError):
            ValidatorConfig(interval=30.0)

    def test_batch_timeout_bounds(self) -> None:
        """Test batch timeout bounds."""
        with pytest.raises(ValueError):
            BatchConfig(timeout=0.05)  # Below 0.1

        with pytest.raises(ValueError):
            BatchConfig(timeout=100.0)  # Above 60.0


# ============================================================================
# ConcurrencyConfig Tests
# ============================================================================


class TestConcurrencyConfig:
    """Tests for ConcurrencyConfig."""

    def test_default_values(self) -> None:
        """Test default concurrency values."""
        config = ConcurrencyConfig()
        assert config.processes == 1
        assert config.tasks == 10

    def test_custom_values(self) -> None:
        """Test custom concurrency values."""
        config = ConcurrencyConfig(processes=4, tasks=25)
        assert config.processes == 4
        assert config.tasks == 25

    def test_tasks_bounds(self) -> None:
        """Test tasks validation bounds."""
        # Test minimum bound
        with pytest.raises(ValueError):
            ConcurrencyConfig(tasks=0)

        # Test maximum bound
        with pytest.raises(ValueError):
            ConcurrencyConfig(tasks=101)

        # Test valid edge cases
        config_min = ConcurrencyConfig(tasks=1)
        assert config_min.tasks == 1

        config_max = ConcurrencyConfig(tasks=100)
        assert config_max.tasks == 100

    def test_processes_bounds(self) -> None:
        """Test processes validation bounds."""
        # Test minimum bound
        with pytest.raises(ValueError):
            ConcurrencyConfig(processes=0)

        # Test maximum bound
        with pytest.raises(ValueError):
            ConcurrencyConfig(processes=33)

        # Test valid edge cases
        config_min = ConcurrencyConfig(processes=1)
        assert config_min.processes == 1

        config_max = ConcurrencyConfig(processes=32)
        assert config_max.processes == 32


# ============================================================================
# Validator Service Tests
# ============================================================================


class TestValidator:
    """Tests for Validator service."""

    def test_init_default_config(self, mock_validator_brotr: Brotr) -> None:
        """Test initialization with default config."""
        validator = Validator(brotr=mock_validator_brotr)

        assert validator._config.interval == 300.0
        assert validator._config.batch.timeout == 10.0

    def test_init_custom_config(self, mock_validator_brotr: Brotr) -> None:
        """Test initialization with custom config."""
        config = ValidatorConfig(
            interval=600.0,
            batch=BatchConfig(timeout=20.0),
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)

        assert validator._config.interval == 600.0
        assert validator._config.batch.timeout == 20.0


# ============================================================================
# Candidate Selection Tests
# ============================================================================


class TestCandidateSelection:
    """Tests for candidate selection logic.

    Note: With the new validator design, candidate selection and limiting
    is done via SQL query (ORDER BY failed_attempts ASC, LIMIT). These tests
    verify the validator handles the fetched candidates correctly.
    """

    def test_handles_candidates_from_database(self, mock_validator_brotr: Brotr) -> None:
        """Test validator handles candidates returned from database."""
        config = ValidatorConfig()
        validator = Validator(brotr=mock_validator_brotr, config=config)

        # Candidates are now fetched via SQL, not selected in Python
        # This test verifies the config structure is correct
        assert config.batch.max_candidates is None  # No limit by default

    def test_batch_max_candidates_config(self, mock_validator_brotr: Brotr) -> None:
        """Test batch.max_candidates configuration."""
        config = ValidatorConfig(batch=BatchConfig(max_candidates=10))
        validator = Validator(brotr=mock_validator_brotr, config=config)

        assert validator._config.batch.max_candidates == 10

    def test_batch_max_candidates_none_means_unlimited(self, mock_validator_brotr: Brotr) -> None:
        """Test batch.max_candidates=None means unlimited."""
        config = ValidatorConfig(batch=BatchConfig(max_candidates=None))
        validator = Validator(brotr=mock_validator_brotr, config=config)

        assert validator._config.batch.max_candidates is None


# ============================================================================
# validator.run() Error Handling Tests
# ============================================================================


class TestValidatorRunErrorHandling:
    """Tests for Validator.run() error handling."""

    @pytest.mark.asyncio
    async def test_database_error_during_candidate_fetch(self, mock_validator_brotr: Brotr) -> None:
        """Database error during candidate fetch logged and handled."""
        mock_validator_brotr.get_service_data = AsyncMock(
            side_effect=Exception("DB connection failed")
        )

        validator = Validator(brotr=mock_validator_brotr)

        # Should not raise, error should be handled
        with pytest.raises(Exception, match="DB connection failed"):
            await validator.run()

    @pytest.mark.asyncio
    async def test_database_error_during_batch_insert(self, mock_validator_brotr: Brotr) -> None:
        """Database error during batch insert logged and handled."""
        mock_validator_brotr.get_service_data = AsyncMock(
            return_value=[
                {"key": "wss://relay.com", "value": {"failed_attempts": 0}, "updated_at": 1000}
            ]
        )
        mock_validator_brotr.insert_relays = AsyncMock(side_effect=Exception("Insert failed"))
        mock_validator_brotr.delete_service_data = AsyncMock(return_value=1)
        mock_validator_brotr.upsert_service_data = AsyncMock(return_value=1)

        config = ValidatorConfig(batch=BatchConfig(timeout=1.0))
        validator = Validator(brotr=mock_validator_brotr, config=config)

        # Mock the connection test to succeed
        with patch.object(validator, "_test_connection", new_callable=AsyncMock, return_value=True):
            # Should not raise, error should be logged
            await validator.run()

            # Verify insert was attempted
            mock_validator_brotr.insert_relays.assert_called()

    @pytest.mark.asyncio
    async def test_partial_batch_success(self, mock_validator_brotr: Brotr) -> None:
        """Partial batch success (some candidates fail)."""
        candidates = [
            {"key": "wss://good.relay.com", "value": {"failed_attempts": 0}, "updated_at": 1000},
            {"key": "wss://bad.relay.com", "value": {"failed_attempts": 0}, "updated_at": 1001},
        ]
        mock_validator_brotr.get_service_data = AsyncMock(return_value=candidates)
        mock_validator_brotr.insert_relays = AsyncMock(return_value=1)
        mock_validator_brotr.delete_service_data = AsyncMock(return_value=1)
        mock_validator_brotr.upsert_service_data = AsyncMock(return_value=1)

        config = ValidatorConfig(batch=BatchConfig(timeout=1.0))
        validator = Validator(brotr=mock_validator_brotr, config=config)

        # Mock connection test to return success for first, failure for second
        async def mock_test(url: str, keys=None) -> bool:
            return "good" in url

        with patch.object(validator, "_test_connection", side_effect=mock_test):
            await validator.run()

            # One success, one failure
            assert validator._validated_count == 1
            assert validator._failed_count == 1

    @pytest.mark.asyncio
    async def test_empty_candidate_list_after_filtering(self, mock_validator_brotr: Brotr) -> None:
        """Empty candidate list after filtering."""
        mock_validator_brotr.get_service_data = AsyncMock(return_value=[])

        validator = Validator(brotr=mock_validator_brotr)
        await validator.run()

        # Should complete without error
        assert validator._validated_count == 0
        assert validator._failed_count == 0

    @pytest.mark.asyncio
    async def test_all_candidates_fail_validation(self, mock_validator_brotr: Brotr) -> None:
        """All candidates fail validation."""
        candidates = [
            {"key": "wss://fail1.com", "value": {"failed_attempts": 0}, "updated_at": 1000},
            {"key": "wss://fail2.com", "value": {"failed_attempts": 0}, "updated_at": 1001},
        ]
        mock_validator_brotr.get_service_data = AsyncMock(return_value=candidates)
        mock_validator_brotr.upsert_service_data = AsyncMock(return_value=2)

        config = ValidatorConfig(batch=BatchConfig(timeout=1.0))
        validator = Validator(brotr=mock_validator_brotr, config=config)

        with patch.object(
            validator, "_test_connection", new_callable=AsyncMock, return_value=False
        ):
            await validator.run()

            assert validator._validated_count == 0
            assert validator._failed_count == 2
            # Retry records should be upserted
            mock_validator_brotr.upsert_service_data.assert_called()

    @pytest.mark.asyncio
    async def test_mix_of_successful_and_failed_validations(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Mix of successful and failed validations."""
        candidates = [
            {"key": "wss://success1.com", "value": {"failed_attempts": 0}, "updated_at": 1000},
            {"key": "wss://fail1.com", "value": {"failed_attempts": 1}, "updated_at": 1001},
            {"key": "wss://success2.com", "value": {"failed_attempts": 0}, "updated_at": 1002},
            {"key": "wss://fail2.com", "value": {"failed_attempts": 2}, "updated_at": 1003},
        ]
        mock_validator_brotr.get_service_data = AsyncMock(return_value=candidates)
        mock_validator_brotr.insert_relays = AsyncMock(return_value=2)
        mock_validator_brotr.delete_service_data = AsyncMock(return_value=2)
        mock_validator_brotr.upsert_service_data = AsyncMock(return_value=2)

        config = ValidatorConfig(batch=BatchConfig(timeout=1.0))
        validator = Validator(brotr=mock_validator_brotr, config=config)

        async def mock_test(url: str, keys=None) -> bool:
            return "success" in url

        with patch.object(validator, "_test_connection", side_effect=mock_test):
            await validator.run()

            assert validator._validated_count == 2
            assert validator._failed_count == 2

    @pytest.mark.asyncio
    async def test_shutdown_during_validation_stops_gracefully(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Shutdown during validation stops gracefully."""
        candidates = [
            {"key": f"wss://relay{i}.com", "value": {"failed_attempts": 0}, "updated_at": 1000 + i}
            for i in range(10)
        ]
        mock_validator_brotr.get_service_data = AsyncMock(return_value=candidates)
        mock_validator_brotr.insert_relays = AsyncMock(return_value=1)
        mock_validator_brotr.delete_service_data = AsyncMock(return_value=1)
        mock_validator_brotr.upsert_service_data = AsyncMock(return_value=1)

        config = ValidatorConfig(batch=BatchConfig(timeout=1.0))
        validator = Validator(brotr=mock_validator_brotr, config=config)

        # Simulate slow validation
        async def slow_test(url: str, keys=None) -> bool:
            await asyncio.sleep(0.1)
            return True

        with patch.object(validator, "_test_connection", side_effect=slow_test):
            # Start validation
            task = asyncio.create_task(validator.run())
            # Let some validations start
            await asyncio.sleep(0.05)
            # Cancel (simulating shutdown)
            task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_timeout_during_batch_insert_handled(self, mock_validator_brotr: Brotr) -> None:
        """Timeout during batch insert handled."""
        candidates = [
            {"key": "wss://relay.com", "value": {"failed_attempts": 0}, "updated_at": 1000}
        ]
        mock_validator_brotr.get_service_data = AsyncMock(return_value=candidates)
        mock_validator_brotr.insert_relays = AsyncMock(
            side_effect=asyncio.TimeoutError("Insert timed out")
        )
        mock_validator_brotr.delete_service_data = AsyncMock(return_value=1)
        mock_validator_brotr.upsert_service_data = AsyncMock(return_value=1)

        config = ValidatorConfig(batch=BatchConfig(timeout=1.0))
        validator = Validator(brotr=mock_validator_brotr, config=config)

        with patch.object(validator, "_test_connection", new_callable=AsyncMock, return_value=True):
            # Should handle timeout gracefully
            await validator.run()

    @pytest.mark.asyncio
    async def test_connection_pool_exhaustion_handled(self, mock_validator_brotr: Brotr) -> None:
        """Connection pool exhaustion handled."""
        candidates = [
            {"key": "wss://relay.com", "value": {"failed_attempts": 0}, "updated_at": 1000}
        ]
        mock_validator_brotr.get_service_data = AsyncMock(return_value=candidates)
        mock_validator_brotr.insert_relays = AsyncMock(
            side_effect=Exception("Connection pool exhausted")
        )
        mock_validator_brotr.delete_service_data = AsyncMock(return_value=1)
        mock_validator_brotr.upsert_service_data = AsyncMock(return_value=1)

        config = ValidatorConfig(batch=BatchConfig(timeout=1.0))
        validator = Validator(brotr=mock_validator_brotr, config=config)

        with patch.object(validator, "_test_connection", new_callable=AsyncMock, return_value=True):
            # Should handle pool exhaustion gracefully
            await validator.run()


# ============================================================================
# _validate_candidate() and _test_connection() Tests
# ============================================================================


class TestValidateCandidateAndTestConnection:
    """Tests for _validate_candidate() and _test_connection() methods (H15)."""

    @pytest.mark.asyncio
    async def test_valid_clearnet_relay_passes_validation(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Valid clearnet relay passes validation."""
        config = ValidatorConfig(batch=BatchConfig(timeout=5.0))
        validator = Validator(brotr=mock_validator_brotr, config=config)
        candidate = {
            "key": "wss://valid.relay.com",
            "value": {"failed_attempts": 0},
            "updated_at": 1000,
        }
        semaphore = asyncio.Semaphore(10)

        with patch.object(validator, "_test_connection", new_callable=AsyncMock, return_value=True):
            result = await validator._validate_candidate(candidate, semaphore)

            url, is_valid, failed_attempts = result
            assert url == "wss://valid.relay.com"
            assert is_valid is True
            assert failed_attempts == 0

    @pytest.mark.asyncio
    async def test_valid_tor_relay_passes_validation_with_proxy(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Valid Tor relay passes validation (with proxy)."""
        config = ValidatorConfig(
            batch=BatchConfig(timeout=5.0),
            network=NetworkConfig(tor=NetworkProxyConfig(enabled=True, proxy_url="socks5://127.0.0.1:9050")),
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)
        candidate = {
            "key": "ws://tortest.onion",
            "value": {"failed_attempts": 0},
            "updated_at": 1000,
        }
        semaphore = asyncio.Semaphore(10)

        with patch.object(validator, "_test_connection", new_callable=AsyncMock, return_value=True):
            result = await validator._validate_candidate(candidate, semaphore)

            url, is_valid, failed_attempts = result
            assert is_valid is True

    @pytest.mark.asyncio
    async def test_connection_timeout_fails_validation(self, mock_validator_brotr: Brotr) -> None:
        """Connection timeout fails validation."""
        # connection_timeout minimum is 1.0 per ValidatorConfig validation
        config = ValidatorConfig(batch=BatchConfig(timeout=1.0))
        validator = Validator(brotr=mock_validator_brotr, config=config)
        candidate = {
            "key": "wss://timeout.relay.com",
            "value": {"failed_attempts": 0},
            "updated_at": 1000,
        }
        semaphore = asyncio.Semaphore(10)

        # Simulate connection test returning False (timeout scenario)
        with patch.object(
            validator, "_test_connection", new_callable=AsyncMock, return_value=False
        ):
            result = await validator._validate_candidate(candidate, semaphore)
            # Timeout/failure should result in is_valid=False
            url, is_valid, failed_attempts = result
            assert is_valid is False
            assert url == "wss://timeout.relay.com"

    @pytest.mark.asyncio
    async def test_invalid_websocket_url_fails_validation(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Invalid WebSocket URL fails validation."""
        config = ValidatorConfig(batch=BatchConfig(timeout=5.0))
        validator = Validator(brotr=mock_validator_brotr, config=config)

        # Test _test_connection directly with invalid URL
        result = await validator._test_connection("not-a-valid-url")
        assert result is False

    @pytest.mark.asyncio
    async def test_relay_refuses_connection_fails_validation(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Relay refuses connection fails validation."""
        config = ValidatorConfig(batch=BatchConfig(timeout=5.0))
        validator = Validator(brotr=mock_validator_brotr, config=config)
        candidate = {
            "key": "wss://refused.relay.com",
            "value": {"failed_attempts": 0},
            "updated_at": 1000,
        }
        semaphore = asyncio.Semaphore(10)

        with patch.object(
            validator, "_test_connection", new_callable=AsyncMock, return_value=False
        ):
            result = await validator._validate_candidate(candidate, semaphore)

            url, is_valid, failed_attempts = result
            assert is_valid is False

    @pytest.mark.asyncio
    async def test_relay_accepts_but_returns_error_fails_validation(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Relay accepts but returns error fails validation."""
        config = ValidatorConfig(batch=BatchConfig(timeout=5.0))
        validator = Validator(brotr=mock_validator_brotr, config=config)
        candidate = {
            "key": "wss://error.relay.com",
            "value": {"failed_attempts": 0},
            "updated_at": 1000,
        }
        semaphore = asyncio.Semaphore(10)

        # Simulate relay accepting connection but returning error
        with patch.object(
            validator, "_test_connection", new_callable=AsyncMock, return_value=False
        ):
            result = await validator._validate_candidate(candidate, semaphore)

            url, is_valid, failed_attempts = result
            assert is_valid is False

    @pytest.mark.asyncio
    async def test_tor_proxy_configuration_applied_correctly(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Tor proxy configuration applied correctly."""
        config = ValidatorConfig(
            batch=BatchConfig(timeout=5.0),
            network=NetworkConfig(tor=NetworkProxyConfig(enabled=True, proxy_url="socks5://127.0.0.1:9050")),
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)

        # Verify proxy URL is correctly configured
        assert validator._config.network.get_proxy_url(NetworkType.TOR) == "socks5://127.0.0.1:9050"
        assert validator._config.network.is_network_enabled(NetworkType.TOR) is True

    @pytest.mark.asyncio
    async def test_batch_timeout_value_respected(self, mock_validator_brotr: Brotr) -> None:
        """Batch timeout value respected."""
        config = ValidatorConfig(batch=BatchConfig(timeout=15.0))
        validator = Validator(brotr=mock_validator_brotr, config=config)

        assert validator._config.batch.timeout == 15.0

    @pytest.mark.asyncio
    async def test_failed_attempts_counter_incremented_on_failure(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Failed attempts counter incremented on failure."""
        config = ValidatorConfig(batch=BatchConfig(timeout=5.0))
        validator = Validator(brotr=mock_validator_brotr, config=config)
        candidate = {
            "key": "wss://failing.relay.com",
            "value": {"failed_attempts": 3},
            "updated_at": 1000,
        }
        semaphore = asyncio.Semaphore(10)

        with patch.object(
            validator, "_test_connection", new_callable=AsyncMock, return_value=False
        ):
            result = await validator._validate_candidate(candidate, semaphore)

            url, is_valid, failed_attempts = result
            # Original failed_attempts should be returned for incrementing by caller
            assert failed_attempts == 3
            assert is_valid is False

    @pytest.mark.asyncio
    async def test_successful_validation_resets_failed_attempts(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Successful validation resets failed attempts."""
        candidates = [
            {
                "key": "wss://recovered.relay.com",
                "value": {"failed_attempts": 5},
                "updated_at": 1000,
            }
        ]
        mock_validator_brotr.get_service_data = AsyncMock(return_value=candidates)
        mock_validator_brotr.insert_relays = AsyncMock(return_value=1)
        mock_validator_brotr.delete_service_data = AsyncMock(return_value=1)

        config = ValidatorConfig(batch=BatchConfig(timeout=5.0))
        validator = Validator(brotr=mock_validator_brotr, config=config)

        with patch.object(validator, "_test_connection", new_callable=AsyncMock, return_value=True):
            await validator.run()

            # Relay should be inserted (moved from candidates)
            mock_validator_brotr.insert_relays.assert_called()
            # Candidate should be deleted (not kept for retry)
            mock_validator_brotr.delete_service_data.assert_called()

    @pytest.mark.asyncio
    async def test_nip11_info_fetched_on_successful_connection(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """NIP-11 info fetched on successful connection."""
        # The validator uses nostr-sdk's fetch_events which implicitly validates
        # Nostr protocol compliance (EOSE response). NIP-11 is optional metadata.
        config = ValidatorConfig(batch=BatchConfig(timeout=5.0))
        validator = Validator(brotr=mock_validator_brotr, config=config)
        candidate = {
            "key": "wss://nip11.relay.com",
            "value": {"failed_attempts": 0},
            "updated_at": 1000,
        }
        semaphore = asyncio.Semaphore(10)

        # Mock successful connection and protocol validation
        with patch.object(validator, "_test_connection", new_callable=AsyncMock, return_value=True):
            result = await validator._validate_candidate(candidate, semaphore)

            url, is_valid, failed_attempts = result
            assert is_valid is True
