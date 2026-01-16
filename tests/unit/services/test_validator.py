"""
Unit tests for services.validator module.

Tests:
- Configuration models (ValidatorConfig, NetworkConfig, NetworkTypeConfig, BatchConfig)
- Unified network settings (enabled, proxy_url, max_tasks, timeout)
- Validator service initialization and defaults
- Streaming architecture (Producer/Consumer/Workers)
- Batch processing and checkpoints
- Relay validation workflow
- Candidate promotion and failure tracking
- RunStats dataclass
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.brotr import Brotr, BrotrConfig
from models import Relay
from models.relay import NetworkType
from services.validator import (
    BatchConfig,
    CleanupConfig,
    RunStats,
    Validator,
    ValidatorConfig,
)
from utils.network import NetworkConfig, NetworkTypeConfig


# ============================================================================
# Helpers
# ============================================================================


def make_candidate(
    url: str, network: str = "clearnet", failed_attempts: int = 0, score: float = 0.0
) -> dict:
    """Create a mock candidate row for pool.fetch results."""
    return {
        "data_key": url,
        "data": {"failed_attempts": failed_attempts, "network": network},
        "score": score,
    }


def make_candidates(urls: list[str], network: str = "clearnet") -> list[dict]:
    """Create multiple mock candidate rows."""
    return [
        make_candidate(url, network, score=float(i)) for i, url in enumerate(urls)
    ]


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_validator_brotr(mock_brotr: Brotr) -> Brotr:
    """Create a Brotr mock configured for validator tests."""
    mock_batch_config = MagicMock()
    mock_batch_config.max_batch_size = 100
    mock_timeouts_config = MagicMock()
    mock_timeouts_config.query = 30.0
    mock_config = MagicMock(spec=BrotrConfig)
    mock_config.batch = mock_batch_config
    mock_config.timeouts = mock_timeouts_config
    mock_brotr._config = mock_config
    mock_brotr.get_service_data = AsyncMock(return_value=[])
    mock_brotr.upsert_service_data = AsyncMock()
    mock_brotr.delete_service_data = AsyncMock()
    mock_brotr.insert_relays = AsyncMock(return_value=1)

    # Mock pool.fetch for _fetch_candidates_page
    mock_brotr.pool.fetch = AsyncMock(return_value=[])
    # Mock pool.execute for cleanup methods
    mock_brotr.pool.execute = AsyncMock(return_value="DELETE 0")

    return mock_brotr


# ============================================================================
# RunStats Tests
# ============================================================================


class TestRunStats:
    """Tests for RunStats dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        stats = RunStats()
        assert stats.validated == 0
        assert stats.failed == 0
        assert stats.total_candidates == 0
        assert stats.start_time > 0
        assert all(
            stats.by_network[net] == {"validated": 0, "failed": 0}
            for net in NetworkType
        )

    def test_record_valid_result(self) -> None:
        """Test recording a valid result."""
        stats = RunStats()
        stats.record_result(NetworkType.CLEARNET, valid=True)

        assert stats.validated == 1
        assert stats.failed == 0
        assert stats.by_network[NetworkType.CLEARNET]["validated"] == 1

    def test_record_failed_result(self) -> None:
        """Test recording a failed result."""
        stats = RunStats()
        stats.record_result(NetworkType.TOR, valid=False)

        assert stats.validated == 0
        assert stats.failed == 1
        assert stats.by_network[NetworkType.TOR]["failed"] == 1

    def test_get_active_networks_filters_inactive(self) -> None:
        """Test get_active_networks only returns networks with activity."""
        stats = RunStats()
        stats.record_result(NetworkType.CLEARNET, valid=True)
        stats.record_result(NetworkType.TOR, valid=False)

        active = stats.get_active_networks()
        assert "clearnet" in active
        assert "tor" in active
        assert "i2p" not in active
        assert "loki" not in active

    def test_elapsed_property(self) -> None:
        """Test elapsed property calculates duration."""
        stats = RunStats()
        # elapsed should be very small but positive
        assert stats.elapsed >= 0
        assert stats.elapsed < 1.0


# ============================================================================
# NetworkTypeConfig Tests
# ============================================================================


class TestNetworkTypeConfig:
    """Tests for NetworkTypeConfig."""

    def test_default_values(self) -> None:
        """Test default values."""
        settings = NetworkTypeConfig()
        assert settings.enabled is True
        assert settings.proxy_url is None
        assert settings.max_tasks == 10
        assert settings.timeout == 10.0

    def test_custom_values(self) -> None:
        """Test custom values."""
        settings = NetworkTypeConfig(
            enabled=True,
            proxy_url="socks5://127.0.0.1:9050",
            max_tasks=50,
            timeout=30.0,
        )
        assert settings.enabled is True
        assert settings.proxy_url == "socks5://127.0.0.1:9050"
        assert settings.max_tasks == 50
        assert settings.timeout == 30.0

    def test_max_tasks_bounds(self) -> None:
        """Test max_tasks validation bounds."""
        with pytest.raises(ValueError):
            NetworkTypeConfig(max_tasks=0)

        with pytest.raises(ValueError):
            NetworkTypeConfig(max_tasks=201)

        # Valid edge cases
        assert NetworkTypeConfig(max_tasks=1).max_tasks == 1
        assert NetworkTypeConfig(max_tasks=200).max_tasks == 200

    def test_timeout_bounds(self) -> None:
        """Test timeout validation bounds."""
        with pytest.raises(ValueError):
            NetworkTypeConfig(timeout=0.5)

        with pytest.raises(ValueError):
            NetworkTypeConfig(timeout=121.0)

        # Valid edge cases
        assert NetworkTypeConfig(timeout=1.0).timeout == 1.0
        assert NetworkTypeConfig(timeout=120.0).timeout == 120.0


# ============================================================================
# NetworkConfig Tests
# ============================================================================


class TestNetworkConfig:
    """Tests for NetworkConfig."""

    def test_default_values(self) -> None:
        """Test default network-aware settings."""
        config = NetworkConfig()

        # Clearnet: high concurrency, short timeout, no proxy
        assert config.clearnet.enabled is True
        assert config.clearnet.proxy_url is None
        assert config.clearnet.max_tasks == 50
        assert config.clearnet.timeout == 10.0

        # Tor: lower concurrency, longer timeout, proxy
        assert config.tor.enabled is True
        assert config.tor.proxy_url == "socks5://tor:9050"
        assert config.tor.max_tasks == 10
        assert config.tor.timeout == 30.0

        # I2P: lowest concurrency, longest timeout, proxy
        assert config.i2p.enabled is True
        assert config.i2p.proxy_url == "socks5://i2p:4447"
        assert config.i2p.max_tasks == 5
        assert config.i2p.timeout == 45.0

        # Loki: disabled by default
        assert config.loki.enabled is False
        assert config.loki.proxy_url == "socks5://lokinet:1080"

    def test_custom_values(self) -> None:
        """Test custom network settings."""
        config = NetworkConfig(
            clearnet=NetworkTypeConfig(max_tasks=100, timeout=5.0),
            tor=NetworkTypeConfig(
                enabled=True,
                proxy_url="socks5://custom:9050",
                max_tasks=20,
                timeout=60.0,
            ),
        )
        assert config.clearnet.max_tasks == 100
        assert config.clearnet.timeout == 5.0
        assert config.tor.proxy_url == "socks5://custom:9050"
        assert config.tor.max_tasks == 20
        assert config.tor.timeout == 60.0

    def test_get_settings_for_network(self) -> None:
        """Test get method returns correct settings for network type."""
        config = NetworkConfig(
            clearnet=NetworkTypeConfig(max_tasks=50, timeout=10.0),
            tor=NetworkTypeConfig(
                proxy_url="socks5://tor:9050",
                max_tasks=10,
                timeout=30.0,
            ),
        )

        clearnet = config.get(NetworkType.CLEARNET)
        assert clearnet.max_tasks == 50
        assert clearnet.timeout == 10.0

        tor = config.get(NetworkType.TOR)
        assert tor.max_tasks == 10
        assert tor.timeout == 30.0

    def test_get_enabled_networks(self) -> None:
        """Test get_enabled_networks method."""
        config = NetworkConfig(
            clearnet=NetworkTypeConfig(enabled=True),
            tor=NetworkTypeConfig(enabled=True),
            i2p=NetworkTypeConfig(enabled=False),
            loki=NetworkTypeConfig(enabled=False),
        )

        enabled = config.get_enabled_networks()
        assert "clearnet" in enabled
        assert "tor" in enabled
        assert "i2p" not in enabled
        assert "loki" not in enabled


# ============================================================================
# BatchConfig Tests
# ============================================================================


class TestBatchConfig:
    """Tests for BatchConfig."""

    def test_default_values(self) -> None:
        """Test default batch values."""
        config = BatchConfig()
        assert config.fetch_size == 500
        assert config.write_size == 100
        assert config.max_pending == 500

    def test_custom_values(self) -> None:
        """Test custom batch values."""
        config = BatchConfig(fetch_size=1000, write_size=50, max_pending=300)
        assert config.fetch_size == 1000
        assert config.write_size == 50
        assert config.max_pending == 300

    def test_fetch_size_bounds(self) -> None:
        """Test fetch_size validation bounds."""
        with pytest.raises(ValueError):
            BatchConfig(fetch_size=50)  # Below 100

        with pytest.raises(ValueError):
            BatchConfig(fetch_size=6000)  # Above 5000

    def test_write_size_bounds(self) -> None:
        """Test write_size validation bounds."""
        with pytest.raises(ValueError):
            BatchConfig(write_size=5)  # Below 10

        with pytest.raises(ValueError):
            BatchConfig(write_size=600)  # Above 500

    def test_max_pending_bounds(self) -> None:
        """Test max_pending validation bounds."""
        with pytest.raises(ValueError):
            BatchConfig(max_pending=30)  # Below 50

        with pytest.raises(ValueError):
            BatchConfig(max_pending=6000)  # Above 5000


# ============================================================================
# ValidatorConfig Tests
# ============================================================================


class TestValidatorConfig:
    """Tests for ValidatorConfig."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = ValidatorConfig()

        assert config.interval == 300.0
        assert config.networks.clearnet.max_tasks == 50
        assert config.networks.tor.timeout == 30.0
        assert config.networks.tor.proxy_url == "socks5://tor:9050"
        assert config.batch.fetch_size == 500
        assert config.cleanup.enabled is False

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = ValidatorConfig(
            interval=600.0,
            networks=NetworkConfig(
                clearnet=NetworkTypeConfig(max_tasks=100, timeout=15.0)
            ),
            batch=BatchConfig(fetch_size=1000, write_size=200),
        )

        assert config.interval == 600.0
        assert config.networks.clearnet.max_tasks == 100
        assert config.networks.clearnet.timeout == 15.0
        assert config.batch.fetch_size == 1000
        assert config.batch.write_size == 200

    def test_interval_minimum(self) -> None:
        """Test interval minimum constraint."""
        with pytest.raises(ValueError):
            ValidatorConfig(interval=30.0)


# ============================================================================
# Validator Service Tests
# ============================================================================


class TestValidator:
    """Tests for Validator service."""

    def test_init_default_config(self, mock_validator_brotr: Brotr) -> None:
        """Test initialization with default config."""
        validator = Validator(brotr=mock_validator_brotr)

        assert validator._config.interval == 300.0
        assert validator._config.networks.clearnet.max_tasks == 50
        assert validator._config.networks.tor.timeout == 30.0

    def test_init_custom_config(self, mock_validator_brotr: Brotr) -> None:
        """Test initialization with custom config."""
        config = ValidatorConfig(
            interval=600.0,
            networks=NetworkConfig(
                clearnet=NetworkTypeConfig(max_tasks=100, timeout=20.0)
            ),
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)

        assert validator._config.interval == 600.0
        assert validator._config.networks.clearnet.max_tasks == 100
        assert validator._config.networks.clearnet.timeout == 20.0


# ============================================================================
# Validator Run Tests
# ============================================================================


class TestValidatorRun:
    """Tests for Validator.run() method."""

    @pytest.mark.asyncio
    async def test_run_with_no_candidates(self, mock_validator_brotr: Brotr) -> None:
        """Test run completes successfully with no candidates."""
        validator = Validator(brotr=mock_validator_brotr)
        await validator.run()

        assert validator._stats.validated == 0
        assert validator._stats.failed == 0

    @pytest.mark.asyncio
    async def test_cleanup_promoted_candidates_called(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Test cleanup of promoted candidates is called."""
        mock_validator_brotr.pool.execute = AsyncMock(return_value="DELETE 5")

        validator = Validator(brotr=mock_validator_brotr)
        await validator.run()

        mock_validator_brotr.pool.execute.assert_called()

    @pytest.mark.asyncio
    async def test_run_validates_candidates(self, mock_validator_brotr: Brotr) -> None:
        """Test run validates candidates from database."""
        mock_validator_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [
                    make_candidate("wss://relay1.com", failed_attempts=0, score=0.0),
                    make_candidate("wss://relay2.com", failed_attempts=1, score=1.0),
                ],
                [],
            ]
        )

        config = ValidatorConfig(
            batch=BatchConfig(fetch_size=100, write_size=10),
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)

        async def mock_is_nostr_relay(relay, proxy_url, timeout):
            return "relay1" in relay.url

        with patch(
            "services.validator.is_nostr_relay", side_effect=mock_is_nostr_relay
        ):
            await validator.run()

        assert validator._stats.validated == 1
        assert validator._stats.failed == 1


# ============================================================================
# Producer/Consumer Architecture Tests
# ============================================================================


class TestValidatorArchitecture:
    """Tests for streaming architecture (Producer/Consumer/Workers)."""

    @pytest.mark.asyncio
    async def test_producer_fetches_in_pages(self, mock_validator_brotr: Brotr) -> None:
        """Test producer fetches candidates in pages."""
        mock_validator_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [
                    make_candidate(f"wss://relay{i}.com", score=float(i))
                    for i in range(100)
                ],
                [
                    make_candidate(f"wss://relay{i+100}.com", score=float(i + 100))
                    for i in range(50)
                ],
                [],
            ]
        )

        config = ValidatorConfig(
            batch=BatchConfig(fetch_size=100, write_size=50),
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)

        with patch(
            "services.validator.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await validator.run()

        assert validator._stats.validated == 150

    @pytest.mark.asyncio
    async def test_consumer_flushes_at_write_size(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Test consumer flushes batches at write_size threshold."""
        mock_validator_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [
                    make_candidate(f"wss://relay{i}.com", score=float(i))
                    for i in range(250)
                ],
                [],
            ]
        )

        config = ValidatorConfig(
            batch=BatchConfig(fetch_size=500, write_size=100),
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)

        with patch(
            "services.validator.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await validator.run()

        assert mock_validator_brotr.insert_relays.call_count >= 2

    @pytest.mark.asyncio
    async def test_backpressure_with_bounded_pending(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Test backpressure works with bounded pending tasks."""
        mock_validator_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [
                    make_candidate(f"wss://relay{i}.com", score=float(i))
                    for i in range(300)
                ],
                [],
            ]
        )

        config = ValidatorConfig(
            batch=BatchConfig(fetch_size=500, write_size=100, max_pending=50),
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)

        async def slow_validation(relay, proxy_url, timeout):
            await asyncio.sleep(0.001)
            return True

        with patch("services.validator.is_nostr_relay", side_effect=slow_validation):
            await validator.run()

        assert validator._stats.validated == 300


# ============================================================================
# Network-Aware Validation Tests
# ============================================================================


class TestNetworkAwareValidation:
    """Tests for network-aware concurrency and timeouts."""

    @pytest.mark.asyncio
    async def test_clearnet_uses_clearnet_timeout(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Test clearnet relays use clearnet timeout."""
        mock_validator_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate("wss://clearnet.relay.com", score=0.0)],
                [],
            ]
        )

        config = ValidatorConfig(
            networks=NetworkConfig(
                clearnet=NetworkTypeConfig(max_tasks=50, timeout=10.0),
                tor=NetworkTypeConfig(
                    proxy_url="socks5://tor:9050", max_tasks=10, timeout=30.0
                ),
            ),
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)

        timeout_used = None

        async def capture_timeout(relay, proxy_url, timeout):
            nonlocal timeout_used
            timeout_used = timeout
            return True

        with patch("services.validator.is_nostr_relay", side_effect=capture_timeout):
            await validator.run()

        assert timeout_used == 10.0

    @pytest.mark.asyncio
    async def test_tor_uses_tor_timeout(self, mock_validator_brotr: Brotr) -> None:
        """Test Tor relays use Tor timeout."""
        mock_validator_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate("ws://tortest.onion", network="tor", score=0.0)],
                [],
            ]
        )

        config = ValidatorConfig(
            networks=NetworkConfig(
                clearnet=NetworkTypeConfig(max_tasks=50, timeout=10.0),
                tor=NetworkTypeConfig(
                    enabled=True,
                    proxy_url="socks5://127.0.0.1:9050",
                    max_tasks=10,
                    timeout=30.0,
                ),
            ),
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)

        timeout_used = None

        async def capture_timeout(relay, proxy_url, timeout):
            nonlocal timeout_used
            timeout_used = timeout
            return True

        with patch("services.validator.is_nostr_relay", side_effect=capture_timeout):
            await validator.run()

        assert timeout_used == 30.0

    @pytest.mark.asyncio
    async def test_tor_uses_proxy(self, mock_validator_brotr: Brotr) -> None:
        """Test Tor relays use proxy URL."""
        mock_validator_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate("ws://tortest.onion", network="tor", score=0.0)],
                [],
            ]
        )

        config = ValidatorConfig(
            networks=NetworkConfig(
                tor=NetworkTypeConfig(
                    enabled=True,
                    proxy_url="socks5://127.0.0.1:9050",
                    max_tasks=10,
                    timeout=30.0,
                ),
            ),
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)

        proxy_used = None

        async def capture_proxy(relay, proxy_url, timeout):
            nonlocal proxy_used
            proxy_used = proxy_url
            return True

        with patch("services.validator.is_nostr_relay", side_effect=capture_proxy):
            await validator.run()

        assert proxy_used == "socks5://127.0.0.1:9050"

    @pytest.mark.asyncio
    async def test_clearnet_uses_no_proxy(self, mock_validator_brotr: Brotr) -> None:
        """Test clearnet relays don't use proxy."""
        mock_validator_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate("wss://clearnet.relay.com", score=0.0)],
                [],
            ]
        )

        validator = Validator(brotr=mock_validator_brotr)

        proxy_used = "not_called"

        async def capture_proxy(relay, proxy_url, timeout):
            nonlocal proxy_used
            proxy_used = proxy_url
            return True

        with patch("services.validator.is_nostr_relay", side_effect=capture_proxy):
            await validator.run()

        assert proxy_used is None


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestValidatorErrorHandling:
    """Tests for Validator error handling."""

    @pytest.mark.asyncio
    async def test_validation_exception_handled(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Test validation exceptions are handled gracefully."""
        mock_validator_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate("wss://error.relay.com", score=0.0)],
                [],
            ]
        )

        validator = Validator(brotr=mock_validator_brotr)

        async def raise_error(relay, proxy_url, timeout):
            raise Exception("Connection failed")

        with patch("services.validator.is_nostr_relay", side_effect=raise_error):
            await validator.run()

        assert validator._stats.failed == 1

    @pytest.mark.asyncio
    async def test_database_error_during_flush_logged(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Test database errors during flush are logged but don't crash."""
        mock_validator_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate("wss://relay.com", score=0.0)],
                [],
            ]
        )
        mock_validator_brotr.insert_relays = AsyncMock(side_effect=Exception("DB error"))

        validator = Validator(brotr=mock_validator_brotr)

        with patch(
            "services.validator.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await validator.run()

    @pytest.mark.asyncio
    async def test_all_candidates_fail_validation(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Test all candidates failing validation."""
        mock_validator_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [
                    make_candidate("wss://fail1.com", failed_attempts=0, score=0.0),
                    make_candidate("wss://fail2.com", failed_attempts=1, score=1.0),
                ],
                [],
            ]
        )

        validator = Validator(brotr=mock_validator_brotr)

        with patch(
            "services.validator.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await validator.run()

        assert validator._stats.validated == 0
        assert validator._stats.failed == 2
        mock_validator_brotr.upsert_service_data.assert_called()

    @pytest.mark.asyncio
    async def test_graceful_shutdown(self, mock_validator_brotr: Brotr) -> None:
        """Test graceful shutdown during validation."""
        mock_validator_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [
                    make_candidate(f"wss://relay{i}.com", score=float(i))
                    for i in range(100)
                ],
                [],
            ]
        )

        validator = Validator(brotr=mock_validator_brotr)

        async def slow_validation(relay, proxy_url, timeout):
            await asyncio.sleep(0.1)
            return True

        with patch("services.validator.is_nostr_relay", side_effect=slow_validation):
            task = asyncio.create_task(validator.run())
            await asyncio.sleep(0.05)
            validator.request_shutdown()
            await task


# ============================================================================
# Persistence Tests
# ============================================================================


class TestPersistence:
    """Tests for result persistence methods."""

    @pytest.mark.asyncio
    async def test_valid_relays_inserted_and_candidates_deleted(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Test valid relays are inserted and candidates deleted."""
        mock_validator_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate("wss://valid.relay.com", score=0.0)],
                [],
            ]
        )

        validator = Validator(brotr=mock_validator_brotr)

        with patch(
            "services.validator.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await validator.run()

        mock_validator_brotr.insert_relays.assert_called()
        mock_validator_brotr.delete_service_data.assert_called()

    @pytest.mark.asyncio
    async def test_failed_attempts_incremented(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Test failed attempts are incremented for failed validations."""
        mock_validator_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [
                    make_candidate(
                        "wss://failing.relay.com", failed_attempts=3, score=30.0
                    )
                ],
                [],
            ]
        )

        validator = Validator(brotr=mock_validator_brotr)

        with patch(
            "services.validator.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await validator.run()

        mock_validator_brotr.upsert_service_data.assert_called()
        call_args = mock_validator_brotr.upsert_service_data.call_args[0][0]
        assert call_args[0][3]["failed_attempts"] == 4


# ============================================================================
# Cleanup Tests
# ============================================================================


class TestValidatorCleanup:
    """Tests for cleanup methods."""

    @pytest.mark.asyncio
    async def test_cleanup_promoted_candidates(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Test cleanup of candidates already in relays table."""
        mock_validator_brotr.pool.execute = AsyncMock(return_value="DELETE 5")

        validator = Validator(brotr=mock_validator_brotr)
        await validator._cleanup_promoted_candidates()

        # Verify execute was called with correct query pattern
        call_args = mock_validator_brotr.pool.execute.call_args
        assert "DELETE FROM service_data" in call_args[0][0]
        assert "data_key IN (SELECT url FROM relays)" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_cleanup_exhausted_candidates_when_enabled(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Test cleanup of exhausted candidates when enabled."""
        mock_validator_brotr.pool.execute = AsyncMock(return_value="DELETE 3")

        config = ValidatorConfig(cleanup=CleanupConfig(enabled=True, max_attempts=10))
        validator = Validator(brotr=mock_validator_brotr, config=config)
        await validator._cleanup_exhausted_candidates()

        # Verify execute was called with correct query pattern
        call_args = mock_validator_brotr.pool.execute.call_args
        assert "DELETE FROM service_data" in call_args[0][0]
        assert "failed_attempts" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_cleanup_exhausted_not_called_when_disabled(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Test cleanup of exhausted candidates not called when disabled."""
        config = ValidatorConfig(cleanup=CleanupConfig(enabled=False))
        validator = Validator(brotr=mock_validator_brotr, config=config)

        mock_validator_brotr.pool.execute.reset_mock()
        mock_validator_brotr.pool.execute.return_value = "DELETE 0"

        await validator.run()

        # Only one cleanup call (promoted candidates, not exhausted)
        calls = mock_validator_brotr.pool.execute.call_args_list
        assert len(calls) == 1
