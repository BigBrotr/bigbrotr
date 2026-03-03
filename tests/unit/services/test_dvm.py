"""Unit tests for the dvm service package."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import Relay
from bigbrotr.models.constants import ServiceName
from bigbrotr.services.common.catalog import (
    Catalog,
    ColumnSchema,
    QueryResult,
    TableSchema,
)
from bigbrotr.services.common.configs import TableConfig
from bigbrotr.services.dvm.configs import DvmConfig
from bigbrotr.services.dvm.service import Dvm


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
        assert config.max_page_size == 1000
        assert config.announce is True
        assert config.tables == {}
        assert config.fetch_timeout == 30.0

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


# ============================================================================
# Service
# ============================================================================


class TestDvm:
    def test_service_name(self) -> None:
        assert Dvm.SERVICE_NAME == ServiceName.DVM

    def test_init(self, dvm_service: Dvm) -> None:
        assert dvm_service._client is None
        assert dvm_service._last_fetch_ts == 0
        assert dvm_service._processed_ids == set()


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


class TestParseJobParams:
    def test_basic_params(self) -> None:
        event = _make_mock_event(
            tags=[
                ["param", "table", "relay"],
                ["param", "limit", "50"],
                ["param", "offset", "10"],
            ]
        )
        params = Dvm._parse_job_params(event)
        assert params["table"] == "relay"
        assert params["limit"] == "50"
        assert params["offset"] == "10"

    def test_bid_tag(self) -> None:
        event = _make_mock_event(
            tags=[
                ["param", "table", "relay"],
                ["bid", "5000"],
            ]
        )
        params = Dvm._parse_job_params(event)
        assert params["bid"] == 5000

    def test_invalid_bid_ignored(self) -> None:
        event = _make_mock_event(
            tags=[
                ["param", "table", "relay"],
                ["bid", "not_a_number"],
            ]
        )
        params = Dvm._parse_job_params(event)
        assert "bid" not in params

    def test_empty_tags(self) -> None:
        event = _make_mock_event(tags=[])
        params = Dvm._parse_job_params(event)
        assert params == {}

    def test_filter_and_sort(self) -> None:
        event = _make_mock_event(
            tags=[
                ["param", "table", "relay"],
                ["param", "filter", "network=clearnet"],
                ["param", "sort", "url:asc"],
            ]
        )
        params = Dvm._parse_job_params(event)
        assert params["filter"] == "network=clearnet"
        assert params["sort"] == "url:asc"


class TestParseQueryFilters:
    def test_empty_string(self) -> None:
        assert Dvm._parse_query_filters("") is None

    def test_single_filter(self) -> None:
        result = Dvm._parse_query_filters("network=clearnet")
        assert result == {"network": "clearnet"}

    def test_multiple_filters(self) -> None:
        result = Dvm._parse_query_filters("network=clearnet,kind=>:100")
        assert result is not None
        assert result["network"] == "clearnet"
        assert result["kind"] == ">:100"

    def test_no_equals(self) -> None:
        result = Dvm._parse_query_filters("invalid")
        assert result is None


class TestDvmRun:
    async def test_run_no_client(self, dvm_service: Dvm) -> None:
        await dvm_service.run()

    async def test_run_no_events(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        events_obj = MagicMock()
        events_obj.to_vec.return_value = []
        mock_client.fetch_events = AsyncMock(return_value=events_obj)
        dvm_service._client = mock_client

        with (
            patch.object(dvm_service, "set_gauge") as mock_gauge,
            patch.object(dvm_service, "inc_counter"),
        ):
            await dvm_service.run()

        mock_gauge.assert_any_call("jobs_received", 0)

    async def test_run_processes_job(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        mock_client.send_event_builder = AsyncMock()

        event = _make_mock_event(
            tags=[
                ["param", "table", "relay"],
                ["param", "limit", "10"],
            ]
        )
        events_obj = MagicMock()
        events_obj.to_vec.return_value = [event]
        mock_client.fetch_events = AsyncMock(return_value=events_obj)
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
        mock_client = MagicMock()
        mock_client.send_event_builder = AsyncMock()

        event = _make_mock_event(
            event_id="dedup_id",
            tags=[
                ["param", "table", "relay"],
            ],
        )
        events_obj = MagicMock()
        events_obj.to_vec.return_value = [event]
        mock_client.fetch_events = AsyncMock(return_value=events_obj)
        dvm_service._client = mock_client
        dvm_service._processed_ids.add("dedup_id")

        with patch.object(dvm_service, "set_gauge"), patch.object(dvm_service, "inc_counter"):
            await dvm_service.run()

        mock_client.send_event_builder.assert_not_called()

    async def test_run_disabled_table(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        mock_client.send_event_builder = AsyncMock()

        event = _make_mock_event(
            tags=[
                ["param", "table", "service_state"],
            ]
        )
        events_obj = MagicMock()
        events_obj.to_vec.return_value = [event]
        mock_client.fetch_events = AsyncMock(return_value=events_obj)
        dvm_service._client = mock_client

        with patch.object(dvm_service, "set_gauge"), patch.object(dvm_service, "inc_counter"):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()

    async def test_run_payment_required(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        mock_client.send_event_builder = AsyncMock()

        event = _make_mock_event(
            tags=[
                ["param", "table", "premium_data"],
            ]
        )
        events_obj = MagicMock()
        events_obj.to_vec.return_value = [event]
        mock_client.fetch_events = AsyncMock(return_value=events_obj)
        dvm_service._client = mock_client

        with patch.object(dvm_service, "set_gauge"), patch.object(dvm_service, "inc_counter"):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()

    async def test_run_sufficient_bid(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        mock_client.send_event_builder = AsyncMock()

        event = _make_mock_event(
            tags=[
                ["param", "table", "premium_data"],
                ["bid", "10000"],
            ]
        )
        events_obj = MagicMock()
        events_obj.to_vec.return_value = [event]
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

        mock_client.send_event_builder.assert_called_once()

    async def test_run_invalid_limit(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        mock_client.send_event_builder = AsyncMock()

        event = _make_mock_event(
            tags=[
                ["param", "table", "relay"],
                ["param", "limit", "not_a_number"],
            ]
        )
        events_obj = MagicMock()
        events_obj.to_vec.return_value = [event]
        mock_client.fetch_events = AsyncMock(return_value=events_obj)
        dvm_service._client = mock_client

        with patch.object(dvm_service, "set_gauge"), patch.object(dvm_service, "inc_counter"):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()

    async def test_run_updates_fetch_ts_before_processing(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        mock_client.send_event_builder = AsyncMock()

        event = _make_mock_event(
            tags=[
                ["param", "table", "relay"],
            ]
        )
        events_obj = MagicMock()
        events_obj.to_vec.return_value = [event]
        mock_client.fetch_events = AsyncMock(return_value=events_obj)
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
            tags=[
                ["param", "table", "service_state"],
            ],
        )
        event2 = _make_mock_event(
            event_id="ok_pub",
            tags=[
                ["param", "table", "relay"],
            ],
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
        mock_client = MagicMock()
        mock_client.send_event_builder = AsyncMock()

        event = _make_mock_event(
            event_id="trigger",
            tags=[
                ["param", "table", "relay"],
            ],
        )
        events_obj = MagicMock()
        events_obj.to_vec.return_value = [event]
        mock_client.fetch_events = AsyncMock(return_value=events_obj)
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
# Metrics
# ============================================================================


class TestDvmMetrics:
    async def test_report_metrics_emits_total_jobs_received(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        mock_client.send_event_builder = AsyncMock()

        event = _make_mock_event(tags=[["param", "table", "relay"], ["param", "limit", "5"]])
        events_obj = MagicMock()
        events_obj.to_vec.return_value = [event]
        mock_client.fetch_events = AsyncMock(return_value=events_obj)
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

        mock_counter.assert_any_call("total_jobs_received", 1)
