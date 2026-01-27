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

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.brotr import Brotr, BrotrConfig
from services.validator import Validator, ValidatorConfig
from utils.network import ClearnetConfig, NetworkConfig, TorConfig


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
def mock_brotr() -> Brotr:
    """Create a mock Brotr instance for validator tests."""
    brotr = MagicMock(spec=Brotr)
    brotr.config = BrotrConfig(
        database={"host": "localhost", "port": 5432, "name": "test", "user": "test"}
    )
    brotr.pool = MagicMock()
    brotr.pool.execute = AsyncMock(return_value="DELETE 0")
    brotr.pool.fetch = AsyncMock(return_value=[])
    brotr.pool.fetchrow = AsyncMock(return_value={"count": 0})
    brotr.insert_relays = AsyncMock()
    brotr.delete_service_data = AsyncMock()
    brotr.upsert_service_data = AsyncMock()
    return brotr


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


# ============================================================================
# Validator Tests
# ============================================================================


class TestValidator:
    """Tests for Validator initialization."""

    def test_init_default_config(self, mock_brotr: Brotr) -> None:
        """Test validator with default config."""
        validator = Validator(brotr=mock_brotr)

        assert validator._config.interval == 300.0
        assert validator._config.processing.chunk_size == 100

    def test_init_custom_config(self, mock_brotr: Brotr) -> None:
        """Test validator with custom config."""
        config = ValidatorConfig(interval=600.0, processing={"chunk_size": 200})
        validator = Validator(brotr=mock_brotr, config=config)

        assert validator._config.interval == 600.0
        assert validator._config.processing.chunk_size == 200


# ============================================================================
# Validator Run Tests
# ============================================================================


class TestValidatorRun:
    """Tests for validator run cycle."""

    @pytest.mark.asyncio
    async def test_run_with_no_candidates(self, mock_brotr: Brotr) -> None:
        """Test run completes when no candidates exist."""
        validator = Validator(brotr=mock_brotr)
        await validator.run()

        assert validator._progress.success == 0
        assert validator._progress.failure == 0

    @pytest.mark.asyncio
    async def test_cleanup_promoted_called_at_end_of_run(self, mock_brotr: Brotr) -> None:
        """Test cleanup of promoted candidates is called at end of run cycle."""
        mock_brotr.pool.fetch = AsyncMock(side_effect=[[make_candidate_row("wss://relay.com")], []])
        mock_brotr.pool.execute = AsyncMock(return_value="DELETE 0")

        validator = Validator(brotr=mock_brotr)

        with patch("services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=False):
            await validator.run()

        # Cleanup promoted is called at end of run (not in _persist)
        assert mock_brotr.pool.execute.called
        # Check that the cleanup query was called
        calls = mock_brotr.pool.execute.call_args_list
        cleanup_called = any("data_key IN (SELECT url FROM relays)" in str(c) for c in calls)
        assert cleanup_called

    @pytest.mark.asyncio
    async def test_run_validates_candidates(self, mock_brotr: Brotr) -> None:
        """Test basic validation flow."""
        mock_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate_row("wss://relay1.com"), make_candidate_row("wss://relay2.com")],
                [],
            ]
        )

        validator = Validator(brotr=mock_brotr)

        async def mock_is_nostr_relay(relay, proxy_url, timeout):
            return "relay1" in relay.url

        with patch("services.validator.is_nostr_relay", side_effect=mock_is_nostr_relay):
            await validator.run()

        assert validator._progress.success == 1
        assert validator._progress.failure == 1


# ============================================================================
# Chunk Processing Tests
# ============================================================================


class TestChunkProcessing:
    """Tests for chunk-based processing."""

    @pytest.mark.asyncio
    async def test_loads_chunks_until_empty(self, mock_brotr: Brotr) -> None:
        """Test validator loads chunks until no more candidates."""
        mock_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate_row(f"wss://relay{i}.com") for i in range(100)],
                [make_candidate_row(f"wss://relay{i + 100}.com") for i in range(50)],
                [],
            ]
        )

        config = ValidatorConfig(processing={"chunk_size": 100})
        validator = Validator(brotr=mock_brotr, config=config)

        with patch("services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=True):
            await validator.run()

        assert validator._progress.success == 150

    @pytest.mark.asyncio
    async def test_respects_max_candidates_limit(self, mock_brotr: Brotr) -> None:
        """Test validator respects max_candidates limit."""

        def mock_fetch(query, *args, timeout=None):
            # args order: (networks, run_start_ts, limit)
            limit = args[2] if len(args) > 2 else 100
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

        mock_brotr.pool.fetch = AsyncMock(side_effect=mock_fetch)

        config = ValidatorConfig(processing={"chunk_size": 100, "max_candidates": 150})
        validator = Validator(brotr=mock_brotr, config=config)

        with patch("services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=True):
            await validator.run()

        assert validator._progress.success == 150


# ============================================================================
# Network-Aware Validation Tests
# ============================================================================


class TestNetworkAwareValidation:
    """Tests for network-specific validation behavior."""

    @pytest.mark.asyncio
    async def test_clearnet_uses_clearnet_timeout(self, mock_brotr: Brotr) -> None:
        """Test clearnet relays use clearnet timeout."""
        mock_brotr.pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("wss://relay.com", network="clearnet")], []]
        )

        config = ValidatorConfig(
            networks=NetworkConfig(clearnet=ClearnetConfig(timeout=5.0, max_tasks=10))
        )
        validator = Validator(brotr=mock_brotr, config=config)

        with patch(
            "services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=True
        ) as mock:
            await validator.run()
            mock.assert_called_once()
            _, _, timeout = mock.call_args[0]
            assert timeout == 5.0

    @pytest.mark.asyncio
    async def test_tor_uses_tor_timeout(self, mock_brotr: Brotr) -> None:
        """Test Tor relays use Tor timeout."""
        mock_brotr.pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("ws://onion.onion", network="tor")], []]
        )

        config = ValidatorConfig(networks=NetworkConfig(tor=TorConfig(timeout=45.0, max_tasks=5)))
        validator = Validator(brotr=mock_brotr, config=config)

        with patch(
            "services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=True
        ) as mock:
            await validator.run()
            mock.assert_called_once()
            _, _, timeout = mock.call_args[0]
            assert timeout == 45.0

    @pytest.mark.asyncio
    async def test_tor_uses_proxy(self, mock_brotr: Brotr) -> None:
        """Test Tor relays use proxy URL."""
        mock_brotr.pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("ws://onion.onion", network="tor")], []]
        )

        config = ValidatorConfig(
            networks=NetworkConfig(tor=TorConfig(enabled=True, proxy_url="socks5://tor:9050"))
        )
        validator = Validator(brotr=mock_brotr, config=config)

        with patch(
            "services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=True
        ) as mock:
            await validator.run()
            mock.assert_called_once()
            _, proxy_url, _ = mock.call_args[0]
            assert proxy_url == "socks5://tor:9050"

    @pytest.mark.asyncio
    async def test_clearnet_uses_no_proxy(self, mock_brotr: Brotr) -> None:
        """Test clearnet relays don't use proxy."""
        mock_brotr.pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("wss://relay.com", network="clearnet")], []]
        )

        validator = Validator(brotr=mock_brotr)

        with patch(
            "services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=True
        ) as mock:
            await validator.run()
            mock.assert_called_once()
            _, proxy_url, _ = mock.call_args[0]
            assert proxy_url is None


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_validation_exception_handled(self, mock_brotr: Brotr) -> None:
        """Test exceptions during validation are handled."""
        mock_brotr.pool.fetch = AsyncMock(side_effect=[[make_candidate_row("wss://relay.com")], []])

        validator = Validator(brotr=mock_brotr)

        with patch(
            "services.validator.is_nostr_relay",
            new_callable=AsyncMock,
            side_effect=Exception("Connection error"),
        ):
            await validator.run()

        assert validator._progress.success == 0
        assert validator._progress.failure == 1

    @pytest.mark.asyncio
    async def test_database_error_during_persist_logged(self, mock_brotr: Brotr) -> None:
        """Test database errors during persist are logged."""
        mock_brotr.pool.fetch = AsyncMock(side_effect=[[make_candidate_row("wss://relay.com")], []])
        mock_brotr.upsert_service_data = AsyncMock(side_effect=Exception("DB error"))

        validator = Validator(brotr=mock_brotr)

        with patch("services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=False):
            await validator.run()

        assert validator._progress.failure == 1

    @pytest.mark.asyncio
    async def test_all_candidates_fail_validation(self, mock_brotr: Brotr) -> None:
        """Test run completes when all validations fail."""
        mock_brotr.pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row(f"wss://relay{i}.com") for i in range(10)], []]
        )

        validator = Validator(brotr=mock_brotr)

        with patch("services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=False):
            await validator.run()

        assert validator._progress.success == 0
        assert validator._progress.failure == 10

    @pytest.mark.asyncio
    async def test_graceful_shutdown(self, mock_brotr: Brotr) -> None:
        """Test is_running flag controls processing loop."""
        mock_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate_row(f"wss://relay{i}.com") for i in range(10)],
                [],
            ]
        )

        validator = Validator(brotr=mock_brotr)

        with patch("services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=True):
            await validator.run()

        total = validator._progress.success + validator._progress.failure
        assert total == 10

        # Test stopping via is_running
        mock_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate_row(f"wss://relay{i}.com") for i in range(10)],
                [],
            ]
        )
        validator2 = Validator(brotr=mock_brotr)

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
    async def test_valid_relays_inserted_and_candidates_deleted(self, mock_brotr: Brotr) -> None:
        """Test valid relays are inserted and candidates removed."""
        mock_brotr.pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("wss://valid.relay.com")], []]
        )

        validator = Validator(brotr=mock_brotr)

        with patch("services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=True):
            await validator.run()

        mock_brotr.insert_relays.assert_called_once()
        mock_brotr.delete_service_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_candidates_failures_incremented(self, mock_brotr: Brotr) -> None:
        """Test invalid candidates have failures incremented."""
        mock_brotr.pool.fetch = AsyncMock(
            side_effect=[[make_candidate_row("wss://invalid.relay.com", failed_attempts=2)], []]
        )

        validator = Validator(brotr=mock_brotr)

        with patch("services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=False):
            await validator.run()

        mock_brotr.upsert_service_data.assert_called_once()
        call_args = mock_brotr.upsert_service_data.call_args[0][0]
        assert call_args[0][3]["failed_attempts"] == 3

    @pytest.mark.asyncio
    async def test_invalid_candidates_preserve_data_fields(self, mock_brotr: Brotr) -> None:
        """Test invalid candidates preserve all data fields (network, etc)."""
        mock_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [make_candidate_row("wss://invalid.relay.com", network="tor", failed_attempts=1)],
                [],
            ]
        )

        validator = Validator(brotr=mock_brotr)

        with patch("services.validator.is_nostr_relay", new_callable=AsyncMock, return_value=False):
            await validator.run()

        mock_brotr.upsert_service_data.assert_called_once()
        call_args = mock_brotr.upsert_service_data.call_args[0][0]
        data = call_args[0][3]
        assert data["failed_attempts"] == 2
        assert data["network"] == "tor"  # Preserved from original data


# ============================================================================
# Cleanup Tests
# ============================================================================


class TestCleanup:
    """Tests for cleanup operations."""

    @pytest.mark.asyncio
    async def test_cleanup_stale(self, mock_brotr: Brotr) -> None:
        """Test stale candidates (already in relays) are cleaned up."""
        mock_brotr.pool.execute = AsyncMock(return_value="DELETE 5")

        validator = Validator(brotr=mock_brotr)
        await validator._cleanup_stale()

        mock_brotr.pool.execute.assert_called_once()
        query = mock_brotr.pool.execute.call_args[0][0]
        assert "DELETE FROM service_data" in query
        assert "data_key IN (SELECT url FROM relays)" in query

    @pytest.mark.asyncio
    async def test_cleanup_exhausted_when_enabled(self, mock_brotr: Brotr) -> None:
        """Test exhausted candidates are cleaned up when enabled."""
        mock_brotr.pool.execute = AsyncMock(return_value="DELETE 3")

        config = ValidatorConfig(cleanup={"enabled": True, "max_failures": 5})
        validator = Validator(brotr=mock_brotr, config=config)
        await validator._cleanup_exhausted()

        mock_brotr.pool.execute.assert_called_once()
        call_args = mock_brotr.pool.execute.call_args
        assert call_args[0][1] == 5  # max_failures threshold

    @pytest.mark.asyncio
    async def test_cleanup_exhausted_not_called_when_disabled(self, mock_brotr: Brotr) -> None:
        """Test exhausted cleanup is skipped when disabled."""
        config = ValidatorConfig(cleanup={"enabled": False})
        validator = Validator(brotr=mock_brotr, config=config)
        await validator._cleanup_exhausted()

        # Only cleanup_promoted should have been called during run, not cleanup_exhausted
        mock_brotr.pool.execute.assert_not_called()
