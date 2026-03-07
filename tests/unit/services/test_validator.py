"""Unit tests for the Validator service package.

Covers configuration models, database queries, and service logic.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceStateType
from bigbrotr.services.common.configs import (
    ClearnetConfig,
    I2pConfig,
    LokiConfig,
    NetworksConfig,
    TorConfig,
)
from bigbrotr.services.common.queries import insert_relays_as_candidates
from bigbrotr.services.common.types import CandidateCheckpoint
from bigbrotr.services.validator import (
    CleanupConfig,
    ProcessingConfig,
    Validator,
    ValidatorConfig,
)
from bigbrotr.services.validator.queries import (
    count_candidates,
    delete_exhausted_candidates,
    delete_promoted_candidates,
    fail_candidates,
    fetch_candidates,
    promote_candidates,
)


_SVC = "bigbrotr.services.validator.service"


# ============================================================================
# Fixtures & Helpers
# ============================================================================


@pytest.fixture
def validator_brotr(mock_brotr: Brotr) -> Brotr:
    """Brotr mock with additional methods used by Validator."""
    mock_brotr.insert_relay = AsyncMock()
    mock_brotr.delete_service_state = AsyncMock()
    mock_brotr.upsert_service_state = AsyncMock()
    return mock_brotr


@pytest.fixture
def query_brotr() -> MagicMock:
    """Lightweight MagicMock Brotr for query-level tests."""
    brotr = MagicMock()
    brotr.fetch = AsyncMock(return_value=[])
    brotr.fetchrow = AsyncMock(return_value={"count": 0})
    brotr.fetchval = AsyncMock(return_value=0)
    brotr.upsert_service_state = AsyncMock(return_value=0)
    brotr.insert_relay = AsyncMock(return_value=0)
    brotr.delete_service_state = AsyncMock(return_value=0)
    brotr.config.batch.max_size = 1000
    return brotr


def _candidate(
    url: str = "wss://relay.example.com",
    network: NetworkType = NetworkType.CLEARNET,
    failures: int = 0,
) -> CandidateCheckpoint:
    return CandidateCheckpoint(key=url, timestamp=0, network=network, failures=failures)


def _mock_relay(url: str = "wss://relay.example.com", network: str = "clearnet") -> MagicMock:
    relay = MagicMock()
    relay.url = url
    relay.network = MagicMock(value=network)
    return relay


def _row(data: dict[str, Any]) -> dict[str, Any]:
    return data


# ============================================================================
# ProcessingConfig
# ============================================================================


class TestProcessingConfig:
    def test_defaults(self) -> None:
        cfg = ProcessingConfig()
        assert cfg.chunk_size == 100
        assert cfg.max_candidates is None
        assert cfg.interval == 3600.0

    def test_chunk_size_bounds(self) -> None:
        assert ProcessingConfig(chunk_size=10).chunk_size == 10
        assert ProcessingConfig(chunk_size=1000).chunk_size == 1000

    def test_chunk_size_out_of_range(self) -> None:
        with pytest.raises(ValueError):
            ProcessingConfig(chunk_size=9)
        with pytest.raises(ValueError):
            ProcessingConfig(chunk_size=1001)

    def test_max_candidates_valid(self) -> None:
        assert ProcessingConfig(max_candidates=None).max_candidates is None
        assert ProcessingConfig(max_candidates=1).max_candidates == 1

    def test_max_candidates_zero_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProcessingConfig(max_candidates=0)

    def test_interval_bounds(self) -> None:
        assert ProcessingConfig(interval=0.0).interval == 0.0
        assert ProcessingConfig(interval=604_800.0).interval == 604_800.0

    def test_interval_above_max_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProcessingConfig(interval=604_801.0)


# ============================================================================
# CleanupConfig
# ============================================================================


class TestCleanupConfig:
    def test_defaults(self) -> None:
        cfg = CleanupConfig()
        assert cfg.enabled is False
        assert cfg.max_failures == 720

    def test_custom_values(self) -> None:
        cfg = CleanupConfig(enabled=True, max_failures=100)
        assert cfg.enabled is True
        assert cfg.max_failures == 100

    def test_max_failures_minimum(self) -> None:
        assert CleanupConfig(max_failures=1).max_failures == 1

    def test_max_failures_zero_rejected(self) -> None:
        with pytest.raises(ValueError):
            CleanupConfig(max_failures=0)


# ============================================================================
# ValidatorConfig
# ============================================================================


class TestValidatorConfig:
    def test_defaults(self) -> None:
        cfg = ValidatorConfig()
        assert cfg.interval == 300.0
        assert cfg.max_consecutive_failures == 5
        assert isinstance(cfg.networks, NetworksConfig)
        assert isinstance(cfg.processing, ProcessingConfig)
        assert isinstance(cfg.cleanup, CleanupConfig)

    def test_interval_minimum(self) -> None:
        assert ValidatorConfig(interval=60.0).interval == 60.0

    def test_interval_below_minimum_rejected(self) -> None:
        with pytest.raises(ValueError):
            ValidatorConfig(interval=59.9)

    def test_max_consecutive_failures_bounds(self) -> None:
        assert ValidatorConfig(max_consecutive_failures=0).max_consecutive_failures == 0
        with pytest.raises(ValueError):
            ValidatorConfig(max_consecutive_failures=101)

    def test_nested_processing_via_dict(self) -> None:
        cfg = ValidatorConfig(processing={"chunk_size": 200, "max_candidates": 5000})
        assert cfg.processing.chunk_size == 200
        assert cfg.processing.max_candidates == 5000

    def test_nested_cleanup_via_dict(self) -> None:
        cfg = ValidatorConfig(cleanup={"enabled": True, "max_failures": 50})
        assert cfg.cleanup.enabled is True
        assert cfg.cleanup.max_failures == 50

    def test_nested_networks(self) -> None:
        cfg = ValidatorConfig(networks=NetworksConfig(tor=TorConfig(enabled=True)))
        assert cfg.networks.tor.enabled is True

    def test_processing_validation_propagated(self) -> None:
        with pytest.raises(ValueError):
            ValidatorConfig(processing={"chunk_size": 5})


# ============================================================================
# NetworksConfig
# ============================================================================


class TestNetworksConfig:
    def test_defaults(self) -> None:
        cfg = NetworksConfig()
        assert cfg.clearnet.enabled is True
        assert cfg.tor.enabled is False
        assert cfg.i2p.enabled is False
        assert cfg.loki.enabled is False

    def test_get_enabled_networks_default(self) -> None:
        assert NetworksConfig().get_enabled_networks() == [NetworkType.CLEARNET]

    def test_get_enabled_networks_with_tor(self) -> None:
        cfg = NetworksConfig(tor=TorConfig(enabled=True))
        enabled = cfg.get_enabled_networks()
        assert NetworkType.CLEARNET in enabled
        assert NetworkType.TOR in enabled

    def test_get_enabled_networks_all_disabled(self) -> None:
        cfg = NetworksConfig(clearnet=ClearnetConfig(enabled=False))
        assert cfg.get_enabled_networks() == []

    def test_get_enabled_networks_all_enabled(self) -> None:
        cfg = NetworksConfig(
            clearnet=ClearnetConfig(enabled=True),
            tor=TorConfig(enabled=True),
            i2p=I2pConfig(enabled=True),
            loki=LokiConfig(enabled=True),
        )
        assert len(cfg.get_enabled_networks()) == 4

    def test_get_returns_correct_config(self) -> None:
        cfg = NetworksConfig(clearnet=ClearnetConfig(timeout=15.0))
        assert cfg.get(NetworkType.CLEARNET).timeout == 15.0

    def test_get_proxy_url_clearnet_always_none(self) -> None:
        assert NetworksConfig().get_proxy_url(NetworkType.CLEARNET) is None

    def test_get_proxy_url_tor(self) -> None:
        cfg = NetworksConfig(tor=TorConfig(enabled=True, proxy_url="socks5://tor:9050"))
        assert cfg.get_proxy_url(NetworkType.TOR) == "socks5://tor:9050"
        assert NetworksConfig().get_proxy_url(NetworkType.TOR) is None

    def test_is_enabled(self) -> None:
        assert NetworksConfig().is_enabled(NetworkType.CLEARNET) is True
        assert NetworksConfig().is_enabled(NetworkType.TOR) is False


# ============================================================================
# Per-Network Configs
# ============================================================================


class TestClearnetConfig:
    def test_defaults(self) -> None:
        cfg = ClearnetConfig()
        assert cfg.enabled is True
        assert cfg.proxy_url is None
        assert cfg.max_tasks == 50
        assert cfg.timeout == 10.0

    def test_max_tasks_bounds(self) -> None:
        assert ClearnetConfig(max_tasks=1).max_tasks == 1
        with pytest.raises(ValueError):
            ClearnetConfig(max_tasks=201)

    def test_timeout_bounds(self) -> None:
        assert ClearnetConfig(timeout=1.0).timeout == 1.0
        with pytest.raises(ValueError):
            ClearnetConfig(timeout=121.0)


class TestTorConfig:
    def test_defaults(self) -> None:
        cfg = TorConfig()
        assert cfg.enabled is False
        assert cfg.proxy_url == "socks5://tor:9050"
        assert cfg.max_tasks == 10
        assert cfg.timeout == 30.0

    def test_custom_proxy(self) -> None:
        assert TorConfig(proxy_url="socks5://localhost:9150").proxy_url == "socks5://localhost:9150"

    def test_proxy_can_be_none(self) -> None:
        assert TorConfig(proxy_url=None).proxy_url is None


class TestI2pConfig:
    def test_defaults(self) -> None:
        cfg = I2pConfig()
        assert cfg.enabled is False
        assert cfg.proxy_url == "socks5://i2p:4447"
        assert cfg.max_tasks == 5
        assert cfg.timeout == 45.0


class TestLokiConfig:
    def test_defaults(self) -> None:
        cfg = LokiConfig()
        assert cfg.enabled is False
        assert cfg.proxy_url == "socks5://lokinet:1080"
        assert cfg.max_tasks == 5
        assert cfg.timeout == 30.0


# ============================================================================
# insert_relays_as_candidates
# ============================================================================


class TestInsertCandidates:
    async def test_filters_then_upserts(self, query_brotr: MagicMock) -> None:
        relay = _mock_relay()
        query_brotr.fetch = AsyncMock(return_value=[_row({"url": "wss://relay.example.com"})])
        query_brotr.upsert_service_state = AsyncMock(return_value=1)

        result = await insert_relays_as_candidates(query_brotr, [relay])

        query_brotr.fetch.assert_awaited_once()
        assert "unnest($1::text[])" in query_brotr.fetch.call_args[0][0]
        records = query_brotr.upsert_service_state.call_args[0][0]
        assert len(records) == 1
        record = records[0]
        assert record.service_name == ServiceName.VALIDATOR
        assert record.state_type == ServiceStateType.CHECKPOINT
        assert record.state_key == "wss://relay.example.com"
        assert record.state_value["failures"] == 0
        assert record.state_value["network"] == "clearnet"
        assert "timestamp" in record.state_value
        assert result == 1

    async def test_all_filtered_out(self, query_brotr: MagicMock) -> None:
        query_brotr.fetch = AsyncMock(return_value=[])
        result = await insert_relays_as_candidates(query_brotr, [_mock_relay()])
        query_brotr.upsert_service_state.assert_not_awaited()
        assert result == 0

    async def test_empty_input(self, query_brotr: MagicMock) -> None:
        result = await insert_relays_as_candidates(query_brotr, [])
        query_brotr.fetch.assert_not_awaited()
        assert result == 0

    async def test_batching(self, query_brotr: MagicMock) -> None:
        query_brotr.config.batch.max_size = 2
        relays = [_mock_relay(f"wss://r{i}.example.com") for i in range(3)]
        query_brotr.fetch = AsyncMock(return_value=[_row({"url": r.url}) for r in relays])
        query_brotr.upsert_service_state = AsyncMock(side_effect=[2, 1])

        result = await insert_relays_as_candidates(query_brotr, relays)

        assert query_brotr.upsert_service_state.await_count == 2
        assert result == 3


# ============================================================================
# delete_promoted_candidates
# ============================================================================


class TestDeletePromotedCandidates:
    async def test_deletes_matching_relays(self, query_brotr: MagicMock) -> None:
        query_brotr.fetchval = AsyncMock(return_value=2)
        result = await delete_promoted_candidates(query_brotr)

        args = query_brotr.fetchval.call_args
        sql = args[0][0]
        assert "DELETE FROM service_state" in sql
        assert "EXISTS" in sql
        assert "FROM relay r" in sql
        assert args[0][1] == ServiceName.VALIDATOR
        assert args[0][2] == ServiceStateType.CHECKPOINT
        assert result == 2

    async def test_returns_zero_on_none(self, query_brotr: MagicMock) -> None:
        query_brotr.fetchval = AsyncMock(return_value=None)
        assert await delete_promoted_candidates(query_brotr) == 0


# ============================================================================
# delete_exhausted_candidates
# ============================================================================


class TestDeleteExhaustedCandidates:
    async def test_deletes_over_threshold(self, query_brotr: MagicMock) -> None:
        query_brotr.fetchval = AsyncMock(return_value=3)
        result = await delete_exhausted_candidates(query_brotr, max_failures=5)

        args = query_brotr.fetchval.call_args
        sql = args[0][0]
        assert "DELETE FROM service_state" in sql
        assert "failures" in sql
        assert ">= $3" in sql
        assert args[0][3] == 5
        assert result == 3

    async def test_returns_zero_when_none(self, query_brotr: MagicMock) -> None:
        query_brotr.fetchval = AsyncMock(return_value=0)
        assert await delete_exhausted_candidates(query_brotr, max_failures=5) == 0


# ============================================================================
# count_candidates
# ============================================================================


class TestCountCandidates:
    async def test_counts_with_filters(self, query_brotr: MagicMock) -> None:
        query_brotr.fetchrow = AsyncMock(return_value={"count": 15})
        result = await count_candidates(
            query_brotr,
            networks=[NetworkType.CLEARNET, NetworkType.TOR],
            attempted_before=1700000000,
        )

        args = query_brotr.fetchrow.call_args
        sql = args[0][0]
        assert "COUNT(*)" in sql
        assert "service_name = $1" in sql
        assert "state_type = $2" in sql
        assert args[0][1] == ServiceName.VALIDATOR
        assert args[0][2] == ServiceStateType.CHECKPOINT
        assert args[0][3] == [NetworkType.CLEARNET, NetworkType.TOR]
        assert args[0][4] == 1700000000
        assert result == 15

    async def test_returns_zero_on_none_row(self, query_brotr: MagicMock) -> None:
        query_brotr.fetchrow = AsyncMock(return_value=None)
        assert await count_candidates(query_brotr, [NetworkType.CLEARNET], 1700000000) == 0


# ============================================================================
# fetch_candidates
# ============================================================================


class TestFetchCandidates:
    async def test_query_params(self, query_brotr: MagicMock) -> None:
        await fetch_candidates(query_brotr, [NetworkType.CLEARNET], 1700000000, 50)

        args = query_brotr.fetch.call_args
        sql = args[0][0]
        assert "state_key, state_value" in sql
        assert "LIMIT $5" in sql
        assert args[0][1] == ServiceName.VALIDATOR
        assert args[0][5] == 50

    async def test_returns_checkpoint_objects(self, query_brotr: MagicMock) -> None:
        query_brotr.fetch = AsyncMock(
            return_value=[
                _row(
                    {
                        "state_key": "wss://relay.example.com",
                        "state_value": {
                            "failures": 0,
                            "network": "clearnet",
                            "timestamp": 1700000000,
                        },
                    }
                )
            ]
        )
        result = await fetch_candidates(query_brotr, [NetworkType.CLEARNET], 1700000000, 50)

        assert len(result) == 1
        assert isinstance(result[0], CandidateCheckpoint)
        assert result[0].key == "wss://relay.example.com"
        assert result[0].network == NetworkType.CLEARNET

    async def test_skips_invalid_network(self, query_brotr: MagicMock) -> None:
        query_brotr.fetch = AsyncMock(
            return_value=[
                _row(
                    {
                        "state_key": "wss://good.com",
                        "state_value": {
                            "failures": 0,
                            "network": "clearnet",
                            "timestamp": 0,
                        },
                    }
                ),
                _row(
                    {
                        "state_key": "wss://bad.com",
                        "state_value": {
                            "failures": 0,
                            "network": "invalid_net",
                            "timestamp": 0,
                        },
                    }
                ),
            ]
        )
        result = await fetch_candidates(query_brotr, [NetworkType.CLEARNET], 0, 50)
        assert len(result) == 1

    async def test_empty_result(self, query_brotr: MagicMock) -> None:
        assert await fetch_candidates(query_brotr, [NetworkType.CLEARNET], 0, 50) == []


# ============================================================================
# promote_candidates
# ============================================================================


class TestPromoteCandidates:
    async def test_inserts_and_deletes(self, query_brotr: MagicMock) -> None:
        query_brotr.insert_relay = AsyncMock(return_value=1)
        query_brotr.delete_service_state = AsyncMock(return_value=1)

        result = await promote_candidates(query_brotr, [_candidate("wss://promoted.com")])

        relays = query_brotr.insert_relay.call_args[0][0]
        assert relays[0].url == "wss://promoted.com"
        query_brotr.delete_service_state.assert_awaited_once_with(
            [ServiceName.VALIDATOR],
            [ServiceStateType.CHECKPOINT],
            ["wss://promoted.com"],
        )
        assert result == 1

    async def test_empty_list(self, query_brotr: MagicMock) -> None:
        assert await promote_candidates(query_brotr, []) == 0
        query_brotr.insert_relay.assert_not_awaited()

    async def test_multiple_candidates(self, query_brotr: MagicMock) -> None:
        candidates = [_candidate(f"wss://r{i}.com") for i in range(2)]
        query_brotr.insert_relay = AsyncMock(return_value=2)
        query_brotr.delete_service_state = AsyncMock(return_value=2)

        result = await promote_candidates(query_brotr, candidates)

        urls = [r.url for r in query_brotr.insert_relay.call_args[0][0]]
        assert urls == ["wss://r0.com", "wss://r1.com"]
        assert result == 2


# ============================================================================
# fail_candidates
# ============================================================================


class TestFailCandidates:
    async def test_increments_failures(self, query_brotr: MagicMock) -> None:
        query_brotr.upsert_service_state = AsyncMock(return_value=1)

        result = await fail_candidates(query_brotr, [_candidate("wss://bad.com", failures=2)])

        records = query_brotr.upsert_service_state.call_args[0][0]
        assert records[0].state_value["failures"] == 3
        assert records[0].state_key == "wss://bad.com"
        assert result == 1

    async def test_empty_list(self, query_brotr: MagicMock) -> None:
        assert await fail_candidates(query_brotr, []) == 0
        query_brotr.upsert_service_state.assert_not_awaited()


# ============================================================================
# Validator.__init__
# ============================================================================


class TestValidatorInit:
    def test_service_name(self, validator_brotr: Brotr) -> None:
        assert Validator(validator_brotr).SERVICE_NAME == ServiceName.VALIDATOR

    def test_config_class(self) -> None:
        assert Validator.CONFIG_CLASS is ValidatorConfig

    def test_default_config(self, validator_brotr: Brotr) -> None:
        v = Validator(validator_brotr)
        assert v._config.interval == 300.0
        assert v._config.processing.chunk_size == 100

    def test_custom_config(self, validator_brotr: Brotr) -> None:
        cfg = ValidatorConfig(interval=600.0, processing={"chunk_size": 200})
        v = Validator(validator_brotr, config=cfg)
        assert v._config.interval == 600.0
        assert v._config.processing.chunk_size == 200


# ============================================================================
# Validator.run
# ============================================================================


class TestValidatorRun:
    async def test_delegates_to_validate(self, validator_brotr: Brotr) -> None:
        v = Validator(validator_brotr)
        with patch.object(v, "validate", new_callable=AsyncMock, return_value=0) as mock:
            await v.run()
        mock.assert_awaited_once()

    async def test_completes_with_no_candidates(self, validator_brotr: Brotr) -> None:
        validator_brotr._pool.fetch = AsyncMock(return_value=[])
        await Validator(validator_brotr).run()


# ============================================================================
# Validator.validate
# ============================================================================


class TestValidate:
    async def test_no_networks_returns_zero(self, validator_brotr: Brotr) -> None:
        cfg = ValidatorConfig(networks=NetworksConfig(clearnet=ClearnetConfig(enabled=False)))
        assert await Validator(validator_brotr, config=cfg).validate() == 0

    async def test_empty_candidates_returns_zero(self, validator_brotr: Brotr) -> None:
        with (
            patch(
                f"{_SVC}.count_candidates",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                f"{_SVC}.fetch_candidates",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            assert await Validator(validator_brotr).validate() == 0

    async def test_all_promoted(self, validator_brotr: Brotr) -> None:
        candidates = [_candidate(f"wss://r{i}.com") for i in range(3)]
        with (
            patch(f"{_SVC}.count_candidates", new_callable=AsyncMock, return_value=3),
            patch(
                f"{_SVC}.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[candidates, []],
            ),
            patch(f"{_SVC}.promote_candidates", new_callable=AsyncMock, return_value=3),
            patch(f"{_SVC}.fail_candidates", new_callable=AsyncMock, return_value=0),
            patch(f"{_SVC}.is_nostr_relay", new_callable=AsyncMock, return_value=True),
        ):
            assert await Validator(validator_brotr).validate() == 3

    async def test_all_failed(self, validator_brotr: Brotr) -> None:
        candidates = [_candidate(f"wss://r{i}.com") for i in range(4)]
        with (
            patch(f"{_SVC}.count_candidates", new_callable=AsyncMock, return_value=4),
            patch(
                f"{_SVC}.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[candidates, []],
            ),
            patch(f"{_SVC}.promote_candidates", new_callable=AsyncMock, return_value=0),
            patch(f"{_SVC}.fail_candidates", new_callable=AsyncMock, return_value=4),
            patch(f"{_SVC}.is_nostr_relay", new_callable=AsyncMock, return_value=False),
        ):
            assert await Validator(validator_brotr).validate() == 4

    async def test_mixed_splits_valid_invalid(self, validator_brotr: Brotr) -> None:
        c_good = _candidate("wss://good.com")
        c_bad = _candidate("wss://bad.com")
        promote_mock = AsyncMock(return_value=1)
        fail_mock = AsyncMock(return_value=1)

        async def relay_check(relay, proxy, timeout):
            return "good" in relay.url

        with (
            patch(f"{_SVC}.count_candidates", new_callable=AsyncMock, return_value=2),
            patch(
                f"{_SVC}.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[[c_good, c_bad], []],
            ),
            patch(f"{_SVC}.promote_candidates", promote_mock),
            patch(f"{_SVC}.fail_candidates", fail_mock),
            patch(f"{_SVC}.is_nostr_relay", side_effect=relay_check),
        ):
            assert await Validator(validator_brotr).validate() == 2

        assert promote_mock.call_args[0][1][0].key == "wss://good.com"
        assert fail_mock.call_args[0][1][0].key == "wss://bad.com"

    async def test_multiple_chunks_accumulate(self, validator_brotr: Brotr) -> None:
        chunk1 = [_candidate(f"wss://a{i}.com") for i in range(5)]
        chunk2 = [_candidate(f"wss://b{i}.com") for i in range(3)]
        with (
            patch(f"{_SVC}.count_candidates", new_callable=AsyncMock, return_value=8),
            patch(
                f"{_SVC}.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[chunk1, chunk2, []],
            ),
            patch(
                f"{_SVC}.promote_candidates",
                new_callable=AsyncMock,
                side_effect=[5, 3],
            ),
            patch(f"{_SVC}.fail_candidates", new_callable=AsyncMock, return_value=0),
            patch(f"{_SVC}.is_nostr_relay", new_callable=AsyncMock, return_value=True),
        ):
            assert await Validator(validator_brotr).validate() == 8

    async def test_respects_max_candidates(self, validator_brotr: Brotr) -> None:
        cfg = ValidatorConfig(processing={"chunk_size": 100, "max_candidates": 100})
        chunk = [_candidate(f"wss://r{i}.com") for i in range(100)]
        with (
            patch(f"{_SVC}.count_candidates", new_callable=AsyncMock, return_value=10),
            patch(
                f"{_SVC}.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[chunk, []],
            ),
            patch(f"{_SVC}.promote_candidates", new_callable=AsyncMock, return_value=5),
            patch(f"{_SVC}.fail_candidates", new_callable=AsyncMock, return_value=0),
            patch(f"{_SVC}.is_nostr_relay", new_callable=AsyncMock, return_value=True),
        ):
            result = await Validator(validator_brotr, config=cfg).validate()
        assert result == 100

    async def test_exception_counted_as_invalid(self, validator_brotr: Brotr) -> None:
        fail_mock = AsyncMock(return_value=1)
        broken = _candidate("wss://broken.com")
        with (
            patch(f"{_SVC}.count_candidates", new_callable=AsyncMock, return_value=1),
            patch(
                f"{_SVC}.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[[broken], []],
            ),
            patch(f"{_SVC}.promote_candidates", new_callable=AsyncMock, return_value=0),
            patch(f"{_SVC}.fail_candidates", fail_mock),
            patch(
                f"{_SVC}.is_nostr_relay",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
        ):
            assert await Validator(validator_brotr).validate() == 1

        assert fail_mock.call_args[0][1][0].key == "wss://broken.com"

    async def test_cancelled_worker_does_not_abort_validation(self, validator_brotr: Brotr) -> None:
        with (
            patch(f"{_SVC}.count_candidates", new_callable=AsyncMock, return_value=1),
            patch(
                f"{_SVC}.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[[_candidate()], []],
            ),
            patch(
                f"{_SVC}.is_nostr_relay",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
            patch(f"{_SVC}.fail_candidates", new_callable=AsyncMock, return_value=0),
            patch(f"{_SVC}.promote_candidates", new_callable=AsyncMock, return_value=0),
        ):
            result = await Validator(validator_brotr).validate()

        assert result == 0

    async def test_db_error_propagates(self, validator_brotr: Brotr) -> None:
        with (
            patch(f"{_SVC}.count_candidates", new_callable=AsyncMock, return_value=1),
            patch(
                f"{_SVC}.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[[_candidate()], []],
            ),
            patch(
                f"{_SVC}.promote_candidates",
                new_callable=AsyncMock,
                side_effect=OSError("db down"),
            ),
            patch(f"{_SVC}.fail_candidates", new_callable=AsyncMock, return_value=0),
            patch(f"{_SVC}.is_nostr_relay", new_callable=AsyncMock, return_value=True),
            pytest.raises(OSError, match="db down"),
        ):
            await Validator(validator_brotr).validate()


# ============================================================================
# Validator._validate_candidate
# ============================================================================


class TestValidateCandidate:
    async def test_valid_returns_true(self, validator_brotr: Brotr) -> None:
        v = Validator(validator_brotr)
        with patch(f"{_SVC}.is_nostr_relay", new_callable=AsyncMock, return_value=True):
            assert await v._validate_candidate(_candidate("wss://good.com")) is True

    async def test_invalid_returns_false(self, validator_brotr: Brotr) -> None:
        v = Validator(validator_brotr)
        with patch(f"{_SVC}.is_nostr_relay", new_callable=AsyncMock, return_value=False):
            assert await v._validate_candidate(_candidate("wss://bad.com")) is False

    async def test_timeout_returns_false(self, validator_brotr: Brotr) -> None:
        v = Validator(validator_brotr)
        with patch(
            f"{_SVC}.is_nostr_relay",
            new_callable=AsyncMock,
            side_effect=TimeoutError,
        ):
            assert await v._validate_candidate(_candidate()) is False

    async def test_os_error_returns_false(self, validator_brotr: Brotr) -> None:
        v = Validator(validator_brotr)
        with patch(
            f"{_SVC}.is_nostr_relay",
            new_callable=AsyncMock,
            side_effect=OSError("refused"),
        ):
            assert await v._validate_candidate(_candidate()) is False

    async def test_unknown_network_returns_false(self, validator_brotr: Brotr) -> None:
        v = Validator(validator_brotr)
        c = _candidate(network=NetworkType.UNKNOWN)
        assert await v._validate_candidate(c) is False

    async def test_clearnet_no_proxy(self, validator_brotr: Brotr) -> None:
        v = Validator(validator_brotr)
        with patch(f"{_SVC}.is_nostr_relay", new_callable=AsyncMock, return_value=True) as mock:
            await v._validate_candidate(_candidate())
        assert mock.call_args[0][1] is None


# ============================================================================
# Network Routing
# ============================================================================


class TestNetworkRouting:
    async def _run(
        self,
        validator_brotr: Brotr,
        cfg: ValidatorConfig,
        candidate: CandidateCheckpoint,
    ) -> tuple[str | None, float]:
        v = Validator(validator_brotr, config=cfg)
        with patch(f"{_SVC}.is_nostr_relay", new_callable=AsyncMock, return_value=True) as mock:
            await v._validate_candidate(candidate)
        return mock.call_args[0][1], mock.call_args[0][2]

    async def test_clearnet(self, validator_brotr: Brotr) -> None:
        cfg = ValidatorConfig(networks=NetworksConfig(clearnet=ClearnetConfig(timeout=7.0)))
        proxy, timeout = await self._run(validator_brotr, cfg, _candidate())
        assert proxy is None
        assert timeout == 7.0

    async def test_tor(self, validator_brotr: Brotr) -> None:
        cfg = ValidatorConfig(
            networks=NetworksConfig(
                tor=TorConfig(enabled=True, proxy_url="socks5://tor:9050", timeout=45.0),
            )
        )
        proxy, timeout = await self._run(
            validator_brotr,
            cfg,
            _candidate("ws://abc.onion", NetworkType.TOR),
        )
        assert proxy == "socks5://tor:9050"
        assert timeout == 45.0

    async def test_i2p(self, validator_brotr: Brotr) -> None:
        cfg = ValidatorConfig(
            networks=NetworksConfig(
                i2p=I2pConfig(
                    enabled=True,
                    proxy_url="socks5://i2p:4447",
                    timeout=60.0,
                ),
            )
        )
        proxy, timeout = await self._run(
            validator_brotr,
            cfg,
            _candidate("ws://test.i2p", NetworkType.I2P),
        )
        assert proxy == "socks5://i2p:4447"
        assert timeout == 60.0

    async def test_loki(self, validator_brotr: Brotr) -> None:
        cfg = ValidatorConfig(
            networks=NetworksConfig(
                loki=LokiConfig(
                    enabled=True,
                    proxy_url="socks5://lokinet:1080",
                    timeout=30.0,
                ),
            )
        )
        proxy, timeout = await self._run(
            validator_brotr,
            cfg,
            _candidate("ws://test.loki", NetworkType.LOKI),
        )
        assert proxy == "socks5://lokinet:1080"
        assert timeout == 30.0


# ============================================================================
# Validator.cleanup
# ============================================================================


class TestCleanup:
    async def test_removes_promoted(self, validator_brotr: Brotr) -> None:
        validator_brotr.fetchval = AsyncMock(return_value=3)
        result = await Validator(validator_brotr).cleanup()
        assert "AND EXISTS" in validator_brotr.fetchval.call_args[0][0]
        assert result == 3

    async def test_delete_exhausted_when_enabled(self, validator_brotr: Brotr) -> None:
        validator_brotr.fetchval = AsyncMock(return_value=0)
        cfg = ValidatorConfig(cleanup={"enabled": True, "max_failures": 10})
        with patch(
            f"{_SVC}.delete_exhausted_candidates",
            new_callable=AsyncMock,
            return_value=5,
        ) as mock:
            result = await Validator(validator_brotr, config=cfg).cleanup()
        mock.assert_awaited_once()
        assert result == 5

    async def test_skips_exhausted_when_disabled(self, validator_brotr: Brotr) -> None:
        validator_brotr.fetchval = AsyncMock(return_value=0)
        with patch(f"{_SVC}.delete_exhausted_candidates", new_callable=AsyncMock) as mock:
            await Validator(validator_brotr).cleanup()
        mock.assert_not_awaited()

    async def test_returns_sum(self, validator_brotr: Brotr) -> None:
        validator_brotr.fetchval = AsyncMock(return_value=4)
        cfg = ValidatorConfig(cleanup={"enabled": True, "max_failures": 5})
        with patch(
            f"{_SVC}.delete_exhausted_candidates",
            new_callable=AsyncMock,
            return_value=6,
        ):
            result = await Validator(validator_brotr, config=cfg).cleanup()
        assert result == 10


# ============================================================================
# Metrics
# ============================================================================


class TestValidatorMetrics:
    async def test_total_gauge(self, validator_brotr: Brotr) -> None:
        with (
            patch(f"{_SVC}.count_candidates", new_callable=AsyncMock, return_value=42),
            patch(f"{_SVC}.fetch_candidates", new_callable=AsyncMock, return_value=[]),
        ):
            v = Validator(validator_brotr)
            with patch.object(v, "set_gauge") as mock_gauge:
                await v.validate()
        mock_gauge.assert_any_call("total", 42)

    async def test_gauges_reset_at_start(self, validator_brotr: Brotr) -> None:
        with (
            patch(f"{_SVC}.count_candidates", new_callable=AsyncMock, return_value=0),
            patch(f"{_SVC}.fetch_candidates", new_callable=AsyncMock, return_value=[]),
        ):
            v = Validator(validator_brotr)
            with patch.object(v, "set_gauge") as mock_gauge:
                await v.validate()
        calls = {(c.args[0], c.args[1]) for c in mock_gauge.call_args_list}
        assert ("validated", 0) in calls
        assert ("not_validated", 0) in calls
        assert ("chunk", 0) in calls

    async def test_validated_gauge_accumulates(self, validator_brotr: Brotr) -> None:
        chunk1 = [_candidate(f"wss://a{i}.com") for i in range(3)]
        chunk2 = [_candidate(f"wss://b{i}.com") for i in range(2)]
        with (
            patch(f"{_SVC}.count_candidates", new_callable=AsyncMock, return_value=5),
            patch(
                f"{_SVC}.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[chunk1, chunk2, []],
            ),
            patch(
                f"{_SVC}.promote_candidates",
                new_callable=AsyncMock,
                side_effect=[3, 2],
            ),
            patch(f"{_SVC}.fail_candidates", new_callable=AsyncMock, return_value=0),
            patch(f"{_SVC}.is_nostr_relay", new_callable=AsyncMock, return_value=True),
        ):
            v = Validator(validator_brotr)
            gauge_calls: list[tuple[str, int]] = []
            with patch.object(
                v,
                "set_gauge",
                side_effect=lambda n, val: gauge_calls.append((n, val)),
            ):
                await v.validate()
        validated = [val for name, val in gauge_calls if name == "validated"]
        assert validated == sorted(validated)
        assert validated[-1] == 5

    async def test_chunk_gauge_increments(self, validator_brotr: Brotr) -> None:
        chunk1 = [_candidate("wss://r1.com")]
        chunk2 = [_candidate("wss://r2.com")]
        with (
            patch(f"{_SVC}.count_candidates", new_callable=AsyncMock, return_value=2),
            patch(
                f"{_SVC}.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[chunk1, chunk2, []],
            ),
            patch(f"{_SVC}.promote_candidates", new_callable=AsyncMock, return_value=1),
            patch(f"{_SVC}.fail_candidates", new_callable=AsyncMock, return_value=0),
            patch(f"{_SVC}.is_nostr_relay", new_callable=AsyncMock, return_value=True),
        ):
            v = Validator(validator_brotr)
            gauge_calls: list[tuple[str, int]] = []
            with patch.object(
                v,
                "set_gauge",
                side_effect=lambda n, val: gauge_calls.append((n, val)),
            ):
                await v.validate()
        chunk_values = [val for name, val in gauge_calls if name == "chunk"]
        assert chunk_values[-1] == 2

    async def test_total_promoted_counter(self, validator_brotr: Brotr) -> None:
        chunk1 = [_candidate(f"wss://a{i}.com") for i in range(3)]
        chunk2 = [_candidate(f"wss://b{i}.com") for i in range(2)]
        with (
            patch(f"{_SVC}.count_candidates", new_callable=AsyncMock, return_value=5),
            patch(
                f"{_SVC}.fetch_candidates",
                new_callable=AsyncMock,
                side_effect=[chunk1, chunk2, []],
            ),
            patch(
                f"{_SVC}.promote_candidates",
                new_callable=AsyncMock,
                side_effect=[3, 2],
            ),
            patch(f"{_SVC}.fail_candidates", new_callable=AsyncMock, return_value=0),
            patch(f"{_SVC}.is_nostr_relay", new_callable=AsyncMock, return_value=True),
        ):
            v = Validator(validator_brotr)
            with patch.object(v, "inc_counter") as mock_counter:
                await v.validate()
        assert mock_counter.call_args_list == [
            call("total_promoted", 3),
            call("total_promoted", 2),
        ]
