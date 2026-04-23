"""Deterministic network fault-control helpers for higher-band system tests."""

from __future__ import annotations

import hashlib
import http.client
import json
import subprocess
import time
from dataclasses import dataclass, field
from subprocess import CompletedProcess
from typing import TYPE_CHECKING
from urllib import error, request

from tests.integration.harness.postgres import (
    ensure_docker_available,
    ensure_testcontainers_environment,
)
from tests.system.harness.artifacts import sanitize_artifact_component


if TYPE_CHECKING:
    from pathlib import Path


TOXIPROXY_IMAGE = "ghcr.io/shopify/toxiproxy@sha256:9378ed52a28bc50edc1350f936f518f31fa95f0d15917d6eb40b8e376d1a214e"
TOXIPROXY_ADMIN_PORT = 8474
DEFAULT_FAULT_READY_TIMEOUT = 10.0
DEFAULT_FAULT_POLL_INTERVAL = 0.25
BIGBROTR_TOXIPROXY_PREFIX = "bigbrotr-toxiproxy-"


def build_fault_network_name(role: str, runtime_dir: Path) -> str:
    """Build a deterministic Docker network name for one fault-control runtime."""
    normalized_role = sanitize_artifact_component(role)
    digest = hashlib.sha256(str(runtime_dir.resolve()).encode()).hexdigest()[:12]
    return f"bigbrotr-fault-net-{normalized_role}-{digest}"


def build_fault_container_name(role: str, runtime_dir: Path) -> str:
    """Build a deterministic Toxiproxy container name for one runtime root."""
    normalized_role = sanitize_artifact_component(role)
    digest = hashlib.sha256(str(runtime_dir.resolve()).encode()).hexdigest()[:12]
    return f"{BIGBROTR_TOXIPROXY_PREFIX}{normalized_role}-{digest}"


def _docker_command(*args: str) -> tuple[str, ...]:
    return ("docker", *args)


def docker_network_exists(network_name: str) -> bool:
    """Return whether one Docker network currently exists."""
    result = subprocess.run(  # noqa: S603
        _docker_command("network", "inspect", network_name),
        check=False,
        text=True,
        capture_output=True,
    )
    return result.returncode == 0


def _docker_container_exists(container_ref: str) -> bool:
    result = subprocess.run(  # noqa: S603
        _docker_command("container", "inspect", container_ref),
        check=False,
        text=True,
        capture_output=True,
    )
    return result.returncode == 0


def _run_docker(*args: str) -> CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        _docker_command(*args),
        check=True,
        text=True,
        capture_output=True,
    )


def _ensure_fault_image(image: str) -> None:
    inspect_result = subprocess.run(  # noqa: S603
        _docker_command("image", "inspect", image),
        check=False,
        text=True,
        capture_output=True,
    )
    if inspect_result.returncode == 0:
        return
    _run_docker("pull", image)


def _list_bigbrotr_toxiproxy_containers() -> tuple[str, ...]:
    result = subprocess.run(  # noqa: S603
        _docker_command("ps", "-aq", "--filter", f"name={BIGBROTR_TOXIPROXY_PREFIX}"),
        check=True,
        text=True,
        capture_output=True,
    )
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def _container_uses_host_ports(container_ref: str, *, host: str, ports: frozenset[str]) -> bool:
    result = subprocess.run(  # noqa: S603
        _docker_command("inspect", container_ref),
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return False

    payload = json.loads(result.stdout)
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        return False

    port_bindings = payload[0].get("HostConfig", {}).get("PortBindings", {})
    if not isinstance(port_bindings, dict):
        return False

    for host_bindings in port_bindings.values():
        if not isinstance(host_bindings, list):
            continue
        for binding in host_bindings:
            if not isinstance(binding, dict):
                continue
            if binding.get("HostIp") == host and binding.get("HostPort") in ports:
                return True
    return False


def _remove_conflicting_toxiproxy_containers(*, host: str, ports: tuple[int, ...]) -> None:
    reserved_ports = frozenset(str(port) for port in ports)
    for container_ref in _list_bigbrotr_toxiproxy_containers():
        if not _container_uses_host_ports(container_ref, host=host, ports=reserved_ports):
            continue
        subprocess.run(  # noqa: S603
            _docker_command("rm", "-f", container_ref),
            check=False,
            text=True,
            capture_output=True,
        )


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
        except http.client.HTTPException as exc:
            raise FaultControlError(f"Fault-control request failed: {exc}") from exc

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

    def set_proxy_enabled(self, proxy_name: str, *, enabled: bool) -> dict[str, object]:
        """Enable or disable one proxy."""
        payload = self._request("POST", f"/proxies/{proxy_name}", {"enabled": enabled})
        if not isinstance(payload, dict):
            raise FaultControlError("Fault-control proxy update returned a non-object payload")
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


@dataclass(slots=True)
class DockerNetworkRuntime:
    """Lifecycle wrapper around a deterministic Docker bridge network."""

    role: str
    runtime_dir: Path
    network_id: str | None = field(init=False, default=None)

    @property
    def name(self) -> str:
        return build_fault_network_name(self.role, self.runtime_dir)

    def start(self) -> None:
        """Create the named Docker network."""
        if self.network_id is not None:
            raise RuntimeError("Fault-control Docker network is already running")
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        result = _run_docker("network", "create", self.name)
        self.network_id = result.stdout.strip() or self.name

    def inspect(self) -> dict[str, object]:
        """Return the raw inspect payload for the managed network."""
        result = _run_docker("network", "inspect", self.name)
        payload = json.loads(result.stdout)
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            raise RuntimeError("Fault-control network inspect payload was not a single JSON object")
        return payload[0]

    def stop(self) -> None:
        """Remove the Docker network if it still exists."""
        if self.network_id is None:
            return
        try:
            subprocess.run(  # noqa: S603
                _docker_command("network", "rm", self.name),
                check=False,
                text=True,
                capture_output=True,
            )
        finally:
            self.network_id = None

    def __enter__(self) -> DockerNetworkRuntime:
        self.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.stop()


@dataclass(slots=True)
class LocalToxiproxyRuntime:
    """Lifecycle wrapper around a local Toxiproxy container."""

    role: str
    runtime_dir: Path
    network_name: str
    port_plan: FaultControlPortPlan
    exposed_proxy_ports: tuple[int, ...]
    network_aliases: tuple[str, ...] = ()
    image: str = TOXIPROXY_IMAGE
    host: str = "127.0.0.1"
    ready_timeout: float = DEFAULT_FAULT_READY_TIMEOUT
    poll_interval: float = DEFAULT_FAULT_POLL_INTERVAL
    container_id: str | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if not self.role.strip():
            raise ValueError("Fault-control runtime role must not be blank")
        if self.ready_timeout <= 0:
            raise ValueError("Fault-control ready_timeout must be positive")
        if self.poll_interval <= 0:
            raise ValueError("Fault-control poll_interval must be positive")

    @property
    def container_name(self) -> str:
        return build_fault_container_name(self.role, self.runtime_dir)

    @property
    def admin_url(self) -> str:
        return f"http://{self.host}:{self.port_plan.admin}"

    @property
    def client(self) -> ToxiproxyClient:
        return ToxiproxyClient(self.admin_url)

    def proxy_ws_url(self, proxy_port: int) -> str:
        """Return the host-side WebSocket URL for one exposed proxy port."""
        return f"ws://{self.host}:{proxy_port}"

    def start(self) -> None:
        """Start the Toxiproxy container with deterministic port bindings."""
        if self.container_id is not None:
            raise RuntimeError("Fault-control runtime is already running")

        ensure_docker_available()
        ensure_testcontainers_environment()
        _ensure_fault_image(self.image)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        _remove_conflicting_toxiproxy_containers(
            host=self.host,
            ports=(self.port_plan.admin, *self.exposed_proxy_ports),
        )

        command = [
            "run",
            "-d",
            "--name",
            self.container_name,
            "--network",
            self.network_name,
            "-p",
            f"{self.host}:{self.port_plan.admin}:{TOXIPROXY_ADMIN_PORT}",
        ]
        for alias in self.network_aliases:
            command.extend(("--network-alias", alias))
        for proxy_port in self.exposed_proxy_ports:
            command.extend(("-p", f"{self.host}:{proxy_port}:{proxy_port}"))

        try:
            result = _run_docker(*command, self.image)
            self.container_id = result.stdout.strip()
            if not self.container_id:
                raise RuntimeError("Fault-control container did not return a container id")
        except Exception:
            self.stop()
            raise

    def wait_until_ready(self) -> None:
        """Wait until the Toxiproxy admin plane accepts requests."""
        deadline = time.monotonic() + self.ready_timeout
        last_error: FaultControlError | None = None
        while time.monotonic() < deadline:
            try:
                self.client.list_proxies()
                return
            except FaultControlError as exc:
                last_error = exc
                time.sleep(self.poll_interval)
        if last_error is None:
            raise RuntimeError(
                f"Fault-control runtime {self.container_name} did not become ready within "
                f"{self.ready_timeout} seconds"
            )
        raise RuntimeError(
            f"Fault-control runtime {self.container_name} did not become ready: {last_error}"
        ) from last_error

    def inspect(self) -> dict[str, object]:
        """Return the raw inspect payload for the managed container."""
        container_ref = self.container_id or self.container_name
        result = _run_docker("inspect", container_ref)
        payload = json.loads(result.stdout)
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            raise RuntimeError("Fault-control inspect payload was not a single JSON object")
        return payload[0]

    def logs(self) -> str:
        """Return the current Toxiproxy container logs."""
        container_ref = self.container_id or self.container_name
        return _run_docker("logs", container_ref).stdout

    def stop(self) -> None:
        """Force-remove the Toxiproxy container if it is still present."""
        container_ref = self.container_id or self.container_name
        if self.container_id is None and not _docker_container_exists(container_ref):
            return
        try:
            subprocess.run(  # noqa: S603
                _docker_command("rm", "-f", container_ref),
                check=False,
                text=True,
                capture_output=True,
            )
        finally:
            self.container_id = None

    def __enter__(self) -> LocalToxiproxyRuntime:
        self.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.stop()
