"""
Unit tests for the Validator service.

Tests cover:
- ValidatorConfig validation
- Validator initialization and run cycle
- Chunk-based processing
- Network-aware validation (timeouts, proxies)
- Error handling and graceful shutdown
- Persistence (valid relays, invalid candidates)
- Cleanup of promoted and exhausted candidates
- Prometheus metrics integration
"""

from unittest.mock import AsyncMock, patch

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceStateType
from bigbrotr.services.common.configs import (
    ClearnetConfig,
    I2pConfig,
    LokiConfig,
    NetworksConfig,
    TorConfig,
)
from bigbrotr.services.validator import (
    CleanupConfig,
    ProcessingConfig,
    Validator,
    ValidatorConfig,
)


# ============================================================================
# Helpers
# ============================================================================


def make_candidate_row(url: str, network: str = "clearnet", failures: int = 0) -> dict:
    """Create a mock candidate row from database."""
    return {
        "service_name": "validator",
        "state_type": "candidate",
        "state_key": url,
        "state_value": {"network": network, "failures": failures},
        "updated_at": 1700000000,
    }


@pytest.fixture
def mock_validator_brotr(mock_brotr: Brotr) -> Brotr:
    """Create a mock Brotr instance for validator tests."""
    # Mock additional methods needed by Validator
    mock_brotr.insert_relay = AsyncMock()
    mock_brotr.delete_service_state = AsyncMock()
    mock_brotr.upsert_service_state = AsyncMock()
    return mock_brotr


# ============================================================================
# ProcessingConfig Tests
# ============================================================================


class TestProcessingConfig:
    """Tests for ProcessingConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default processing configuration."""
        config = ProcessingConfig()
        assert config.chunk_size == 100
        assert config.max_candidates is None

    def test_custom_values(self) -> None:
        """Test custom processing configuration."""
        config = ProcessingConfig(chunk_size=200, max_candidates=1000)
        assert config.chunk_size == 200
        assert config.max_candidates == 1000

    def test_chunk_size_bounds(self) -> None:
        """Test chunk_size validation bounds."""
        # Valid values
        config_min = ProcessingConfig(chunk_size=10)
        assert config_min.chunk_size == 10

        config_max = ProcessingConfig(chunk_size=1000)
        assert config_max.chunk_size == 1000

        # Below minimum
        with pytest.raises(ValueError):
            ProcessingConfig(chunk_size=5)

        # Above maximum
        with pytest.raises(ValueError):
            ProcessingConfig(chunk_size=2000)

    def test_max_candidates_none(self) -> None:
        """Test max_candidates can be None (unlimited)."""
        config = ProcessingConfig(max_candidates=None)
        assert config.max_candidates is None


# ============================================================================
# CleanupConfig Tests
# ============================================================================


class TestCleanupConfig:
    """Tests for CleanupConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default cleanup configuration."""
        config = CleanupConfig()
        assert config.enabled is False
        assert config.max_failures == 100

    def test_custom_values(self) -> None:
        """Test custom cleanup configuration."""
        config = CleanupConfig(enabled=True, max_failures=5)
        assert config.enabled is True
        assert config.max_failures == 5

    def test_max_failures_bounds(self) -> None:
        """Test max_failures validation bounds."""
        # Valid values
        config_min = CleanupConfig(max_failures=1)
        assert config_min.max_failures == 1

        config_max = CleanupConfig(max_failures=1000)
        assert config_max.max_failures == 1000

        # Below minimum
        with pytest.raises(ValueError):
            CleanupConfig(max_failures=0)


# ============================================================================
# ValidatorConfig Tests
# ============================================================================


class TestValidatorConfig:
    """Tests for ValidatorConfig."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = ValidatorConfig()

        assert config.interval == 300.0
        assert config.processing.chunk_size == 100
        assert config.processing.max_candidates is None
        assert config.cleanup.enabled is False
        assert config.cleanup.max_failures == 100
        assert config.networks.clearnet.max_tasks == 50

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = ValidatorConfig(
            interval=600.0,
            processing={"chunk_size": 200, "max_candidates": 1000},
            cleanup={"enabled": True, "max_failures": 5},
        )

        assert config.interval == 600.0
        assert config.processing.chunk_size == 200
        assert config.processing.max_candidates == 1000
        assert config.cleanup.enabled is True
        assert config.cleanup.max_failures == 5

    def test_chunk_size_bounds(self) -> None:
        """Test chunk_size validation bounds."""
        with pytest.raises(ValueError):
            ValidatorConfig(processing={"chunk_size": 5})  # Below 10

        with pytest.raises(ValueError):
            ValidatorConfig(processing={"chunk_size": 2000})  # Above 1000

    def test_interval_minimum(self) -> None:
        """Test interval minimum constraint."""
        with pytest.raises(ValueError):
            ValidatorConfig(interval=30.0)

    def test_networks_config(self) -> None:
        """Test networks configuration."""
        config = ValidatorConfig(
            networks=NetworksConfig(
                clearnet=ClearnetConfig(max_tasks=100),
                tor=TorConfig(enabled=True, max_tasks=10),
            )
        )
        assert config.networks.clearnet.max_tasks == 100
        assert config.networks.tor.enabled is True
        assert config.networks.tor.max_tasks == 10


# ============================================================================
# Validator Initialization Tests
# ============================================================================


class TestValidator:
    """Tests for Validator initialization."""

    def test_init_default_config(self, mock_validator_brotr: Brotr) -> None:
        """Test validator with default config."""
        validator = Validator(brotr=mock_validator_brotr)

        assert validator._config.interval == 300.0
        assert validator._config.processing.chunk_size == 100

    def test_init_custom_config(self, mock_validator_brotr: Brotr) -> None:
        """Test validator with custom config."""
        config = ValidatorConfig(interval=600.0, processing={"chunk_size": 200})
        validator = Validator(brotr=mock_validator_brotr, config=config)

        assert validator._config.interval == 600.0
        assert validator._config.processing.chunk_size == 200

    def test_service_name(self, mock_validator_brotr: Brotr) -> None:
        """Test service name attribute."""
        validator = Validator(brotr=mock_validator_brotr)
        assert validator.SERVICE_NAME == "validator"

    def test_config_class(self, mock_validator_brotr: Brotr) -> None:
        """Test config class attribute."""
        assert ValidatorConfig == Validator.CONFIG_CLASS


# ============================================================================
# Validator Run Tests
# ============================================================================


class TestValidatorRun:
    """Tests for validator run cycle."""

    async def test_run_with_no_candidates(self, mock_validator_brotr: Brotr) -> None:
        """Test run completes when no candidates exist."""
        validator = Validator(brotr=mock_validator_brotr)
        await validator.run()

        assert validator.chunk_progress.succeeded == 0
        assert validator.chunk_progress.failed == 0

    async def test_cleanup_promoted_called_at_end_of_run(self, mock_validator_brotr: Brotr) -> None:
        """Test cleanup of promoted candidates is called at end of run cycle."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("wss://relay.com")], []]
        )
        mock_validator_brotr._pool.fetchval = AsyncMock(return_value=0)

        validator = Validator(brotr=mock_validator_brotr)

        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await validator.run()

        assert mock_validator_brotr._pool.fetchval.called
        calls = mock_validator_brotr._pool.fetchval.call_args_list
        cleanup_called = any("AND EXISTS" in str(c) and "NOT EXISTS" not in str(c) for c in calls)
        assert cleanup_called

    async def test_run_validates_candidates(self, mock_validator_brotr: Brotr) -> None:
        """Test basic validation flow."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate_row("wss://relay1.com"), make_candidate_row("wss://relay2.com")],
                [],
            ]
        )

        validator = Validator(brotr=mock_validator_brotr)

        async def mock_is_nostr_relay(relay, proxy_url, timeout):
            return "relay1" in relay.url

        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay", side_effect=mock_is_nostr_relay
        ):
            await validator.run()

        assert validator.chunk_progress.succeeded == 1
        assert validator.chunk_progress.failed == 1

    async def test_run_progress_reset(self, mock_validator_brotr: Brotr) -> None:
        """Test progress is reset at start of run."""
        validator = Validator(brotr=mock_validator_brotr)
        validator.chunk_progress.succeeded = 10
        validator.chunk_progress.failed = 5

        await validator.run()

        assert validator.chunk_progress.succeeded == 0
        assert validator.chunk_progress.failed == 0


# ============================================================================
# Chunk Processing Tests
# ============================================================================


class TestChunkProcessing:
    """Tests for chunk-based processing."""

    async def test_loads_chunks_until_empty(self, mock_validator_brotr: Brotr) -> None:
        """Test validator loads chunks until no more candidates."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate_row(f"wss://relay{i}.com") for i in range(100)],
                [make_candidate_row(f"wss://relay{i + 100}.com") for i in range(50)],
                [],
            ]
        )

        config = ValidatorConfig(processing={"chunk_size": 100})
        validator = Validator(brotr=mock_validator_brotr, config=config)

        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await validator.run()

        assert validator.chunk_progress.succeeded == 150

    async def test_respects_max_candidates_limit(self, mock_validator_brotr: Brotr) -> None:
        """Test validator respects max_candidates limit."""

        def mock_fetch(query, *args, timeout=None):
            # args order: (service_name, data_type, networks, run_start_ts, limit)
            limit = args[4] if len(args) > 4 else 100
            if limit <= 0:
                return []
            if not hasattr(mock_fetch, "_call_count"):
                mock_fetch._call_count = 0
            mock_fetch._call_count += 1

            if mock_fetch._call_count == 1:
                return [make_candidate_row(f"wss://relay{i}.com") for i in range(min(limit, 100))]
            if mock_fetch._call_count == 2:
                return [
                    make_candidate_row(f"wss://relay{i + 100}.com") for i in range(min(limit, 100))
                ]
            return []

        mock_validator_brotr._pool.fetch = AsyncMock(side_effect=mock_fetch)

        config = ValidatorConfig(processing={"chunk_size": 100, "max_candidates": 150})
        validator = Validator(brotr=mock_validator_brotr, config=config)

        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await validator.run()

        assert validator.chunk_progress.succeeded == 150


# ============================================================================
# Network-Aware Validation Tests
# ============================================================================


class TestNetworkAwareValidation:
    """Tests for network-specific validation behavior."""

    async def test_clearnet_uses_clearnet_timeout(self, mock_validator_brotr: Brotr) -> None:
        """Test clearnet relays use clearnet timeout."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("wss://relay.com", network="clearnet")], []]
        )

        config = ValidatorConfig(
            networks=NetworksConfig(clearnet=ClearnetConfig(timeout=5.0, max_tasks=10))
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)

        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock:
            await validator.run()
            mock.assert_called_once()
            _, _, timeout = mock.call_args[0]
            assert timeout == 5.0

    async def test_tor_uses_tor_timeout(self, mock_validator_brotr: Brotr) -> None:
        """Test Tor relays use Tor timeout."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("ws://onion.onion", network="tor")], []]
        )

        config = ValidatorConfig(networks=NetworksConfig(tor=TorConfig(timeout=45.0, max_tasks=5)))
        validator = Validator(brotr=mock_validator_brotr, config=config)

        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock:
            await validator.run()
            mock.assert_called_once()
            _, _, timeout = mock.call_args[0]
            assert timeout == 45.0

    async def test_tor_uses_proxy(self, mock_validator_brotr: Brotr) -> None:
        """Test Tor relays use proxy URL."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("ws://onion.onion", network="tor")], []]
        )

        config = ValidatorConfig(
            networks=NetworksConfig(tor=TorConfig(enabled=True, proxy_url="socks5://tor:9050"))
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)

        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock:
            await validator.run()
            mock.assert_called_once()
            _, proxy_url, _ = mock.call_args[0]
            assert proxy_url == "socks5://tor:9050"

    async def test_clearnet_uses_no_proxy(self, mock_validator_brotr: Brotr) -> None:
        """Test clearnet relays don't use proxy."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("wss://relay.com", network="clearnet")], []]
        )

        validator = Validator(brotr=mock_validator_brotr)

        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock:
            await validator.run()
            mock.assert_called_once()
            _, proxy_url, _ = mock.call_args[0]
            assert proxy_url is None

    async def test_i2p_uses_i2p_settings(self, mock_validator_brotr: Brotr) -> None:
        """Test I2P relays use I2P timeout and proxy."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("ws://test.i2p", network="i2p")], []]
        )

        config = ValidatorConfig(
            networks=NetworksConfig(
                i2p=I2pConfig(enabled=True, timeout=60.0, proxy_url="socks5://i2p:4447")
            )
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)

        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock:
            await validator.run()
            mock.assert_called_once()
            _, proxy_url, timeout = mock.call_args[0]
            assert proxy_url == "socks5://i2p:4447"
            assert timeout == 60.0

    async def test_lokinet_uses_lokinet_settings(self, mock_validator_brotr: Brotr) -> None:
        """Test Lokinet relays use Lokinet timeout and proxy."""
        mock_validator_brotr._pool._mock_connection.fetch = AsyncMock(
            side_effect=[[make_candidate_row("ws://test.loki", network="loki")], []]
        )

        config = ValidatorConfig(
            networks=NetworksConfig(
                loki=LokiConfig(enabled=True, timeout=30.0, proxy_url="socks5://loki:1080")
            )
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)

        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock:
            await validator.run()
            mock.assert_called_once()
            _, proxy_url, timeout = mock.call_args[0]
            assert proxy_url == "socks5://loki:1080"
            assert timeout == 30.0


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    async def test_validation_exception_handled(self, mock_validator_brotr: Brotr) -> None:
        """Test exceptions during validation are handled."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("wss://relay.com")], []]
        )

        validator = Validator(brotr=mock_validator_brotr)

        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            side_effect=Exception("Connection error"),
        ):
            await validator.run()

        assert validator.chunk_progress.succeeded == 0
        assert validator.chunk_progress.failed == 1

    async def test_database_error_during_persist_logged(self, mock_validator_brotr: Brotr) -> None:
        """Test database errors during persist are logged."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("wss://relay.com")], []]
        )
        mock_validator_brotr.upsert_service_state = AsyncMock(side_effect=OSError("DB error"))

        validator = Validator(brotr=mock_validator_brotr)

        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await validator.run()

        assert validator.chunk_progress.failed == 1

    async def test_all_candidates_fail_validation(self, mock_validator_brotr: Brotr) -> None:
        """Test run completes when all validations fail."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row(f"wss://relay{i}.com") for i in range(10)], []]
        )

        validator = Validator(brotr=mock_validator_brotr)

        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await validator.run()

        assert validator.chunk_progress.succeeded == 0
        assert validator.chunk_progress.failed == 10

    async def test_graceful_shutdown(self, mock_validator_brotr: Brotr) -> None:
        """Test is_running flag controls processing loop."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate_row(f"wss://relay{i}.com") for i in range(10)],
                [],
            ]
        )

        validator = Validator(brotr=mock_validator_brotr)

        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await validator.run()

        total = validator.chunk_progress.succeeded + validator.chunk_progress.failed
        assert total == 10

        # Test stopping via is_running
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate_row(f"wss://relay{i}.com") for i in range(10)],
                [],
            ]
        )
        validator2 = Validator(brotr=mock_validator_brotr)
        validator2.request_shutdown()
        await validator2.run()

        assert validator2.is_running is False


# ============================================================================
# Persistence Tests
# ============================================================================


class TestPersistence:
    """Tests for result persistence."""

    async def test_valid_relays_inserted_and_candidates_deleted(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Test valid relays are inserted and candidates removed."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("wss://valid.relay.com")], []]
        )
        mock_validator_brotr.insert_relay = AsyncMock(return_value=1)  # type: ignore[method-assign]
        mock_validator_brotr.delete_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

        validator = Validator(brotr=mock_validator_brotr)

        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await validator.run()

        mock_validator_brotr.insert_relay.assert_awaited_once()
        relays = mock_validator_brotr.insert_relay.call_args[0][0]
        assert len(relays) == 1
        assert relays[0].url == "wss://valid.relay.com"

        mock_validator_brotr.delete_service_state.assert_awaited_once()
        delete_args = mock_validator_brotr.delete_service_state.call_args
        assert delete_args[0][0] == [ServiceName.VALIDATOR]
        assert delete_args[0][1] == [ServiceStateType.CANDIDATE]
        assert delete_args[0][2] == ["wss://valid.relay.com"]

    async def test_invalid_candidates_failures_incremented(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Test invalid candidates have failures incremented."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("wss://invalid.relay.com", failures=2)], []]
        )

        validator = Validator(brotr=mock_validator_brotr)

        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await validator.run()

        mock_validator_brotr.upsert_service_state.assert_called_once()
        call_args = mock_validator_brotr.upsert_service_state.call_args[0][0]
        assert call_args[0].state_value["failures"] == 3

    async def test_invalid_candidates_preserve_data_fields(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Test invalid candidates preserve all data fields (network, etc)."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate_row("wss://invalid.relay.com", network="tor", failures=1)],
                [],
            ]
        )

        validator = Validator(brotr=mock_validator_brotr)

        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await validator.run()

        mock_validator_brotr.upsert_service_state.assert_called_once()
        call_args = mock_validator_brotr.upsert_service_state.call_args[0][0]
        data = call_args[0].state_value
        assert data["failures"] == 2
        assert data["network"] == "tor"  # Preserved from original data


# ============================================================================
# Cleanup Tests
# ============================================================================


class TestCleanup:
    """Tests for cleanup operations."""

    async def test_cleanup_stale(self, mock_validator_brotr: Brotr) -> None:
        """Test stale candidates (already in relays) are cleaned up."""
        mock_validator_brotr._pool.fetchval = AsyncMock(return_value=5)

        validator = Validator(brotr=mock_validator_brotr)
        await validator.cleanup_stale()

        mock_validator_brotr._pool.fetchval.assert_called_once()
        call_args = mock_validator_brotr._pool.fetchval.call_args[0]
        query = call_args[0]
        assert "DELETE FROM service_state" in query
        assert "AND EXISTS" in query
        assert "NOT EXISTS" not in query
        assert call_args[1] == ServiceName.VALIDATOR
        assert call_args[2] == ServiceStateType.CANDIDATE

    async def test_cleanup_exhausted_when_enabled(self, mock_validator_brotr: Brotr) -> None:
        """Test exhausted candidates are cleaned up when enabled."""
        mock_validator_brotr._pool.fetchval = AsyncMock(return_value=3)

        config = ValidatorConfig(cleanup={"enabled": True, "max_failures": 5})
        validator = Validator(brotr=mock_validator_brotr, config=config)
        await validator.cleanup_exhausted()

        mock_validator_brotr._pool.fetchval.assert_called_once()
        call_args = mock_validator_brotr._pool.fetchval.call_args
        assert call_args[0][3] == 5  # max_failures threshold

    async def test_cleanup_exhausted_not_called_when_disabled(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Test exhausted cleanup is skipped when disabled."""
        mock_validator_brotr._pool._mock_connection.fetchval = AsyncMock(return_value=0)

        config = ValidatorConfig(cleanup={"enabled": False})
        validator = Validator(brotr=mock_validator_brotr, config=config)
        await validator.cleanup_exhausted()

        mock_validator_brotr._pool._mock_connection.fetchval.assert_not_called()

    async def test_cleanup_propagates_db_errors(self, mock_validator_brotr: Brotr) -> None:
        """Test cleanup propagates database errors (no internal error handling)."""
        mock_validator_brotr._pool.fetchval = AsyncMock(side_effect=Exception("DB error"))

        validator = Validator(brotr=mock_validator_brotr)
        with pytest.raises(Exception, match="DB error"):
            await validator.cleanup_stale()


# ============================================================================
# Network Configuration Tests
# ============================================================================


class TestNetworkConfiguration:
    """Tests for network configuration via ValidatorConfig.networks."""

    def test_enabled_networks_default(self) -> None:
        """Test default enabled networks via config."""
        config = NetworksConfig()
        enabled = config.get_enabled_networks()
        assert "clearnet" in enabled

    def test_enabled_networks_with_tor(self) -> None:
        """Test enabled networks with Tor enabled."""
        config = NetworksConfig(
            clearnet=ClearnetConfig(enabled=True),
            tor=TorConfig(enabled=True),
        )
        enabled = config.get_enabled_networks()
        assert "clearnet" in enabled
        assert "tor" in enabled

    def test_network_config_for_clearnet(self) -> None:
        """Test getting network config for clearnet."""
        config = NetworksConfig(clearnet=ClearnetConfig(timeout=10.0, max_tasks=25))

        assert config.clearnet.timeout == 10.0
        assert config.clearnet.max_tasks == 25

    def test_network_config_for_tor(self) -> None:
        """Test getting network config for Tor."""
        config = NetworksConfig(
            tor=TorConfig(enabled=True, timeout=60.0, proxy_url="socks5://tor:9050")
        )

        assert config.tor.timeout == 60.0
        assert config.tor.proxy_url == "socks5://tor:9050"


# ============================================================================
# Integration Tests
# ============================================================================


class TestValidatorIntegration:
    """Integration tests for Validator."""

    async def test_full_validation_cycle(self, mock_validator_brotr: Brotr) -> None:
        """Test complete validation cycle with mixed results."""
        mock_validator_brotr._pool._mock_connection.fetch = AsyncMock(
            side_effect=[
                [
                    make_candidate_row("wss://good.relay.com"),
                    make_candidate_row("wss://bad.relay.com"),
                    make_candidate_row("wss://error.relay.com"),
                ],
                [],
            ]
        )

        validator = Validator(brotr=mock_validator_brotr)

        async def mock_validation(relay, proxy, timeout):
            if "good" in relay.url:
                return True
            if "error" in relay.url:
                raise Exception("Connection error")
            return False

        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay", side_effect=mock_validation
        ):
            await validator.run()

        # 1 valid (good), 2 failures (bad + error)
        assert validator.chunk_progress.succeeded == 1
        assert validator.chunk_progress.failed == 2

    async def test_validation_with_multiple_networks(self, mock_validator_brotr: Brotr) -> None:
        """Test validation with candidates from multiple networks."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[
                [
                    make_candidate_row("wss://clearnet.relay.com", network="clearnet"),
                    make_candidate_row("ws://onion.relay.onion", network="tor"),
                ],
                [],
            ]
        )

        config = ValidatorConfig(
            networks=NetworksConfig(
                clearnet=ClearnetConfig(timeout=5.0),
                tor=TorConfig(enabled=True, timeout=30.0, proxy_url="socks5://tor:9050"),
            )
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)

        call_args_list = []

        async def capture_args(relay, proxy, timeout):
            call_args_list.append((relay.url, proxy, timeout))
            return True

        with patch("bigbrotr.services.validator.service.is_nostr_relay", side_effect=capture_args):
            await validator.run()

        # Verify correct timeouts/proxies were used
        clearnet_call = next(c for c in call_args_list if "clearnet" in c[0])
        tor_call = next(c for c in call_args_list if "onion" in c[0])

        assert clearnet_call[1] is None  # No proxy for clearnet
        assert clearnet_call[2] == 5.0

        assert tor_call[1] == "socks5://tor:9050"
        assert tor_call[2] == 30.0


# ============================================================================
# Metrics Tests
# ============================================================================


class TestValidatorMetrics:
    """Tests for Validator Prometheus counter emissions."""

    async def test_promoted_counter_emitted(self, mock_validator_brotr: Brotr) -> None:
        """Promoting valid candidates emits total_promoted counter."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate_row("wss://valid1.com"), make_candidate_row("wss://valid2.com")],
                [],
            ]
        )
        mock_validator_brotr.insert_relay = AsyncMock(return_value=2)

        validator = Validator(brotr=mock_validator_brotr)

        with (
            patch(
                "bigbrotr.services.validator.service.is_nostr_relay",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch.object(validator, "inc_counter") as mock_counter,
        ):
            await validator.run()

        mock_counter.assert_any_call("total_promoted", 2)
