"""Deterministic network fault-control helpers for higher-band system tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib import error, request


@dataclass(frozen=True, slots=True)
class FaultControlPortPlan:
    """Admin and proxy-listen ports reserved for one fault-control slot."""

    admin: int
    first_proxy: int

    @classmethod
    def for_slot(cls, slot: int) -> FaultControlPortPlan:
        """Build the deterministic Toxiproxy-style port plan for one slot."""
        if slot < 0:
            raise ValueError("Fault-control slot must be non-negative")
        base = 19500 + (slot * 20)
        return cls(admin=base, first_proxy=base + 1)

    def proxy_port(self, offset: int) -> int:
        """Return one deterministic proxy port inside the reserved slot."""
        if offset < 0:
            raise ValueError("Fault-control proxy offset must be non-negative")
        return self.first_proxy + offset


@dataclass(frozen=True, slots=True)
class ProxySpec:
    """Runtime description of one proxied upstream target."""

    name: str
    upstream_host: str
    upstream_port: int
    listen_host: str = "0.0.0.0"
    listen_port: int = 0
    enabled: bool = True

    def to_payload(self) -> dict[str, object]:
        """Serialize the proxy to the Toxiproxy admin payload."""
        return {
            "name": self.name,
            "listen": f"{self.listen_host}:{self.listen_port}",
            "upstream": f"{self.upstream_host}:{self.upstream_port}",
            "enabled": self.enabled,
        }


@dataclass(frozen=True, slots=True)
class ToxicSpec:
    """Runtime description of one injected fault toxic."""

    name: str
    toxic_type: str
    attributes: dict[str, object] = field(default_factory=dict)
    stream: str = "downstream"
    toxicity: float = 1.0

    def to_payload(self) -> dict[str, object]:
        """Serialize the toxic to the admin API payload."""
        return {
            "name": self.name,
            "type": self.toxic_type,
            "stream": self.stream,
            "toxicity": self.toxicity,
            "attributes": self.attributes,
        }


class FaultControlError(RuntimeError):
    """Raised when the fault-control admin plane rejects a request."""


@dataclass(frozen=True, slots=True)
class ToxiproxyClient:
    """Small admin client for deterministic proxy and toxic control."""

    base_url: str
    timeout: float = 5.0

    def __post_init__(self) -> None:
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("Fault-control base_url must use http:// or https://")

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> object | None:
        url = f"{self.base_url.rstrip('/')}{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"content-type": "application/json"} if payload is not None else {}
        req = request.Request(url, data=data, headers=headers, method=method)  # noqa: S310

        try:
            with request.urlopen(req, timeout=self.timeout) as response:  # noqa: S310
                body = response.read().decode()
        except error.HTTPError as exc:
            body = exc.read().decode()
            raise FaultControlError(
                f"Fault-control request failed with HTTP {exc.code}: {body or exc.reason}"
            ) from exc
        except error.URLError as exc:
            raise FaultControlError(f"Fault-control request failed: {exc.reason}") from exc

        if not body:
            return None
        return json.loads(body)

    def reset_state(self) -> None:
        """Delete all proxies and toxics from the admin plane."""
        self._request("POST", "/reset")

    def list_proxies(self) -> dict[str, object]:
        """Return the current proxy map."""
        payload = self._request("GET", "/proxies")
        if not isinstance(payload, dict):
            raise FaultControlError("Fault-control proxy listing returned a non-object payload")
        return payload

    def create_proxy(self, spec: ProxySpec) -> dict[str, object]:
        """Create one proxy."""
        payload = self._request("POST", "/proxies", spec.to_payload())
        if not isinstance(payload, dict):
            raise FaultControlError("Fault-control proxy creation returned a non-object payload")
        return payload

    def delete_proxy(self, proxy_name: str) -> None:
        """Delete one proxy by name."""
        self._request("DELETE", f"/proxies/{proxy_name}")

    def add_toxic(self, proxy_name: str, toxic: ToxicSpec) -> dict[str, object]:
        """Attach one toxic to a proxy."""
        payload = self._request("POST", f"/proxies/{proxy_name}/toxics", toxic.to_payload())
        if not isinstance(payload, dict):
            raise FaultControlError("Fault-control toxic creation returned a non-object payload")
        return payload

    def remove_toxic(self, proxy_name: str, toxic_name: str) -> None:
        """Remove one toxic from a proxy."""
        self._request("DELETE", f"/proxies/{proxy_name}/toxics/{toxic_name}")
