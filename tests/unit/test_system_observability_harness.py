from __future__ import annotations

import io
import json
from base64 import b64encode
from urllib import error

import pytest

from tests.system.harness import AlertmanagerApi, GrafanaApi, PrometheusApi


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def read(self) -> bytes:
        if isinstance(self._payload, bytes):
            return self._payload
        if isinstance(self._payload, str):
            return self._payload.encode()
        return json.dumps(self._payload).encode()


class TestPrometheusApi:
    def test_query_encodes_expression(self, mocker: pytest.MockFixture) -> None:
        api = PrometheusApi("http://prometheus:9090")
        mock_urlopen = mocker.patch(
            "tests.system.harness.observability.request.urlopen",
            return_value=_FakeResponse({"status": "success"}),
        )

        payload = api.query('up{job="finder"}')

        req = mock_urlopen.call_args.args[0]
        assert (
            req.full_url == "http://prometheus:9090/api/v1/query?query=up%7Bjob%3D%22finder%22%7D"
        )
        assert payload == {"status": "success"}

    def test_targets_hits_expected_endpoint(self, mocker: pytest.MockFixture) -> None:
        api = PrometheusApi("http://prometheus:9090")
        mock_urlopen = mocker.patch(
            "tests.system.harness.observability.request.urlopen",
            return_value=_FakeResponse({"data": {"activeTargets": []}}),
        )

        api.targets()

        req = mock_urlopen.call_args.args[0]
        assert req.full_url == "http://prometheus:9090/api/v1/targets"

    def test_health_reads_plain_text_endpoint(self, mocker: pytest.MockFixture) -> None:
        api = PrometheusApi("http://prometheus:9090")
        mocker.patch(
            "tests.system.harness.observability.request.urlopen",
            return_value=_FakeResponse("Prometheus is Healthy.\n"),
        )

        assert api.health() == "Prometheus is Healthy.\n"


class TestGrafanaApi:
    def test_health_hits_expected_endpoint(self, mocker: pytest.MockFixture) -> None:
        api = GrafanaApi("http://grafana:3000")
        mock_urlopen = mocker.patch(
            "tests.system.harness.observability.request.urlopen",
            return_value=_FakeResponse({"database": "ok"}),
        )

        payload = api.health()

        req = mock_urlopen.call_args.args[0]
        assert req.full_url == "http://grafana:3000/api/health"
        assert payload == {"database": "ok"}

    def test_basic_auth_is_sent_when_credentials_are_configured(
        self,
        mocker: pytest.MockFixture,
    ) -> None:
        api = GrafanaApi("http://grafana:3000", username="admin", password="secret")
        mock_urlopen = mocker.patch(
            "tests.system.harness.observability.request.urlopen",
            return_value=_FakeResponse([{"uid": "prometheus"}]),
        )

        api.datasources()

        req = mock_urlopen.call_args.args[0]
        assert req.get_header("Authorization") == f"Basic {b64encode(b'admin:secret').decode()}"

    def test_dashboards_uses_search_endpoint(self, mocker: pytest.MockFixture) -> None:
        api = GrafanaApi("http://grafana:3000")
        mock_urlopen = mocker.patch(
            "tests.system.harness.observability.request.urlopen",
            return_value=_FakeResponse([{"uid": "finder"}]),
        )

        payload = api.dashboards()

        req = mock_urlopen.call_args.args[0]
        assert req.full_url == "http://grafana:3000/api/search?type=dash-db"
        assert payload == [{"uid": "finder"}]

    def test_datasource_uses_uid_endpoint(self, mocker: pytest.MockFixture) -> None:
        api = GrafanaApi("http://grafana:3000")
        mock_urlopen = mocker.patch(
            "tests.system.harness.observability.request.urlopen",
            return_value=_FakeResponse({"uid": "prometheus"}),
        )

        payload = api.datasource("prometheus")

        req = mock_urlopen.call_args.args[0]
        assert req.full_url == "http://grafana:3000/api/datasources/uid/prometheus"
        assert payload == {"uid": "prometheus"}

    def test_datasource_health_uses_uid_health_endpoint(self, mocker: pytest.MockFixture) -> None:
        api = GrafanaApi("http://grafana:3000")
        mock_urlopen = mocker.patch(
            "tests.system.harness.observability.request.urlopen",
            return_value=_FakeResponse({"status": "OK"}),
        )

        payload = api.datasource_health("prometheus")

        req = mock_urlopen.call_args.args[0]
        assert req.full_url == "http://grafana:3000/api/datasources/uid/prometheus/health"
        assert payload == {"status": "OK"}

    def test_dashboard_uses_uid_endpoint(self, mocker: pytest.MockFixture) -> None:
        api = GrafanaApi("http://grafana:3000")
        mock_urlopen = mocker.patch(
            "tests.system.harness.observability.request.urlopen",
            return_value=_FakeResponse({"dashboard": {"uid": "finder"}}),
        )

        payload = api.dashboard("finder")

        req = mock_urlopen.call_args.args[0]
        assert req.full_url == "http://grafana:3000/api/dashboards/uid/finder"
        assert payload == {"dashboard": {"uid": "finder"}}

    def test_rejects_partial_auth_configuration(self) -> None:
        with pytest.raises(ValueError, match="both username and password"):
            GrafanaApi("http://grafana:3000", username="admin")


class TestAlertmanagerApi:
    def test_status_hits_expected_endpoint(self, mocker: pytest.MockFixture) -> None:
        api = AlertmanagerApi("http://alertmanager:9093")
        mock_urlopen = mocker.patch(
            "tests.system.harness.observability.request.urlopen",
            return_value=_FakeResponse({"config": {"original": "route:\n  receiver: default\n"}}),
        )

        payload = api.status()

        req = mock_urlopen.call_args.args[0]
        assert req.full_url == "http://alertmanager:9093/api/v2/status"
        assert payload == {"config": {"original": "route:\n  receiver: default\n"}}

    def test_alerts_hits_expected_endpoint(self, mocker: pytest.MockFixture) -> None:
        api = AlertmanagerApi("http://alertmanager:9093")
        mock_urlopen = mocker.patch(
            "tests.system.harness.observability.request.urlopen",
            return_value=_FakeResponse([{"labels": {"alertname": "BigBrotrDown"}}]),
        )

        payload = api.alerts()

        req = mock_urlopen.call_args.args[0]
        assert req.full_url == "http://alertmanager:9093/api/v2/alerts"
        assert payload == [{"labels": {"alertname": "BigBrotrDown"}}]

    def test_http_errors_raise_observability_error(self, mocker: pytest.MockFixture) -> None:
        api = GrafanaApi("http://grafana:3000")
        http_error = error.HTTPError(
            url="http://grafana:3000/api/health",
            code=500,
            msg="boom",
            hdrs=None,
            fp=io.BytesIO(b"grafana down"),
        )
        mocker.patch(
            "tests.system.harness.observability.request.urlopen",
            side_effect=http_error,
        )

        with pytest.raises(RuntimeError, match="HTTP 500: grafana down"):
            api.health()
