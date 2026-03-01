"""Unit tests for services.dvm.service module — service logic.

Tests:
- Dvm service initialization
- Dvm._is_table_enabled and _get_table_price policy checks
- Dvm._parse_job_params event tag parsing
- Dvm._parse_query_filters filter string parsing
- Dvm.run() cycle (mocked Nostr client)
- Dvm Prometheus counter emissions
"""

from unittest.mock import AsyncMock, MagicMock, patch

from bigbrotr.models.constants import ServiceName
from bigbrotr.services.common.catalog import QueryResult
from bigbrotr.services.dvm.service import Dvm
from tests.unit.services.dvm.conftest import _make_mock_event


class TestDvm:
    """Tests for Dvm service class."""

    def test_service_name(self) -> None:
        assert Dvm.SERVICE_NAME == ServiceName.DVM

    def test_init(self, dvm_service: Dvm) -> None:
        assert dvm_service._client is None
        assert dvm_service._last_fetch_ts == 0
        assert dvm_service._processed_ids == set()


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


class TestDvmMetrics:
    """Tests for Dvm Prometheus counter emissions."""

    async def test_report_metrics_emits_total_jobs_received(self, dvm_service: Dvm) -> None:
        """Cumulative total_jobs_received counter emitted after cycle with events."""
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
