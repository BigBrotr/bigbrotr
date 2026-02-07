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

from core.brotr import Brotr
from services.validator import (
    CleanupConfig,
    ProcessingConfig,
    Validator,
    ValidatorConfig,
)
from utils.network import ClearnetConfig, I2pConfig, LokiConfig, NetworkConfig, TorConfig


# ============================================================================
# Helpers
# ============================================================================


def make_candidate_row(url: str, network: str = "clearnet", failed_attempts: int = 0) -> dict:
    """Create a mock candidate row from database."""
    return {
        "data_key": url,
        "data": {"network": network, "failed_attempts": failed_attempts},
    }


@pytest.fixture
def mock_validator_brotr(mock_brotr: Brotr) -> Brotr:
    """Create a mock Brotr instance for validator tests."""
    # Mock additional methods needed by Validator
    mock_brotr.insert_relays = AsyncMock()
    mock_brotr.delete_service_data = AsyncMock()
    mock_brotr.upsert_service_data = AsyncMock()
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
            networks=NetworkConfig(
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

    @pytest.mark.asyncio
    async def test_run_with_no_candidates(self, mock_validator_brotr: Brotr) -> None:
        """Test run completes when no candidates exist."""
        validator = Validator(brotr=mock_validator_brotr)
        await validator.run()

        assert validator._progress.success == 0
        assert validator._progress.failure == 0

    @pytest.mark.asyncio
    async def test_cleanup_promoted_called_at_end_of_run(self, mock_validator_brotr: Brotr) -> None:
        """Test cleanup of promoted candidates is called at end of run cycle."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("wss://relay.com")], []]
        )
        mock_validator_brotr._pool.execute = AsyncMock(return_value="DELETE 0")

        validator = Validator(brotr=mock_validator_brotr)

        with patch("services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=False):
            await validator.run()

        assert mock_validator_brotr._pool.execute.called
        calls = mock_validator_brotr._pool.execute.call_args_list
        cleanup_called = any("data_key IN (SELECT url FROM relays)" in str(c) for c in calls)
        assert cleanup_called

    @pytest.mark.asyncio
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

        with patch("services.validator.is_nostr_relay", side_effect=mock_is_nostr_relay):
            await validator.run()

        assert validator._progress.success == 1
        assert validator._progress.failure == 1

    @pytest.mark.asyncio
    async def test_run_progress_reset(self, mock_validator_brotr: Brotr) -> None:
        """Test progress is reset at start of run."""
        validator = Validator(brotr=mock_validator_brotr)
        validator._progress.success = 10
        validator._progress.failure = 5

        await validator.run()

        assert validator._progress.success == 0
        assert validator._progress.failure == 0


# ============================================================================
# Chunk Processing Tests
# ============================================================================


class TestChunkProcessing:
    """Tests for chunk-based processing."""

    @pytest.mark.asyncio
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

        with patch("services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=True):
            await validator.run()

        assert validator._progress.success == 150

    @pytest.mark.asyncio
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
            elif mock_fetch._call_count == 2:
                return [
                    make_candidate_row(f"wss://relay{i + 100}.com") for i in range(min(limit, 100))
                ]
            return []

        mock_validator_brotr._pool.fetch = AsyncMock(side_effect=mock_fetch)

        config = ValidatorConfig(processing={"chunk_size": 100, "max_candidates": 150})
        validator = Validator(brotr=mock_validator_brotr, config=config)

        with patch("services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=True):
            await validator.run()

        assert validator._progress.success == 150


# ============================================================================
# Network-Aware Validation Tests
# ============================================================================


class TestNetworkAwareValidation:
    """Tests for network-specific validation behavior."""

    @pytest.mark.asyncio
    async def test_clearnet_uses_clearnet_timeout(self, mock_validator_brotr: Brotr) -> None:
        """Test clearnet relays use clearnet timeout."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("wss://relay.com", network="clearnet")], []]
        )

        config = ValidatorConfig(
            networks=NetworkConfig(clearnet=ClearnetConfig(timeout=5.0, max_tasks=10))
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)

        with patch(
            "services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=True
        ) as mock:
            await validator.run()
            mock.assert_called_once()
            _, _, timeout = mock.call_args[0]
            assert timeout == 5.0

    @pytest.mark.asyncio
    async def test_tor_uses_tor_timeout(self, mock_validator_brotr: Brotr) -> None:
        """Test Tor relays use Tor timeout."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("ws://onion.onion", network="tor")], []]
        )

        config = ValidatorConfig(networks=NetworkConfig(tor=TorConfig(timeout=45.0, max_tasks=5)))
        validator = Validator(brotr=mock_validator_brotr, config=config)

        with patch(
            "services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=True
        ) as mock:
            await validator.run()
            mock.assert_called_once()
            _, _, timeout = mock.call_args[0]
            assert timeout == 45.0

    @pytest.mark.asyncio
    async def test_tor_uses_proxy(self, mock_validator_brotr: Brotr) -> None:
        """Test Tor relays use proxy URL."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("ws://onion.onion", network="tor")], []]
        )

        config = ValidatorConfig(
            networks=NetworkConfig(tor=TorConfig(enabled=True, proxy_url="socks5://tor:9050"))
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)

        with patch(
            "services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=True
        ) as mock:
            await validator.run()
            mock.assert_called_once()
            _, proxy_url, _ = mock.call_args[0]
            assert proxy_url == "socks5://tor:9050"

    @pytest.mark.asyncio
    async def test_clearnet_uses_no_proxy(self, mock_validator_brotr: Brotr) -> None:
        """Test clearnet relays don't use proxy."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("wss://relay.com", network="clearnet")], []]
        )

        validator = Validator(brotr=mock_validator_brotr)

        with patch(
            "services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=True
        ) as mock:
            await validator.run()
            mock.assert_called_once()
            _, proxy_url, _ = mock.call_args[0]
            assert proxy_url is None

    @pytest.mark.asyncio
    async def test_i2p_uses_i2p_settings(self, mock_validator_brotr: Brotr) -> None:
        """Test I2P relays use I2P timeout and proxy."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("ws://test.i2p", network="i2p")], []]
        )

        config = ValidatorConfig(
            networks=NetworkConfig(
                i2p=I2pConfig(enabled=True, timeout=60.0, proxy_url="socks5://i2p:4447")
            )
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)

        with patch(
            "services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=True
        ) as mock:
            await validator.run()
            mock.assert_called_once()
            _, proxy_url, timeout = mock.call_args[0]
            assert proxy_url == "socks5://i2p:4447"
            assert timeout == 60.0

    @pytest.mark.asyncio
    async def test_lokinet_uses_lokinet_settings(self, mock_validator_brotr: Brotr) -> None:
        """Test Lokinet relays use Lokinet timeout and proxy."""
        mock_validator_brotr._pool._mock_connection.fetch = AsyncMock(
            side_effect=[[make_candidate_row("ws://test.loki", network="loki")], []]
        )

        config = ValidatorConfig(
            networks=NetworkConfig(
                loki=LokiConfig(enabled=True, timeout=30.0, proxy_url="socks5://loki:1080")
            )
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)

        with patch(
            "services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=True
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

    @pytest.mark.asyncio
    async def test_validation_exception_handled(self, mock_validator_brotr: Brotr) -> None:
        """Test exceptions during validation are handled."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("wss://relay.com")], []]
        )

        validator = Validator(brotr=mock_validator_brotr)

        with patch(
            "services.validator.is_nostr_relay",
            new_callable=AsyncMock,
            side_effect=Exception("Connection error"),
        ):
            await validator.run()

        assert validator._progress.success == 0
        assert validator._progress.failure == 1

    @pytest.mark.asyncio
    async def test_database_error_during_persist_logged(self, mock_validator_brotr: Brotr) -> None:
        """Test database errors during persist are logged."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("wss://relay.com")], []]
        )
        mock_validator_brotr.upsert_service_data = AsyncMock(side_effect=Exception("DB error"))

        validator = Validator(brotr=mock_validator_brotr)

        with patch("services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=False):
            await validator.run()

        assert validator._progress.failure == 1

    @pytest.mark.asyncio
    async def test_all_candidates_fail_validation(self, mock_validator_brotr: Brotr) -> None:
        """Test run completes when all validations fail."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row(f"wss://relay{i}.com") for i in range(10)], []]
        )

        validator = Validator(brotr=mock_validator_brotr)

        with patch("services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=False):
            await validator.run()

        assert validator._progress.success == 0
        assert validator._progress.failure == 10

    @pytest.mark.asyncio
    async def test_graceful_shutdown(self, mock_validator_brotr: Brotr) -> None:
        """Test is_running flag controls processing loop."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate_row(f"wss://relay{i}.com") for i in range(10)],
                [],
            ]
        )

        validator = Validator(brotr=mock_validator_brotr)

        with patch("services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=True):
            await validator.run()

        total = validator._progress.success + validator._progress.failure
        assert total == 10

        # Test stopping via is_running
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate_row(f"wss://relay{i}.com") for i in range(10)],
                [],
            ]
        )
        validator2 = Validator(brotr=mock_validator_brotr)

        async def mock_process_all(networks):
            validator2._is_running = False

        validator2._process_all = mock_process_all
        await validator2.run()

        assert validator2._is_running is False


# ============================================================================
# Persistence Tests
# ============================================================================


class TestPersistence:
    """Tests for result persistence."""

    @pytest.mark.asyncio
    async def test_valid_relays_inserted_and_candidates_deleted(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Test valid relays are atomically inserted and candidates removed."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("wss://valid.relay.com")], []]
        )

        validator = Validator(brotr=mock_validator_brotr)

        with patch("services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=True):
            await validator.run()

        # Both operations happen on the same connection inside a transaction
        conn = mock_validator_brotr._pool._mock_connection
        # relays_insert called via fetchval
        fetchval_calls = conn.fetchval.call_args_list
        insert_call = [c for c in fetchval_calls if "relays_insert" in str(c)]
        assert len(insert_call) == 1, f"Expected one relays_insert call, got {insert_call}"
        assert "wss://valid.relay.com" in insert_call[0].args[1]

        # candidate deletion called via execute (atomic, within the same transaction)
        execute_calls = conn.execute.call_args_list
        delete_call = [c for c in execute_calls if "ANY($3::text[])" in str(c)]
        assert len(delete_call) == 1, f"Expected one candidate DELETE call, got {delete_call}"
        assert "wss://valid.relay.com" in delete_call[0].args[3]

    @pytest.mark.asyncio
    async def test_invalid_candidates_failures_incremented(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Test invalid candidates have failures incremented."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("wss://invalid.relay.com", failed_attempts=2)], []]
        )

        validator = Validator(brotr=mock_validator_brotr)

        with patch("services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=False):
            await validator.run()

        mock_validator_brotr.upsert_service_data.assert_called_once()
        call_args = mock_validator_brotr.upsert_service_data.call_args[0][0]
        assert call_args[0][3]["failed_attempts"] == 3

    @pytest.mark.asyncio
    async def test_invalid_candidates_preserve_data_fields(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Test invalid candidates preserve all data fields (network, etc)."""
        mock_validator_brotr._pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate_row("wss://invalid.relay.com", network="tor", failed_attempts=1)],
                [],
            ]
        )

        validator = Validator(brotr=mock_validator_brotr)

        with patch("services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=False):
            await validator.run()

        mock_validator_brotr.upsert_service_data.assert_called_once()
        call_args = mock_validator_brotr.upsert_service_data.call_args[0][0]
        data = call_args[0][3]
        assert data["failed_attempts"] == 2
        assert data["network"] == "tor"  # Preserved from original data


# ============================================================================
# Cleanup Tests
# ============================================================================


class TestCleanup:
    """Tests for cleanup operations."""

    @pytest.mark.asyncio
    async def test_cleanup_stale(self, mock_validator_brotr: Brotr) -> None:
        """Test stale candidates (already in relays) are cleaned up."""
        mock_validator_brotr._pool.execute = AsyncMock(return_value="DELETE 5")

        validator = Validator(brotr=mock_validator_brotr)
        await validator._cleanup_stale()

        mock_validator_brotr._pool.execute.assert_called_once()
        query = mock_validator_brotr._pool.execute.call_args[0][0]
        assert "DELETE FROM service_data" in query
        assert "data_key IN (SELECT url FROM relays)" in query

    @pytest.mark.asyncio
    async def test_cleanup_exhausted_when_enabled(self, mock_validator_brotr: Brotr) -> None:
        """Test exhausted candidates are cleaned up when enabled."""
        mock_validator_brotr._pool.execute = AsyncMock(return_value="DELETE 3")

        config = ValidatorConfig(cleanup={"enabled": True, "max_failures": 5})
        validator = Validator(brotr=mock_validator_brotr, config=config)
        await validator._cleanup_exhausted()

        mock_validator_brotr._pool.execute.assert_called_once()
        call_args = mock_validator_brotr._pool.execute.call_args
        assert call_args[0][3] == 5  # max_failures threshold

    @pytest.mark.asyncio
    async def test_cleanup_exhausted_not_called_when_disabled(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """Test exhausted cleanup is skipped when disabled."""
        # Set up execute as an AsyncMock to track calls
        mock_validator_brotr._pool._mock_connection.execute = AsyncMock(return_value="DELETE 0")

        config = ValidatorConfig(cleanup={"enabled": False})
        validator = Validator(brotr=mock_validator_brotr, config=config)
        await validator._cleanup_exhausted()

        mock_validator_brotr._pool._mock_connection.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_propagates_db_errors(self, mock_validator_brotr: Brotr) -> None:
        """Test cleanup propagates database errors (no internal error handling)."""
        mock_validator_brotr._pool.execute = AsyncMock(side_effect=Exception("DB error"))

        validator = Validator(brotr=mock_validator_brotr)
        with pytest.raises(Exception, match="DB error"):
            await validator._cleanup_stale()


# ============================================================================
# _parse_delete_result Tests
# ============================================================================


class TestParseDeleteResult:
    """Tests for Validator._parse_delete_result edge cases."""

    def test_standard_delete_result(self) -> None:
        assert Validator._parse_delete_result("DELETE 5") == 5

    def test_zero_deleted(self) -> None:
        assert Validator._parse_delete_result("DELETE 0") == 0

    def test_large_count(self) -> None:
        assert Validator._parse_delete_result("DELETE 99999") == 99999

    def test_none_returns_zero(self) -> None:
        assert Validator._parse_delete_result(None) == 0

    def test_empty_string_returns_zero(self) -> None:
        assert Validator._parse_delete_result("") == 0

    def test_non_numeric_suffix_returns_zero(self) -> None:
        assert Validator._parse_delete_result("DELETE abc") == 0

    def test_single_word_returns_zero(self) -> None:
        assert Validator._parse_delete_result("DELETE") == 0

    def test_unexpected_format_returns_zero(self) -> None:
        assert Validator._parse_delete_result("SOMETHING ELSE") == 0


# ============================================================================
# Network Configuration Tests
# ============================================================================


class TestNetworkConfiguration:
    """Tests for network configuration via ValidatorConfig.networks."""

    def test_enabled_networks_default(self) -> None:
        """Test default enabled networks via config."""
        config = NetworkConfig()
        enabled = config.get_enabled_networks()
        assert "clearnet" in enabled

    def test_enabled_networks_with_tor(self) -> None:
        """Test enabled networks with Tor enabled."""
        config = NetworkConfig(
            clearnet=ClearnetConfig(enabled=True),
            tor=TorConfig(enabled=True),
        )
        enabled = config.get_enabled_networks()
        assert "clearnet" in enabled
        assert "tor" in enabled

    def test_network_config_for_clearnet(self) -> None:
        """Test getting network config for clearnet."""
        config = NetworkConfig(clearnet=ClearnetConfig(timeout=10.0, max_tasks=25))

        assert config.clearnet.timeout == 10.0
        assert config.clearnet.max_tasks == 25

    def test_network_config_for_tor(self) -> None:
        """Test getting network config for Tor."""
        config = NetworkConfig(
            tor=TorConfig(enabled=True, timeout=60.0, proxy_url="socks5://tor:9050")
        )

        assert config.tor.timeout == 60.0
        assert config.tor.proxy_url == "socks5://tor:9050"


# ============================================================================
# Integration Tests
# ============================================================================


class TestValidatorIntegration:
    """Integration tests for Validator."""

    @pytest.mark.asyncio
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

        with patch("services.validator.is_nostr_relay", side_effect=mock_validation):
            await validator.run()

        # 1 valid (good), 2 failures (bad + error)
        assert validator._progress.success == 1
        assert validator._progress.failure == 2

    @pytest.mark.asyncio
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
            networks=NetworkConfig(
                clearnet=ClearnetConfig(timeout=5.0),
                tor=TorConfig(enabled=True, timeout=30.0, proxy_url="socks5://tor:9050"),
            )
        )
        validator = Validator(brotr=mock_validator_brotr, config=config)

        call_args_list = []

        async def capture_args(relay, proxy, timeout):
            call_args_list.append((relay.url, proxy, timeout))
            return True

        with patch("services.validator.is_nostr_relay", side_effect=capture_args):
            await validator.run()

        # Verify correct timeouts/proxies were used
        clearnet_call = next(c for c in call_args_list if "clearnet" in c[0])
        tor_call = next(c for c in call_args_list if "onion" in c[0])

        assert clearnet_call[1] is None  # No proxy for clearnet
        assert clearnet_call[2] == 5.0

        assert tor_call[1] == "socks5://tor:9050"
        assert tor_call[2] == 30.0
