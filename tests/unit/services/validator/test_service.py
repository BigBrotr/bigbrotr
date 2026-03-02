"""Unit tests for the Validator service."""

import asyncio
from unittest.mock import AsyncMock, call, patch

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.services.common.configs import (
    ClearnetConfig,
    I2pConfig,
    LokiConfig,
    NetworksConfig,
    TorConfig,
)
from bigbrotr.services.common.types import CandidateCheckpoint
from bigbrotr.services.validator import (
    Validator,
    ValidatorConfig,
)


def make_candidate(
    url: str,
    network: NetworkType = NetworkType.CLEARNET,
    failures: int = 0,
) -> CandidateCheckpoint:
    """Return a typed CandidateCheckpoint for patched-query tests."""
    return CandidateCheckpoint(key=url, timestamp=0, network=network, failures=failures)


# ============================================================================
# Initialization Tests
# ============================================================================


class TestValidatorInit:
    """Tests for Validator construction and class attributes."""

    def test_service_name(self, mock_validator_brotr: Brotr) -> None:
        assert Validator(mock_validator_brotr).SERVICE_NAME == ServiceName.VALIDATOR

    def test_config_class(self) -> None:
        assert Validator.CONFIG_CLASS is ValidatorConfig

    def test_default_config_applied(self, mock_validator_brotr: Brotr) -> None:
        v = Validator(mock_validator_brotr)
        assert v._config.interval == 300.0
        assert v._config.processing.chunk_size == 1000

    def test_custom_config_stored(self, mock_validator_brotr: Brotr) -> None:
        cfg = ValidatorConfig(interval=600.0, processing={"chunk_size": 200})
        v = Validator(mock_validator_brotr, config=cfg)
        assert v._config.interval == 600.0
        assert v._config.processing.chunk_size == 200


# ============================================================================
# run() Tests
# ============================================================================


class TestValidatorRun:
    """Tests for Validator.run()."""

    async def test_run_delegates_to_validate(self, mock_validator_brotr: Brotr) -> None:
        """run() is a thin wrapper that calls validate() exactly once."""
        v = Validator(mock_validator_brotr)
        with patch.object(v, "validate", new_callable=AsyncMock, return_value=0) as mock_validate:
            await v.run()
        mock_validate.assert_awaited_once()

    async def test_run_with_no_candidates(self, mock_validator_brotr: Brotr) -> None:
        """Smoke test: run() completes without error when there are no candidates."""
        mock_validator_brotr._pool.fetch = AsyncMock(return_value=[])
        await Validator(mock_validator_brotr).run()


# ============================================================================
# validate() Tests
# ============================================================================


class TestValidate:
    """Tests for Validator.validate() cycle logic."""

    async def test_no_networks_enabled_returns_zero(self, mock_validator_brotr: Brotr) -> None:
        """If all networks are disabled, validate() logs a warning and returns 0."""
        cfg = ValidatorConfig(networks=NetworksConfig(clearnet=ClearnetConfig(enabled=False)))
        v = Validator(mock_validator_brotr, config=cfg)
        result = await v.validate()
        assert result == 0

    async def test_empty_candidates_returns_zero(self, mock_validator_brotr: Brotr) -> None:
        """When count_candidates returns 0, validate() returns 0 without looping."""
        with (
            patch(
                "bigbrotr.services.validator.service.count_candidates",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "bigbrotr.services.validator.service.fetch_candidates",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await Validator(mock_validator_brotr).validate()
        assert result == 0

    async def test_one_chunk_all_promoted(self, mock_validator_brotr: Brotr) -> None:
        """All valid candidates yield the correct processed count."""
        candidates = [make_candidate(f"wss://r{i}.com") for i in range(3)]
        with (
            patch(
                "bigbrotr.services.validator.service.count_candidates",
                new_callable=AsyncMock,
                return_value=3,
            ),
            patch(
                "bigbrotr.services.validator.service.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[candidates, []],
            ),
            patch(
                "bigbrotr.services.validator.service.promote_candidates",
                new_callable=AsyncMock,
                return_value=3,
            ),
            patch(
                "bigbrotr.services.validator.service.fail_candidates",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "bigbrotr.services.validator.service.is_nostr_relay",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await Validator(mock_validator_brotr).validate()
        assert result == 3

    async def test_one_chunk_all_failed(self, mock_validator_brotr: Brotr) -> None:
        """All invalid candidates yield the correct processed count."""
        candidates = [make_candidate(f"wss://r{i}.com") for i in range(4)]
        with (
            patch(
                "bigbrotr.services.validator.service.count_candidates",
                new_callable=AsyncMock,
                return_value=4,
            ),
            patch(
                "bigbrotr.services.validator.service.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[candidates, []],
            ),
            patch(
                "bigbrotr.services.validator.service.promote_candidates",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "bigbrotr.services.validator.service.fail_candidates",
                new_callable=AsyncMock,
                return_value=4,
            ),
            patch(
                "bigbrotr.services.validator.service.is_nostr_relay",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            result = await Validator(mock_validator_brotr).validate()
        assert result == 4

    async def test_mixed_chunk_splits_valid_invalid(self, mock_validator_brotr: Brotr) -> None:
        """Candidates returning True go to promote_candidates; False go to fail_candidates."""
        c_valid = make_candidate("wss://good.com")
        c_invalid = make_candidate("wss://bad.com")

        async def mock_is_nostr_relay(relay, proxy, timeout):
            return "good" in relay.url

        promote_mock = AsyncMock(return_value=1)
        fail_mock = AsyncMock(return_value=1)

        with (
            patch(
                "bigbrotr.services.validator.service.count_candidates",
                new_callable=AsyncMock,
                return_value=2,
            ),
            patch(
                "bigbrotr.services.validator.service.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[[c_valid, c_invalid], []],
            ),
            patch(
                "bigbrotr.services.validator.service.promote_candidates",
                promote_mock,
            ),
            patch(
                "bigbrotr.services.validator.service.fail_candidates",
                fail_mock,
            ),
            patch(
                "bigbrotr.services.validator.service.is_nostr_relay",
                side_effect=mock_is_nostr_relay,
            ),
        ):
            result = await Validator(mock_validator_brotr).validate()

        assert result == 2
        promoted_list = promote_mock.call_args[0][1]
        failed_list = fail_mock.call_args[0][1]
        assert len(promoted_list) == 1
        assert len(failed_list) == 1
        assert promoted_list[0].key == "wss://good.com"
        assert failed_list[0].key == "wss://bad.com"

    async def test_multiple_chunks_accumulate(self, mock_validator_brotr: Brotr) -> None:
        """validate() accumulates processed count across multiple chunks."""
        chunk1 = [make_candidate(f"wss://a{i}.com") for i in range(5)]
        chunk2 = [make_candidate(f"wss://b{i}.com") for i in range(3)]
        with (
            patch(
                "bigbrotr.services.validator.service.count_candidates",
                new_callable=AsyncMock,
                return_value=8,
            ),
            patch(
                "bigbrotr.services.validator.service.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[chunk1, chunk2, []],
            ),
            patch(
                "bigbrotr.services.validator.service.promote_candidates",
                new_callable=AsyncMock,
                side_effect=[5, 3],
            ),
            patch(
                "bigbrotr.services.validator.service.fail_candidates",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "bigbrotr.services.validator.service.is_nostr_relay",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await Validator(mock_validator_brotr).validate()
        assert result == 8

    async def test_respects_max_candidates_limit(self, mock_validator_brotr: Brotr) -> None:
        """validate() stops after max_candidates have been processed."""
        cfg = ValidatorConfig(processing={"chunk_size": 100, "max_candidates": 100})
        chunk = [make_candidate(f"wss://r{i}.com") for i in range(100)]
        fetch_mock = AsyncMock(side_effect=[chunk, []])
        with (
            patch(
                "bigbrotr.services.validator.service.count_candidates",
                new_callable=AsyncMock,
                return_value=10,
            ),
            patch("bigbrotr.services.validator.service.fetch_candidates", fetch_mock),
            patch(
                "bigbrotr.services.validator.service.promote_candidates",
                new_callable=AsyncMock,
                return_value=5,
            ),
            patch(
                "bigbrotr.services.validator.service.fail_candidates",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "bigbrotr.services.validator.service.is_nostr_relay",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await Validator(mock_validator_brotr, config=cfg).validate()
        assert result == 100

    async def test_exception_in_validation_counted_as_invalid(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """An exception raised by is_nostr_relay is logged and the candidate is failed."""
        c = make_candidate("wss://broken.com")
        fail_mock = AsyncMock(return_value=1)
        with (
            patch(
                "bigbrotr.services.validator.service.count_candidates",
                new_callable=AsyncMock,
                return_value=1,
            ),
            patch(
                "bigbrotr.services.validator.service.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[[c], []],
            ),
            patch(
                "bigbrotr.services.validator.service.promote_candidates",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch("bigbrotr.services.validator.service.fail_candidates", fail_mock),
            patch(
                "bigbrotr.services.validator.service.is_nostr_relay",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
        ):
            result = await Validator(mock_validator_brotr).validate()

        assert result == 1
        failed_list = fail_mock.call_args[0][1]
        assert len(failed_list) == 1
        assert failed_list[0].key == "wss://broken.com"

    async def test_cancelled_error_propagates(self, mock_validator_brotr: Brotr) -> None:
        """asyncio.CancelledError raised by is_nostr_relay propagates out of validate()."""
        c = make_candidate("wss://relay.com")
        with (
            patch(
                "bigbrotr.services.validator.service.count_candidates",
                new_callable=AsyncMock,
                return_value=1,
            ),
            patch(
                "bigbrotr.services.validator.service.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[[c], []],
            ),
            patch(
                "bigbrotr.services.validator.service.is_nostr_relay",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await Validator(mock_validator_brotr).validate()

    async def test_db_error_during_persist_propagates(self, mock_validator_brotr: Brotr) -> None:
        """A database error during promote_candidates propagates to the caller."""
        c = make_candidate("wss://relay.com")
        with (
            patch(
                "bigbrotr.services.validator.service.count_candidates",
                new_callable=AsyncMock,
                return_value=1,
            ),
            patch(
                "bigbrotr.services.validator.service.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[[c], []],
            ),
            patch(
                "bigbrotr.services.validator.service.promote_candidates",
                new_callable=AsyncMock,
                side_effect=OSError("db down"),
            ),
            patch(
                "bigbrotr.services.validator.service.fail_candidates",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "bigbrotr.services.validator.service.is_nostr_relay",
                new_callable=AsyncMock,
                return_value=True,
            ),
            pytest.raises(OSError, match="db down"),
        ):
            await Validator(mock_validator_brotr).validate()


# ============================================================================
# _validate_candidate() Tests
# ============================================================================


class TestValidateCandidate:
    """Tests for Validator._validate_candidate() per-relay probe."""

    async def test_valid_relay_returns_true(self, mock_validator_brotr: Brotr) -> None:
        v = Validator(mock_validator_brotr)

        c = make_candidate("wss://good.com")
        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=True,
        ):
            assert await v._validate_candidate(c) is True

    async def test_invalid_relay_returns_false(self, mock_validator_brotr: Brotr) -> None:
        v = Validator(mock_validator_brotr)

        c = make_candidate("wss://bad.com")
        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=False,
        ):
            assert await v._validate_candidate(c) is False

    async def test_timeout_error_returns_false(self, mock_validator_brotr: Brotr) -> None:
        v = Validator(mock_validator_brotr)

        c = make_candidate("wss://slow.com")
        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            side_effect=TimeoutError,
        ):
            assert await v._validate_candidate(c) is False

    async def test_os_error_returns_false(self, mock_validator_brotr: Brotr) -> None:
        v = Validator(mock_validator_brotr)

        c = make_candidate("wss://unreachable.com")
        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            side_effect=OSError("refused"),
        ):
            assert await v._validate_candidate(c) is False

    async def test_unknown_network_returns_false(self, mock_validator_brotr: Brotr) -> None:
        """NetworkSemaphores.get() returns None for non-operational types; candidate is skipped."""
        v = Validator(mock_validator_brotr)
        # UNKNOWN is not in OPERATIONAL_NETWORKS so its semaphore is None.
        c = make_candidate("wss://relay.com", network=NetworkType.UNKNOWN)
        result = await v._validate_candidate(c)
        assert result is False

    async def test_clearnet_uses_no_proxy(self, mock_validator_brotr: Brotr) -> None:
        v = Validator(mock_validator_brotr)

        c = make_candidate("wss://relay.com")
        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock:
            await v._validate_candidate(c)
        _, proxy_url, _ = mock.call_args[0]
        assert proxy_url is None


# ============================================================================
# Network Routing Tests
# ============================================================================


class TestNetworkRouting:
    """Tests that _validate_candidate routes timeout and proxy correctly per network."""

    async def _run_single(
        self, mock_validator_brotr: Brotr, cfg: ValidatorConfig, candidate: CandidateCheckpoint
    ) -> tuple[str | None, float]:
        """Helper: run _validate_candidate and return (proxy_url, timeout)."""
        v = Validator(mock_validator_brotr, config=cfg)

        with patch(
            "bigbrotr.services.validator.service.is_nostr_relay",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock:
            await v._validate_candidate(candidate)
        _, proxy_url, timeout = mock.call_args[0]
        return proxy_url, timeout

    async def test_clearnet_timeout_and_no_proxy(self, mock_validator_brotr: Brotr) -> None:
        cfg = ValidatorConfig(networks=NetworksConfig(clearnet=ClearnetConfig(timeout=7.0)))
        proxy, timeout = await self._run_single(
            mock_validator_brotr, cfg, make_candidate("wss://relay.com")
        )
        assert proxy is None
        assert timeout == 7.0

    async def test_tor_proxy_and_timeout(self, mock_validator_brotr: Brotr) -> None:
        cfg = ValidatorConfig(
            networks=NetworksConfig(
                tor=TorConfig(enabled=True, proxy_url="socks5://tor:9050", timeout=45.0)
            )
        )
        proxy, timeout = await self._run_single(
            mock_validator_brotr, cfg, make_candidate("ws://abc.onion", network=NetworkType.TOR)
        )
        assert proxy == "socks5://tor:9050"
        assert timeout == 45.0

    async def test_i2p_proxy_and_timeout(self, mock_validator_brotr: Brotr) -> None:
        cfg = ValidatorConfig(
            networks=NetworksConfig(
                i2p=I2pConfig(enabled=True, proxy_url="socks5://i2p:4447", timeout=60.0)
            )
        )
        proxy, timeout = await self._run_single(
            mock_validator_brotr, cfg, make_candidate("ws://test.i2p", network=NetworkType.I2P)
        )
        assert proxy == "socks5://i2p:4447"
        assert timeout == 60.0

    async def test_loki_proxy_and_timeout(self, mock_validator_brotr: Brotr) -> None:
        cfg = ValidatorConfig(
            networks=NetworksConfig(
                loki=LokiConfig(enabled=True, proxy_url="socks5://lokinet:1080", timeout=30.0)
            )
        )
        proxy, timeout = await self._run_single(
            mock_validator_brotr, cfg, make_candidate("ws://test.loki", network=NetworkType.LOKI)
        )
        assert proxy == "socks5://lokinet:1080"
        assert timeout == 30.0


# ============================================================================
# cleanup() Tests
# ============================================================================


class TestCleanup:
    """Tests for Validator.cleanup() lifecycle hook."""

    async def test_removes_promoted_candidates(self, mock_validator_brotr: Brotr) -> None:
        mock_validator_brotr.fetchval = AsyncMock(return_value=3)
        result = await Validator(mock_validator_brotr).cleanup()
        mock_validator_brotr.fetchval.assert_awaited_once()
        sql = mock_validator_brotr.fetchval.call_args[0][0]
        assert "AND EXISTS" in sql
        assert result == 3

    async def test_calls_delete_exhausted_when_enabled(self, mock_validator_brotr: Brotr) -> None:
        mock_validator_brotr.fetchval = AsyncMock(return_value=0)
        cfg = ValidatorConfig(cleanup={"enabled": True, "max_failures": 10})
        with patch(
            "bigbrotr.services.validator.service.delete_exhausted_candidates",
            new_callable=AsyncMock,
            return_value=5,
        ) as mock_delete:
            result = await Validator(mock_validator_brotr, config=cfg).cleanup()
        mock_delete.assert_awaited_once()
        assert result == 5

    async def test_skips_delete_exhausted_when_disabled(self, mock_validator_brotr: Brotr) -> None:
        mock_validator_brotr.fetchval = AsyncMock(return_value=0)
        with patch(
            "bigbrotr.services.validator.service.delete_exhausted_candidates",
            new_callable=AsyncMock,
        ) as mock_delete:
            await Validator(mock_validator_brotr).cleanup()
        mock_delete.assert_not_awaited()

    async def test_returns_sum_of_promoted_and_exhausted(
        self, mock_validator_brotr: Brotr
    ) -> None:
        mock_validator_brotr.fetchval = AsyncMock(return_value=4)
        cfg = ValidatorConfig(cleanup={"enabled": True, "max_failures": 5})
        with patch(
            "bigbrotr.services.validator.service.delete_exhausted_candidates",
            new_callable=AsyncMock,
            return_value=6,
        ):
            result = await Validator(mock_validator_brotr, config=cfg).cleanup()
        assert result == 10


# ============================================================================
# Metrics Tests
# ============================================================================


class TestValidatorMetrics:
    """Tests for Prometheus gauge and counter emissions from validate()."""

    async def test_total_gauge_set_to_candidate_count(self, mock_validator_brotr: Brotr) -> None:
        """'total' gauge is set to the count returned by count_candidates."""
        with (
            patch(
                "bigbrotr.services.validator.service.count_candidates",
                new_callable=AsyncMock,
                return_value=42,
            ),
            patch(
                "bigbrotr.services.validator.service.fetch_candidates",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            v = Validator(mock_validator_brotr)
            with patch.object(v, "set_gauge") as mock_gauge:
                await v.validate()
        mock_gauge.assert_any_call("total", 42)

    async def test_gauges_reset_to_zero_at_cycle_start(self, mock_validator_brotr: Brotr) -> None:
        """validated/not_validated/chunk gauges are reset to 0 before the loop."""
        with (
            patch(
                "bigbrotr.services.validator.service.count_candidates",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "bigbrotr.services.validator.service.fetch_candidates",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            v = Validator(mock_validator_brotr)
            with patch.object(v, "set_gauge") as mock_gauge:
                await v.validate()

        calls = {(c.args[0], c.args[1]) for c in mock_gauge.call_args_list}
        assert ("validated", 0) in calls
        assert ("not_validated", 0) in calls
        assert ("chunk", 0) in calls

    async def test_validated_gauge_accumulates_across_chunks(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """'validated' gauge is non-decreasing and reaches total promoted after all chunks."""
        chunk1 = [make_candidate(f"wss://a{i}.com") for i in range(3)]
        chunk2 = [make_candidate(f"wss://b{i}.com") for i in range(2)]
        with (
            patch(
                "bigbrotr.services.validator.service.count_candidates",
                new_callable=AsyncMock,
                return_value=5,
            ),
            patch(
                "bigbrotr.services.validator.service.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[chunk1, chunk2, []],
            ),
            patch(
                "bigbrotr.services.validator.service.promote_candidates",
                new_callable=AsyncMock,
                side_effect=[3, 2],
            ),
            patch(
                "bigbrotr.services.validator.service.fail_candidates",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "bigbrotr.services.validator.service.is_nostr_relay",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            v = Validator(mock_validator_brotr)
            gauge_calls: list[tuple[str, int]] = []
            with patch.object(
                v, "set_gauge", side_effect=lambda n, val: gauge_calls.append((n, val))
            ):
                await v.validate()

        validated_values = [val for name, val in gauge_calls if name == "validated"]
        assert validated_values == sorted(validated_values)
        assert validated_values[-1] == 5

    async def test_chunk_gauge_increments_per_chunk(self, mock_validator_brotr: Brotr) -> None:
        """'chunk' gauge reaches the total number of chunks processed."""
        chunk1 = [make_candidate("wss://r1.com")]
        chunk2 = [make_candidate("wss://r2.com")]
        with (
            patch(
                "bigbrotr.services.validator.service.count_candidates",
                new_callable=AsyncMock,
                return_value=2,
            ),
            patch(
                "bigbrotr.services.validator.service.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[chunk1, chunk2, []],
            ),
            patch(
                "bigbrotr.services.validator.service.promote_candidates",
                new_callable=AsyncMock,
                return_value=1,
            ),
            patch(
                "bigbrotr.services.validator.service.fail_candidates",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "bigbrotr.services.validator.service.is_nostr_relay",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            v = Validator(mock_validator_brotr)
            gauge_calls: list[tuple[str, int]] = []
            with patch.object(
                v, "set_gauge", side_effect=lambda n, val: gauge_calls.append((n, val))
            ):
                await v.validate()

        chunk_values = [val for name, val in gauge_calls if name == "chunk"]
        assert chunk_values[-1] == 2

    async def test_total_promoted_counter_emitted_per_chunk(
        self, mock_validator_brotr: Brotr
    ) -> None:
        """inc_counter('total_promoted', N) is called after each chunk."""
        chunk1 = [make_candidate(f"wss://a{i}.com") for i in range(3)]
        chunk2 = [make_candidate(f"wss://b{i}.com") for i in range(2)]
        with (
            patch(
                "bigbrotr.services.validator.service.count_candidates",
                new_callable=AsyncMock,
                return_value=5,
            ),
            patch(
                "bigbrotr.services.validator.service.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[chunk1, chunk2, []],
            ),
            patch(
                "bigbrotr.services.validator.service.promote_candidates",
                new_callable=AsyncMock,
                side_effect=[3, 2],
            ),
            patch(
                "bigbrotr.services.validator.service.fail_candidates",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "bigbrotr.services.validator.service.is_nostr_relay",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            v = Validator(mock_validator_brotr)
            with patch.object(v, "inc_counter") as mock_counter:
                await v.validate()

        assert mock_counter.call_args_list == [
            call("total_promoted", 3),
            call("total_promoted", 2),
        ]
