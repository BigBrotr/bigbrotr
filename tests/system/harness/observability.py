"""HTTP inspection helpers for higher-band observability surfaces."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import error, parse, request


class ObservabilityApiError(RuntimeError):
    """Raised when an observability API request fails or returns invalid data."""


@dataclass(frozen=True, slots=True)
class _HttpClient:
    base_url: str
    timeout: float = 5.0

    def __post_init__(self) -> None:
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("Observability base_url must use http:// or https://")

    def _request_json(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> object:
        suffix = path
        if params:
            suffix = f"{path}?{parse.urlencode(params)}"
        url = f"{self.base_url.rstrip('/')}{suffix}"
        req = request.Request(url, method="GET")  # noqa: S310
        try:
            with request.urlopen(req, timeout=self.timeout) as response:  # noqa: S310
                body = response.read().decode()
        except error.HTTPError as exc:
            body = exc.read().decode()
            raise ObservabilityApiError(
                f"Observability request failed with HTTP {exc.code}: {body or exc.reason}"
            ) from exc
        except error.URLError as exc:
            raise ObservabilityApiError(f"Observability request failed: {exc.reason}") from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise ObservabilityApiError("Observability request returned invalid JSON") from exc

    def _request_text(self, path: str) -> str:
        url = f"{self.base_url.rstrip('/')}{path}"
        req = request.Request(url, method="GET")  # noqa: S310
        try:
            with request.urlopen(req, timeout=self.timeout) as response:  # noqa: S310
                return response.read().decode()
        except error.HTTPError as exc:
            body = exc.read().decode()
            raise ObservabilityApiError(
                f"Observability request failed with HTTP {exc.code}: {body or exc.reason}"
            ) from exc
        except error.URLError as exc:
            raise ObservabilityApiError(f"Observability request failed: {exc.reason}") from exc


@dataclass(frozen=True, slots=True)
class PrometheusApi(_HttpClient):
    """Prometheus inspection helpers."""

    def health(self) -> str:
        return self._request_text("/-/healthy")

    def ready(self) -> str:
        return self._request_text("/-/ready")

    def targets(self) -> object:
        return self._request_json("/api/v1/targets")

    def alerts(self) -> object:
        return self._request_json("/api/v1/alerts")

    def query(self, expression: str) -> object:
        return self._request_json("/api/v1/query", params={"query": expression})


@dataclass(frozen=True, slots=True)
class GrafanaApi(_HttpClient):
    """Grafana inspection helpers."""

    def health(self) -> object:
        return self._request_json("/api/health")

    def datasources(self) -> object:
        return self._request_json("/api/datasources")

    def dashboards(self) -> object:
        return self._request_json("/api/search", params={"type": "dash-db"})


@dataclass(frozen=True, slots=True)
class AlertmanagerApi(_HttpClient):
    """Alertmanager inspection helpers."""

    def health(self) -> str:
        return self._request_text("/-/healthy")

    def status(self) -> object:
        return self._request_json("/api/v2/status")

    def alerts(self) -> object:
        return self._request_json("/api/v2/alerts")
