"""Unit tests for the dvm service module."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nostr_sdk import Keys

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import Relay
from bigbrotr.models.constants import ServiceName
from bigbrotr.services.common.catalog import (
    Catalog,
    CatalogError,
    ColumnSchema,
    QueryResult,
    TableSchema,
)
from bigbrotr.services.common.configs import TableConfig
from bigbrotr.services.dvm.configs import DvmConfig
from bigbrotr.services.dvm.service import Dvm
from bigbrotr.services.dvm.utils import (
    build_announcement_event,
    build_error_event,
    build_payment_required_event,
    build_result_event,
    parse_job_params,
    parse_query_filters,
)


# Valid secp256k1 test key (DO NOT USE IN PRODUCTION)
VALID_HEX_KEY = (
    "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"  # pragma: allowlist secret
)


# ============================================================================
# Fixtures & Helpers
# ============================================================================


@pytest.fixture(autouse=True)
def _set_private_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOSTR_PRIVATE_KEY", VALID_HEX_KEY)


@pytest.fixture
def dvm_config() -> DvmConfig:
    return DvmConfig(
        interval=60.0,
        relays=["wss://relay.example.com"],
        kind=5050,
        max_page_size=100,
        tables={
            "relay": TableConfig(enabled=True),
            "premium_data": TableConfig(enabled=True, price=5000),
        },
    )


@pytest.fixture
def sample_dvm_catalog() -> Catalog:
    catalog = Catalog()
    catalog._tables = {
        "relay": TableSchema(
            name="relay",
            columns=(
                ColumnSchema(name="url", pg_type="text", nullable=False),
                ColumnSchema(name="network", pg_type="text", nullable=False),
            ),
            primary_key=("url",),
            is_view=False,
        ),
        "service_state": TableSchema(
            name="service_state",
            columns=(ColumnSchema(name="service_name", pg_type="text", nullable=False),),
            primary_key=("service_name",),
            is_view=False,
        ),
        "premium_data": TableSchema(
            name="premium_data",
            columns=(ColumnSchema(name="id", pg_type="integer", nullable=False),),
            primary_key=("id",),
            is_view=False,
        ),
    }
    return catalog


@pytest.fixture
def dvm_service(mock_brotr: Brotr, dvm_config: DvmConfig, sample_dvm_catalog: Catalog) -> Dvm:
    service = Dvm(brotr=mock_brotr, config=dvm_config)
    service._catalog = sample_dvm_catalog
    return service


def _make_mock_event(
    event_id: str = "abc123",
    author_hex: str = "author_pubkey_hex",
    tags: list[list[str]] | None = None,
) -> MagicMock:
    event = MagicMock()
    event.id.return_value.to_hex.return_value = event_id
    event.author.return_value.to_hex.return_value = author_hex

    if tags is None:
        tags = [
            ["param", "table", "relay"],
            ["param", "limit", "10"],
        ]

    mock_tags = []
    for tag_values in tags:
        mock_tag = MagicMock()
        mock_tag.as_vec.return_value = tag_values
        mock_tags.append(mock_tag)

    tag_list = MagicMock()
    tag_list.to_vec.return_value = mock_tags
    event.tags.return_value = tag_list

    return event


def _make_client_with_events(events: list[MagicMock]) -> MagicMock:
    mock_client = MagicMock()
    mock_client.send_event_builder = AsyncMock()
    events_obj = MagicMock()
    events_obj.to_vec.return_value = events
    mock_client.fetch_events = AsyncMock(return_value=events_obj)
    return mock_client


# ============================================================================
# Configs
# ============================================================================


class TestDvmConfig:
    def test_default_values(self) -> None:
        config = DvmConfig(relays=["wss://relay.example.com"])
        assert config.name == "BigBrotr DVM"
        assert config.about == "Read-only access to BigBrotr relay monitoring data"
        assert config.d_tag == "bigbrotr-dvm"
        assert config.kind == 5050
        assert config.default_page_size == 100
        assert config.max_page_size == 1000
        assert config.announce is True
        assert config.tables == {}
        assert config.fetch_timeout == 30.0
        assert config.allow_insecure is False

    def test_custom_branding(self) -> None:
        config = DvmConfig(
            relays=["wss://relay.example.com"],
            name="LilBrotr DVM",
            about="LilBrotr relay data",
            d_tag="lilbrotr-dvm",
        )
        assert config.name == "LilBrotr DVM"
        assert config.about == "LilBrotr relay data"
        assert config.d_tag == "lilbrotr-dvm"

    def test_custom_fetch_timeout(self) -> None:
        config = DvmConfig(relays=["wss://relay.example.com"], fetch_timeout=60.0)
        assert config.fetch_timeout == 60.0

    def test_requires_relays(self) -> None:
        with pytest.raises(ValueError):
            DvmConfig(relays=[])

    def test_kind_range(self) -> None:
        with pytest.raises(ValueError):
            DvmConfig(relays=["wss://relay.example.com"], kind=4000)

    def test_custom_tables(self) -> None:
        config = DvmConfig(
            relays=["wss://relay.example.com"],
            tables={"relay": TableConfig(enabled=True, price=1000)},
        )
        assert config.tables["relay"].price == 1000
        assert config.tables["relay"].enabled is True

    def test_inherits_base_service_config(self) -> None:
        config = DvmConfig(relays=["wss://relay.example.com"], interval=120.0)
        assert config.interval == 120.0

    def test_invalid_relay_url_rejected(self) -> None:
        with pytest.raises(ValueError):
            DvmConfig(relays=["not_a_url"])

    def test_valid_relay_urls_accepted(self) -> None:
        config = DvmConfig(relays=["wss://relay.damus.io", "wss://nos.lol"])
        assert len(config.relays) == 2
        assert all(isinstance(r, Relay) for r in config.relays)

    def test_default_page_size_exceeds_max_rejected(self) -> None:
        with pytest.raises(ValueError, match="default_page_size"):
            DvmConfig(
                relays=["wss://relay.example.com"],
                default_page_size=500,
                max_page_size=100,
            )

    def test_default_page_size_equals_max_accepted(self) -> None:
        config = DvmConfig(
            relays=["wss://relay.example.com"],
            default_page_size=100,
            max_page_size=100,
        )
        assert config.default_page_size == config.max_page_size


# ============================================================================
# Service Init
# ============================================================================


class TestDvm:
    def test_service_name(self) -> None:
        assert Dvm.SERVICE_NAME == ServiceName.DVM

    def test_config_class(self) -> None:
        assert Dvm.CONFIG_CLASS is DvmConfig

    def test_init(self, dvm_service: Dvm) -> None:
        assert dvm_service._client is None
        assert dvm_service._last_fetch_ts == 0
        assert dvm_service._processed_ids == set()


# ============================================================================
# Table Access Policy
# ============================================================================


class TestDvmTableAccessPolicy:
    def test_enabled_in_config(self, dvm_service: Dvm) -> None:
        assert dvm_service._is_table_enabled("relay") is True

    def test_not_in_config_disabled(self, dvm_service: Dvm) -> None:
        assert dvm_service._is_table_enabled("service_state") is False

    def test_unknown_table_disabled(self, dvm_service: Dvm) -> None:
        assert dvm_service._is_table_enabled("nonexistent") is False

    def test_free_price_default(self, dvm_service: Dvm) -> None:
        assert dvm_service._get_table_price("relay") == 0

    def test_paid_price(self, dvm_service: Dvm) -> None:
        assert dvm_service._get_table_price("premium_data") == 5000

    def test_unknown_table_price_returns_zero(self, dvm_service: Dvm) -> None:
        assert dvm_service._get_table_price("nonexistent_table") == 0


# ============================================================================
# Lifecycle
# ============================================================================


class TestDvmLifecycle:
    async def test_aenter_creates_client_and_connects(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        mock_client.add_relay = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.send_event_builder = AsyncMock()

        with (
            patch(
                "bigbrotr.services.dvm.service.create_client",
                new_callable=AsyncMock,
                return_value=mock_client,
            ),
            patch.object(dvm_service, "set_gauge"),
            patch.object(type(dvm_service), "__aexit__", new_callable=AsyncMock),
        ):
            await dvm_service.__aenter__()

            assert dvm_service._client is mock_client
            assert dvm_service._last_fetch_ts > 0
            mock_client.add_relay.assert_called_once()
            mock_client.connect.assert_called_once()
            mock_client.send_event_builder.assert_called_once()

    async def test_aenter_skips_announcement_when_disabled(self, mock_brotr: Brotr) -> None:
        config = DvmConfig(
            interval=60.0,
            relays=["wss://relay.example.com"],
            announce=False,
            tables={"relay": TableConfig(enabled=True)},
        )
        service = Dvm(brotr=mock_brotr, config=config)
        service._catalog = Catalog()
        service._catalog._tables = {
            "relay": TableSchema(
                name="relay",
                columns=(ColumnSchema(name="url", pg_type="text", nullable=False),),
                primary_key=("url",),
                is_view=False,
            ),
        }

        mock_client = MagicMock()
        mock_client.add_relay = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.send_event_builder = AsyncMock()

        with (
            patch(
                "bigbrotr.services.dvm.service.create_client",
                new_callable=AsyncMock,
                return_value=mock_client,
            ),
            patch.object(service, "set_gauge"),
            patch.object(type(service), "__aexit__", new_callable=AsyncMock),
        ):
            await service.__aenter__()

            mock_client.send_event_builder.assert_not_called()

    async def test_aexit_shuts_down_client(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        mock_client.shutdown = AsyncMock()
        dvm_service._client = mock_client

        with patch.object(type(dvm_service).__mro__[2], "__aexit__", new_callable=AsyncMock):
            await dvm_service.__aexit__(None, None, None)

        mock_client.shutdown.assert_awaited_once()
        assert dvm_service._client is None

    async def test_aexit_handles_shutdown_error(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        mock_client.shutdown = AsyncMock(side_effect=RuntimeError("FFI error"))
        dvm_service._client = mock_client

        with patch.object(type(dvm_service).__mro__[2], "__aexit__", new_callable=AsyncMock):
            await dvm_service.__aexit__(None, None, None)

        assert dvm_service._client is None

    async def test_aexit_noop_when_no_client(self, dvm_service: Dvm) -> None:
        dvm_service._client = None

        with patch.object(type(dvm_service).__mro__[2], "__aexit__", new_callable=AsyncMock):
            await dvm_service.__aexit__(None, None, None)

    async def test_cleanup_returns_zero(self, dvm_service: Dvm) -> None:
        result = await dvm_service.cleanup()
        assert result == 0


# ============================================================================
# Run
# ============================================================================


class TestDvmRun:
    async def test_run_no_client(self, dvm_service: Dvm) -> None:
        await dvm_service.run()

    async def test_run_no_events(self, dvm_service: Dvm) -> None:
        mock_client = _make_client_with_events([])
        dvm_service._client = mock_client

        with (
            patch.object(dvm_service, "set_gauge") as mock_gauge,
            patch.object(dvm_service, "inc_counter"),
        ):
            await dvm_service.run()

        mock_gauge.assert_any_call(
            "tables_exposed",
            sum(1 for n in dvm_service._catalog.tables if dvm_service._is_table_enabled(n)),
        )

    async def test_run_no_events_updates_fetch_ts(self, dvm_service: Dvm) -> None:
        mock_client = _make_client_with_events([])
        dvm_service._client = mock_client

        with (
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter"),
            patch("bigbrotr.services.dvm.service.time") as mock_time,
        ):
            mock_time.time.return_value = 5000
            await dvm_service.run()

        assert dvm_service._last_fetch_ts == 5000

    async def test_run_processes_job(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["param", "table", "relay"], ["param", "limit", "10"]])
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client

        mock_result = QueryResult(
            rows=[{"url": "wss://x", "network": "clearnet"}],
            total=1,
            limit=10,
            offset=0,
        )
        with (
            patch.object(
                dvm_service._catalog, "query", new_callable=AsyncMock, return_value=mock_result
            ),
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter"),
        ):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()

    async def test_run_dedup(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(
            event_id="dedup_id",
            tags=[["param", "table", "relay"]],
        )
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client
        dvm_service._processed_ids.add("dedup_id")

        with patch.object(dvm_service, "set_gauge"), patch.object(dvm_service, "inc_counter"):
            await dvm_service.run()

        mock_client.send_event_builder.assert_not_called()

    async def test_run_disabled_table(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["param", "table", "service_state"]])
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client

        with patch.object(dvm_service, "set_gauge"), patch.object(dvm_service, "inc_counter"):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()

    async def test_run_empty_table_name(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["param", "table", ""]])
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client

        with patch.object(dvm_service, "set_gauge"), patch.object(dvm_service, "inc_counter"):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()

    async def test_run_missing_table_param(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["param", "limit", "10"]])
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client

        with patch.object(dvm_service, "set_gauge"), patch.object(dvm_service, "inc_counter"):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()

    async def test_run_payment_required(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["param", "table", "premium_data"]])
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client

        with patch.object(dvm_service, "set_gauge"), patch.object(dvm_service, "inc_counter"):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()

    async def test_run_sufficient_bid(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["param", "table", "premium_data"], ["bid", "10000"]])
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client

        mock_result = QueryResult(rows=[], total=0, limit=100, offset=0)
        with (
            patch.object(
                dvm_service._catalog, "query", new_callable=AsyncMock, return_value=mock_result
            ),
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter"),
        ):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()

    async def test_run_invalid_limit(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(
            tags=[["param", "table", "relay"], ["param", "limit", "not_a_number"]]
        )
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client

        with patch.object(dvm_service, "set_gauge"), patch.object(dvm_service, "inc_counter"):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()

    async def test_run_updates_fetch_ts_before_processing(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["param", "table", "relay"]])
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client

        mock_result = QueryResult(rows=[], total=0, limit=100, offset=0)
        with (
            patch.object(
                dvm_service._catalog, "query", new_callable=AsyncMock, return_value=mock_result
            ),
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter"),
            patch("bigbrotr.services.dvm.service.time") as mock_time,
        ):
            mock_time.time.side_effect = [1000, 2000]
            mock_time.monotonic.return_value = 0.0
            await dvm_service.run()

        assert dvm_service._last_fetch_ts == 1000

    async def test_run_publish_error_failure_does_not_abort_batch(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        mock_client.send_event_builder = AsyncMock(
            side_effect=[OSError("relay offline"), None, None],
        )

        event1 = _make_mock_event(
            event_id="fail_pub",
            tags=[["param", "table", "service_state"]],
        )
        event2 = _make_mock_event(
            event_id="ok_pub",
            tags=[["param", "table", "relay"]],
        )
        events_obj = MagicMock()
        events_obj.to_vec.return_value = [event1, event2]
        mock_client.fetch_events = AsyncMock(return_value=events_obj)
        dvm_service._client = mock_client

        mock_result = QueryResult(rows=[], total=0, limit=100, offset=0)
        with (
            patch.object(
                dvm_service._catalog, "query", new_callable=AsyncMock, return_value=mock_result
            ),
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter"),
        ):
            await dvm_service.run()

        assert mock_client.send_event_builder.call_count == 3

    async def test_processed_ids_reset(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(
            event_id="trigger",
            tags=[["param", "table", "relay"]],
        )
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client

        dvm_service._processed_ids = {str(i) for i in range(10_001)}

        mock_result = QueryResult(rows=[], total=0, limit=100, offset=0)
        with (
            patch.object(
                dvm_service._catalog, "query", new_callable=AsyncMock, return_value=mock_result
            ),
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter"),
        ):
            await dvm_service.run()

        assert len(dvm_service._processed_ids) == 0


# ============================================================================
# P-tag Targeting
# ============================================================================


class TestDvmPtagTargeting:
    async def test_p_tag_for_other_pubkey_skips_event(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["p", "other_pubkey_hex"], ["param", "table", "relay"]])
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client

        with patch.object(dvm_service, "set_gauge"), patch.object(dvm_service, "inc_counter"):
            await dvm_service.run()

        mock_client.send_event_builder.assert_not_called()

    async def test_no_p_tag_processes_event(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["param", "table", "relay"]])
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client

        mock_result = QueryResult(rows=[], total=0, limit=100, offset=0)
        with (
            patch.object(
                dvm_service._catalog, "query", new_callable=AsyncMock, return_value=mock_result
            ),
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter"),
        ):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()


# ============================================================================
# Error Handling
# ============================================================================


class TestDvmJobErrorHandling:
    @pytest.mark.parametrize(
        "error",
        [
            CatalogError("query failed"),
            OSError("network error"),
            TimeoutError("timed out"),
        ],
        ids=["CatalogError", "OSError", "TimeoutError"],
    )
    async def test_caught_error_publishes_error_and_increments_failed(
        self, dvm_service: Dvm, error: Exception
    ) -> None:
        event = _make_mock_event(tags=[["param", "table", "relay"]])
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client

        with (
            patch.object(
                dvm_service._catalog,
                "query",
                new_callable=AsyncMock,
                side_effect=error,
            ),
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter") as mock_counter,
        ):
            await dvm_service.run()

        mock_counter.assert_any_call("requests_failed", 1)
        mock_client.send_event_builder.assert_called_once()

    async def test_error_event_publish_failure_suppressed(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["param", "table", "relay"]])
        mock_client = _make_client_with_events([event])
        mock_client.send_event_builder = AsyncMock(side_effect=OSError("relay down"))
        dvm_service._client = mock_client

        with (
            patch.object(
                dvm_service._catalog,
                "query",
                new_callable=AsyncMock,
                side_effect=CatalogError("query failed"),
            ),
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter") as mock_counter,
        ):
            await dvm_service.run()

        mock_counter.assert_any_call("requests_failed", 1)


# ============================================================================
# Metrics
# ============================================================================


class TestDvmMetrics:
    async def test_report_metrics_emits_requests_total(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["param", "table", "relay"], ["param", "limit", "5"]])
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client

        mock_result = QueryResult(
            rows=[{"url": "wss://x", "network": "clearnet"}],
            total=1,
            limit=5,
            offset=0,
        )

        with (
            patch.object(
                dvm_service._catalog, "query", new_callable=AsyncMock, return_value=mock_result
            ),
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter") as mock_counter,
        ):
            await dvm_service.run()

        mock_counter.assert_any_call("requests_total", 1)


# ============================================================================
# Publishing Guards (client is None)
# ============================================================================


class TestDvmPublishingGuards:
    async def test_fetch_job_requests_no_client(self, dvm_service: Dvm) -> None:
        dvm_service._client = None
        result = await dvm_service._fetch_job_requests()
        assert result == []

    async def test_send_event_no_client(self, dvm_service: Dvm) -> None:
        dvm_service._client = None
        await dvm_service._send_event(build_error_event("eid", "pk", "err"))

    async def test_publish_announcement_no_client(self, dvm_service: Dvm) -> None:
        dvm_service._client = None
        await dvm_service._publish_announcement()

    async def test_publish_announcement_sends_event(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        mock_client.send_event_builder = AsyncMock()
        dvm_service._client = mock_client

        await dvm_service._publish_announcement()

        mock_client.send_event_builder.assert_called_once()


# ============================================================================
# Parse Job Params
# ============================================================================

_KEYS = Keys.generate()


def _make_utils_mock_event(tags: list[list[str]]) -> MagicMock:
    event = MagicMock()
    mock_tags = []
    for tag_values in tags:
        mock_tag = MagicMock()
        mock_tag.as_vec.return_value = tag_values
        mock_tags.append(mock_tag)
    tag_list = MagicMock()
    tag_list.to_vec.return_value = mock_tags
    event.tags.return_value = tag_list
    return event


def _tags_dict(event) -> dict[str, list[list[str]]]:
    result: dict[str, list[list[str]]] = {}
    for tag in event.tags().to_vec():
        vec = tag.as_vec()
        result.setdefault(vec[0], []).append(vec)
    return result


class TestParseJobParams:
    def test_basic_params(self) -> None:
        event = _make_utils_mock_event(
            tags=[
                ["param", "table", "relay"],
                ["param", "limit", "50"],
                ["param", "offset", "10"],
            ]
        )
        params = parse_job_params(event)
        assert params["table"] == "relay"
        assert params["limit"] == "50"
        assert params["offset"] == "10"

    def test_bid_tag(self) -> None:
        event = _make_utils_mock_event(
            tags=[
                ["param", "table", "relay"],
                ["bid", "5000"],
            ]
        )
        params = parse_job_params(event)
        assert params["bid"] == 5000

    def test_invalid_bid_ignored(self) -> None:
        event = _make_utils_mock_event(
            tags=[
                ["param", "table", "relay"],
                ["bid", "not_a_number"],
            ]
        )
        params = parse_job_params(event)
        assert "bid" not in params

    def test_empty_tags(self) -> None:
        event = _make_utils_mock_event(tags=[])
        assert parse_job_params(event) == {}

    def test_filter_and_sort(self) -> None:
        event = _make_utils_mock_event(
            tags=[
                ["param", "table", "relay"],
                ["param", "filter", "network=clearnet"],
                ["param", "sort", "url:asc"],
            ]
        )
        params = parse_job_params(event)
        assert params["filter"] == "network=clearnet"
        assert params["sort"] == "url:asc"

    def test_short_tags_ignored(self) -> None:
        event = _make_utils_mock_event(tags=[["param"], ["bid"], ["x"]])
        assert parse_job_params(event) == {}

    def test_param_with_only_two_elements_ignored(self) -> None:
        event = _make_utils_mock_event(tags=[["param", "table"]])
        assert parse_job_params(event) == {}


# ============================================================================
# Parse Query Filters
# ============================================================================


class TestParseQueryFilters:
    def test_empty_string(self) -> None:
        assert parse_query_filters("") is None

    def test_single_filter(self) -> None:
        assert parse_query_filters("network=clearnet") == {"network": "clearnet"}

    def test_multiple_filters(self) -> None:
        result = parse_query_filters("network=clearnet,kind=>:100")
        assert result is not None
        assert result["network"] == "clearnet"
        assert result["kind"] == ">:100"

    def test_no_equals(self) -> None:
        assert parse_query_filters("invalid") is None

    def test_whitespace_trimmed(self) -> None:
        result = parse_query_filters(" network = clearnet , kind = 1 ")
        assert result == {"network": "clearnet", "kind": "1"}

    def test_mixed_valid_and_invalid_parts(self) -> None:
        result = parse_query_filters("network=clearnet,invalid,kind=1")
        assert result == {"network": "clearnet", "kind": "1"}


# ============================================================================
# Build Result Event
# ============================================================================


class TestBuildResultEvent:
    def test_result_kind_is_request_plus_1000(self) -> None:
        result = QueryResult(rows=[], total=0, limit=10, offset=0)
        event = build_result_event(5050, "eid", "pk", result, 0).sign_with_keys(_KEYS)
        assert event.kind().as_u16() == 6050

    def test_content_contains_data_and_meta(self) -> None:
        result = QueryResult(rows=[{"url": "wss://r.io"}], total=1, limit=10, offset=0)
        event = build_result_event(5050, "eid", "pk", result, 0).sign_with_keys(_KEYS)
        content = json.loads(event.content())
        assert content["data"] == [{"url": "wss://r.io"}]
        assert content["meta"] == {"total": 1, "limit": 10, "offset": 0}

    def test_amount_tag_included_when_price_positive(self) -> None:
        result = QueryResult(rows=[], total=0, limit=10, offset=0)
        event = build_result_event(5050, "eid", "pk", result, 500).sign_with_keys(_KEYS)
        tags = _tags_dict(event)
        assert tags["amount"] == [["amount", "500"]]

    def test_no_amount_tag_when_price_zero(self) -> None:
        result = QueryResult(rows=[], total=0, limit=10, offset=0)
        event = build_result_event(5050, "eid", "pk", result, 0).sign_with_keys(_KEYS)
        tags = _tags_dict(event)
        assert "amount" not in tags


# ============================================================================
# Build Error Event
# ============================================================================


class TestBuildErrorEvent:
    def test_kind_7000(self) -> None:
        event = build_error_event("eid", "pk", "something broke").sign_with_keys(_KEYS)
        assert event.kind().as_u16() == 7000

    def test_status_tag_contains_error_message(self) -> None:
        event = build_error_event("eid", "pk", "something broke").sign_with_keys(_KEYS)
        tags = _tags_dict(event)
        assert tags["status"] == [["status", "error", "something broke"]]


# ============================================================================
# Build Payment Required Event
# ============================================================================


class TestBuildPaymentRequiredEvent:
    def test_kind_7000(self) -> None:
        event = build_payment_required_event("eid", "pk", 5000).sign_with_keys(_KEYS)
        assert event.kind().as_u16() == 7000

    def test_amount_tag_present(self) -> None:
        event = build_payment_required_event("eid", "pk", 5000).sign_with_keys(_KEYS)
        tags = _tags_dict(event)
        assert tags["amount"] == [["amount", "5000"]]

    def test_status_tag_payment_required(self) -> None:
        event = build_payment_required_event("eid", "pk", 5000).sign_with_keys(_KEYS)
        tags = _tags_dict(event)
        assert len(tags["status"]) == 1
        assert tags["status"][0][1] == "payment-required"


# ============================================================================
# Build Announcement Event
# ============================================================================


class TestBuildAnnouncementEvent:
    def test_kind_31990(self) -> None:
        event = build_announcement_event("dtag", 5050, "DVM", "about", ["relay"]).sign_with_keys(
            _KEYS
        )
        assert event.kind().as_u16() == 31990

    def test_content_contains_name_about_tables(self) -> None:
        event = build_announcement_event("dtag", 5050, "MyDVM", "desc", ["a", "b"]).sign_with_keys(
            _KEYS
        )
        content = json.loads(event.content())
        assert content["name"] == "MyDVM"
        assert content["about"] == "desc"
        assert content["tables"] == ["a", "b"]

    def test_d_and_k_tags(self) -> None:
        event = build_announcement_event("my-d", 5050, "n", "a", []).sign_with_keys(_KEYS)
        tags = _tags_dict(event)
        assert tags["d"] == [["d", "my-d"]]
        assert tags["k"] == [["k", "5050"]]
