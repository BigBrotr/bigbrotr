from __future__ import annotations

import io
from urllib import error

import pytest

from tests.system.harness import MetricsScrapeError, fetch_metrics_snapshot, parse_metrics_text


class _FakeResponse:
    def __init__(self, body: str) -> None:
        self._body = body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body.encode()


_METRICS_TEXT = """
# HELP service_info Service information and metadata
# TYPE service_info gauge
service_info{service="finder"} 1
# HELP service_gauge Service gauge values (point-in-time state)
# TYPE service_gauge gauge
service_gauge{name="last_cycle_timestamp",service="finder"} 1700000000
# HELP service_counter_total Service counter values (cumulative totals)
# TYPE service_counter_total counter
service_counter_total{name="cycles_success",service="finder"} 2
# HELP cycle_duration_seconds Duration of service cycle in seconds
# TYPE cycle_duration_seconds histogram
cycle_duration_seconds_bucket{service="finder",le="1.0"} 0
cycle_duration_seconds_bucket{service="finder",le="+Inf"} 1
cycle_duration_seconds_count{service="finder"} 1
cycle_duration_seconds_sum{service="finder"} 0.5
"""


class TestParseMetricsText:
    def test_parses_expected_families_and_labels(self) -> None:
        snapshot = parse_metrics_text(_METRICS_TEXT)

        assert snapshot.family_names == {
            "service_info",
            "service_gauge",
            "service_counter",
            "cycle_duration_seconds",
        }
        assert snapshot.single_value("service_info", service="finder") == 1.0
        assert (
            snapshot.single_value(
                "service_gauge",
                service="finder",
                name="last_cycle_timestamp",
            )
            == 1_700_000_000.0
        )
        assert (
            snapshot.single_value(
                "service_counter_total",
                service="finder",
                name="cycles_success",
            )
            == 2.0
        )
        assert snapshot.single_value("cycle_duration_seconds_count", service="finder") == 1.0

    def test_single_value_requires_exact_match(self) -> None:
        snapshot = parse_metrics_text(_METRICS_TEXT)

        with pytest.raises(MetricsScrapeError, match="Expected exactly one sample"):
            snapshot.single_value("cycle_duration_seconds_bucket", service="finder")

    def test_invalid_payload_raises_metrics_error(self) -> None:
        with pytest.raises(MetricsScrapeError, match="not valid Prometheus text"):
            parse_metrics_text("not metrics")


class TestFetchMetricsSnapshot:
    def test_fetches_and_parses_metrics_payload(self, mocker: pytest.MockFixture) -> None:
        mock_urlopen = mocker.patch(
            "tests.system.harness.metrics.request.urlopen",
            return_value=_FakeResponse(_METRICS_TEXT),
        )

        snapshot = fetch_metrics_snapshot("http://metrics-host:8000")

        req = mock_urlopen.call_args.args[0]
        assert req.full_url == "http://metrics-host:8000/metrics"
        assert snapshot.single_value("service_info", service="finder") == 1.0

    def test_rejects_non_http_base_urls(self) -> None:
        with pytest.raises(ValueError, match="must use http:// or https://"):
            fetch_metrics_snapshot("ws://metrics-host:8000")

    def test_http_errors_raise_metrics_error(self, mocker: pytest.MockFixture) -> None:
        http_error = error.HTTPError(
            url="http://metrics-host:8000/metrics",
            code=500,
            msg="boom",
            hdrs=None,
            fp=io.BytesIO(b"metrics down"),
        )
        mocker.patch(
            "tests.system.harness.metrics.request.urlopen",
            side_effect=http_error,
        )

        with pytest.raises(MetricsScrapeError, match="HTTP 500: metrics down"):
            fetch_metrics_snapshot("http://metrics-host:8000")
