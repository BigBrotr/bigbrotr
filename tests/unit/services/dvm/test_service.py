"""Unit tests for services.dvm.service module.

Tests:
- DvmConfig defaults and validation
- Dvm service initialization
- Dvm._is_table_enabled and _get_table_price policy checks
- Dvm._parse_job_params event tag parsing
- Dvm._parse_query_filters filter string parsing
- Dvm.run() cycle (mocked Nostr client)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models.constants import ServiceName
from bigbrotr.services.common.catalog import (
    Catalog,
    ColumnSchema,
    QueryResult,
    TableSchema,
)
from bigbrotr.services.common.configs import TableConfig
from bigbrotr.services.dvm.service import Dvm, DvmConfig


# Valid secp256k1 test key (DO NOT USE IN PRODUCTION)
VALID_HEX_KEY = (
    "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"  # pragma: allowlist secret
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _set_private_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set PRIVATE_KEY environment variable for all DVM tests."""
    monkeypatch.setenv("PRIVATE_KEY", VALID_HEX_KEY)


@pytest.fixture
def dvm_config() -> DvmConfig:
    """Minimal DVM config for testing."""
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
    """Catalog pre-populated for DVM tests."""
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
    """Dvm service with mocked catalog and client."""
    service = Dvm(brotr=mock_brotr, config=dvm_config)
    service._catalog = sample_dvm_catalog
    return service


def _make_mock_event(
    event_id: str = "abc123",
    author_hex: str = "author_pubkey_hex",
    tags: list[list[str]] | None = None,
) -> MagicMock:
    """Create a mock Nostr event for testing."""
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
# DvmConfig Tests
# ============================================================================


class TestDvmConfig:
    """Tests for DvmConfig Pydantic model."""

    def test_default_values(self) -> None:
        config = DvmConfig(relays=["wss://relay.example.com"])
        assert config.kind == 5050
        assert config.max_page_size == 1000
        assert config.announce is True
        assert config.tables == {}
        assert config.fetch_timeout == 30.0

    def test_custom_fetch_timeout(self) -> None:
        config = DvmConfig(relays=["wss://relay.example.com"], fetch_timeout=60.0)
        assert config.fetch_timeout == 60.0

    def test_requires_relays(self) -> None:
        with pytest.raises(ValueError):
            DvmConfig(relays=[])

    def test_kind_range(self) -> None:
        with pytest.raises(ValueError):
            DvmConfig(relays=["wss://x"], kind=4000)

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
        """Test that invalid relay URLs are rejected."""
        with pytest.raises(ValueError, match="Invalid relay URL"):
            DvmConfig(relays=["not_a_url"])

    def test_valid_relay_urls_accepted(self) -> None:
        """Test that valid WebSocket relay URLs are accepted."""
        config = DvmConfig(relays=["wss://relay.damus.io", "wss://nos.lol"])
        assert len(config.relays) == 2


# ============================================================================
# Dvm Service Tests
# ============================================================================


class TestDvm:
    """Tests for Dvm service class."""

    def test_service_name(self) -> None:
        assert Dvm.SERVICE_NAME == ServiceName.DVM

    def test_init(self, dvm_service: Dvm) -> None:
        assert dvm_service._client is None
        assert dvm_service._last_fetch_ts == 0
        assert dvm_service._processed_ids == set()


# ============================================================================
# Table Policy Tests
# ============================================================================


class TestDvmTableAccessPolicy:
    """Tests for Dvm._is_table_enabled and _get_table_price."""

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


# ============================================================================
# Event Parsing Tests
# ============================================================================


class TestParseJobParams:
    """Tests for Dvm._parse_job_params."""

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
    """Tests for Dvm._parse_query_filters."""

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


# ============================================================================
# Run Cycle Tests
# ============================================================================


class TestDvmRun:
    """Tests for Dvm.run() cycle."""

    async def test_run_no_client(self, dvm_service: Dvm) -> None:
        # No client means no-op
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

        # Metrics should still be reported even with no events
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

        # Should have published a result event
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

        # Should have published an error (kind 7000)
        mock_client.send_event_builder.assert_called_once()

    async def test_run_payment_required(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        mock_client.send_event_builder = AsyncMock()

        event = _make_mock_event(
            tags=[
                ["param", "table", "premium_data"],
                # No bid tag -> bid defaults to 0 -> price is 5000 -> payment required
            ]
        )
        events_obj = MagicMock()
        events_obj.to_vec.return_value = [event]
        mock_client.fetch_events = AsyncMock(return_value=events_obj)
        dvm_service._client = mock_client

        with patch.object(dvm_service, "set_gauge"), patch.object(dvm_service, "inc_counter"):
            await dvm_service.run()

        # Should have published a payment-required event
        mock_client.send_event_builder.assert_called_once()

    async def test_run_sufficient_bid(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        mock_client.send_event_builder = AsyncMock()

        event = _make_mock_event(
            tags=[
                ["param", "table", "premium_data"],
                ["bid", "10000"],  # Sufficient bid (>= 5000)
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

        # Should have published a result (not payment-required)
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

        # Should have published an error (kind 7000) for invalid limit
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
            # First call (before fetch) returns 1000, second call would return 2000
            mock_time.time.side_effect = [1000, 2000]
            mock_time.monotonic.return_value = 0.0
            await dvm_service.run()

        # fetch_ts should be 1000 (captured before fetch), not 2000
        assert dvm_service._last_fetch_ts == 1000

    async def test_run_publish_error_failure_does_not_abort_batch(self, dvm_service: Dvm) -> None:
        """If _publish_error fails, the batch continues instead of crashing."""
        mock_client = MagicMock()
        # 1st call: _publish_error in _handle_job (disabled table) raises
        # 2nd call: _publish_error retry in _process_event catch block succeeds
        # 3rd call: _publish_result for second event succeeds
        mock_client.send_event_builder = AsyncMock(
            side_effect=[OSError("relay offline"), None, None],
        )

        # Two events: first targets a disabled table (triggers publish_error),
        # second targets a valid table (should still be processed)
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
            # Should NOT raise despite publish_error failure on first event
            await dvm_service.run()

        # 3 calls: failed publish + retry publish + successful result
        assert mock_client.send_event_builder.call_count == 3

    async def test_processed_ids_reset(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        mock_client.send_event_builder = AsyncMock()

        # Need at least one event so run() doesn't short-circuit before _manage_dedup_set
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

        # Fill up the set past threshold
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

        # Should have been cleared (10_001 >= _MAX_PROCESSED_IDS)
        assert len(dvm_service._processed_ids) == 0
