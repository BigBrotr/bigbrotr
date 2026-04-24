from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from tests.system.deployments.baseline import (
    capture_stack_artifacts,
    create_bundle,
    create_stack,
    record_runtime_plan,
)
from tests.system.deployments.runtime_overrides import (
    BOOTSTRAP_SERVICES,
    prepare_runtime_compose_config,
    start_baseline_relay,
)
from tests.system.harness import (
    FaultControlPortPlan,
    LocalTlsWebSocketRuntime,
    LocalToxiproxyRuntime,
    ProxySpec,
    RuntimeAddressPlan,
    ToxicSpec,
    execute_runtime,
    fetch_runtime_rows,
)


if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from tests.system.harness import ComposeStack, LocalRelayRuntime, SystemArtifactBundle


pytestmark = pytest.mark.system


MONITOR_ARTIFACT_SERVICES = (*BOOTSTRAP_SERVICES, "monitor")
_RELAY_INSERT_SQL = """
    INSERT INTO relay (url, network, stored_at)
    VALUES ($1, 'clearnet', $2)
    ON CONFLICT (url) DO UPDATE
    SET stored_at = LEAST(relay.stored_at, EXCLUDED.stored_at)
"""
_MONITOR_DOCUMENT_ROWS_SQL = """
    SELECT
        rd.relay_url,
        rd.role,
        rd.associated_at,
        d.data
    FROM relay_document AS rd
    JOIN document AS d
      ON d.id = rd.document_id
     AND d.type = rd.role
    ORDER BY rd.relay_url, rd.role, rd.associated_at
"""
_MONITOR_CHECKPOINT_ROWS_SQL = """
    SELECT
        state_key,
        (state_value->>'timestamp')::bigint AS timestamp
    FROM service_state
    WHERE owner = 'monitor'
      AND state_type = 'checkpoint'
    ORDER BY state_key
"""
_BLACKHOLE_TOXIC = ToxicSpec(
    name="blackhole",
    toxic_type="timeout",
    stream="downstream",
    attributes={"timeout": 0},
)


def _metadata_flags(
    *,
    nip11_info: bool,
    nip66_rtt: bool,
) -> dict[str, bool]:
    return {
        "nip11_info": nip11_info,
        "nip66_rtt": nip66_rtt,
        "nip66_ssl": False,
        "nip66_geo": False,
        "nip66_net": False,
        "nip66_dns": False,
        "nip66_http": False,
    }


def _configure_monitor_runtime(
    plan: RuntimeAddressPlan,
    *,
    discovery_interval: float,
    timeout: float,
    cycle_interval: float = 3600.0,
) -> None:
    config_path = plan.runtime_root / "config" / "services" / "monitor.yaml"
    payload = yaml.safe_load(config_path.read_text())
    assert isinstance(payload, dict)

    flags = _metadata_flags(nip11_info=True, nip66_rtt=True)

    payload["interval"] = cycle_interval

    processing = payload.setdefault("processing", {})
    assert isinstance(processing, dict)
    processing["chunk_size"] = 10
    processing["max_relays"] = 10
    processing["allow_insecure"] = True
    processing["compute"] = flags
    processing["store"] = flags
    processing["retries"] = {
        "nip11_info": {"max_attempts": 0},
        "nip66_rtt": {"max_attempts": 0},
    }

    discovery = payload.setdefault("discovery", {})
    assert isinstance(discovery, dict)
    discovery["enabled"] = False
    discovery["interval"] = discovery_interval
    discovery["include"] = flags

    announcement = payload.setdefault("announcement", {})
    assert isinstance(announcement, dict)
    announcement["enabled"] = False
    announcement["include"] = flags

    profile = payload.setdefault("profile", {})
    assert isinstance(profile, dict)
    profile["enabled"] = False

    relay_list = payload.setdefault("relay_list", {})
    assert isinstance(relay_list, dict)
    relay_list["enabled"] = False

    networks = payload.setdefault("networks", {})
    assert isinstance(networks, dict)
    networks["clearnet"] = {"enabled": True, "max_tasks": 2, "timeout": timeout}
    networks["tor"] = {"enabled": False}
    networks["i2p"] = {"enabled": False}
    networks["loki"] = {"enabled": False}

    config_path.write_text(yaml.safe_dump(payload, sort_keys=False))


def _prepare_monitor_run(
    tmp_path: Path,
    run_name: str,
    *,
    discovery_interval: float,
    timeout: float,
    cycle_interval: float = 3600.0,
) -> tuple[SystemArtifactBundle, RuntimeAddressPlan, ComposeStack]:
    bundle = create_bundle(tmp_path, run_name)
    plan = RuntimeAddressPlan.create("bigbrotr", tmp_path / "runtime", run_name)
    prepare_runtime_compose_config(plan)
    _configure_monitor_runtime(
        plan,
        discovery_interval=discovery_interval,
        timeout=timeout,
        cycle_interval=cycle_interval,
    )
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)
    return bundle, plan, stack


def _insert_relay(plan: RuntimeAddressPlan, relay_url: str, *, stored_at: int) -> None:
    execute_runtime(plan, _RELAY_INSERT_SQL, relay_url, stored_at)


def _monitor_documents(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _MONITOR_DOCUMENT_ROWS_SQL)


def _monitor_checkpoints(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _MONITOR_CHECKPOINT_ROWS_SQL)


def _wait_until(
    fetch_snapshot: Callable[[], Any],
    *,
    is_ready: Callable[[Any], bool],
    description: str,
    timeout: float = 60.0,
    poll_interval: float = 0.5,
) -> Any:
    deadline = time.monotonic() + timeout
    last_snapshot = fetch_snapshot()
    while time.monotonic() < deadline:
        last_snapshot = fetch_snapshot()
        if is_ready(last_snapshot):
            return last_snapshot
        time.sleep(poll_interval)
    raise RuntimeError(f"Timed out waiting for {description}: {last_snapshot!r}")


def _monitor_log_count(stack: ComposeStack, text: str) -> int:
    return stack.run("logs", "--no-color", "monitor", check=False).stdout.count(text)


def _canonical_tls_docker_url(runtime: LocalTlsWebSocketRuntime) -> str:
    return f"wss://{runtime.docker_host}:{runtime.port}"


def _decode_document_data(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return decoded
    raise TypeError(
        f"Expected document payload dict or JSON object string, got {type(value).__name__}"
    )


def _capture_monitor_artifacts(
    bundle: SystemArtifactBundle,
    stack: ComposeStack,
    *,
    relay: LocalRelayRuntime,
    toxiproxy: LocalToxiproxyRuntime,
    good_runtime: LocalTlsWebSocketRuntime,
    degraded_runtime: LocalTlsWebSocketRuntime,
    proxy_listing: dict[str, object],
    name: str,
) -> None:
    bundle.capture_container_logs(
        f"{name}-monitor", stack.run("logs", "--no-color", "monitor").stdout
    )
    bundle.capture_container_logs(f"{name}-relay", relay.logs())
    bundle.capture_container_logs(f"{name}-toxiproxy", toxiproxy.logs())
    bundle.write_json_artifact(
        category="relay",
        subdir="relay",
        name=f"{name}-relay-inspect",
        payload={
            "relay": relay.inspect(),
            "toxiproxy": toxiproxy.inspect(),
            "proxy_listing": proxy_listing,
            "good_runtime_sessions": [asdict(session) for session in good_runtime.sessions()],
            "degraded_runtime_sessions": [
                asdict(session) for session in degraded_runtime.sessions()
            ],
        },
    )


@pytest.mark.timeout(900)
def test_monitor_persists_probe_documents_for_healthy_and_degraded_relays(  # noqa: PLR0915
    tmp_path: Path,
) -> None:
    bundle, plan, stack = _prepare_monitor_run(
        tmp_path,
        "monitor-probe-documents",
        discovery_interval=3600.9,
        timeout=1.0,
    )
    relay = None
    toxiproxy = None
    good_runtime = None
    degraded_runtime = None
    good_url = ""
    degraded_url = ""
    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        relay = start_baseline_relay(plan)
        good_runtime = LocalTlsWebSocketRuntime(
            tmp_path / "good-tls-runtime",
            mode="proxy",
            backend_url=relay.ws_url,
            http_backend_url=relay.ws_url.replace("ws://", "http://", 1),
        )
        good_runtime.start()
        good_url = _canonical_tls_docker_url(good_runtime)

        port_plan = FaultControlPortPlan.for_slot(6)
        proxy_port = port_plan.proxy_port(0)
        toxiproxy = LocalToxiproxyRuntime(
            role="mtox",
            runtime_dir=tmp_path / "toxiproxy-runtime",
            network_name=plan.data_network_name,
            port_plan=port_plan,
            exposed_proxy_ports=(proxy_port,),
        )
        toxiproxy.start()
        toxiproxy.wait_until_ready()
        toxiproxy.client.create_proxy(
            ProxySpec(
                name="monitor-upstream",
                upstream_host=relay.container_name,
                upstream_port=8080,
                listen_port=proxy_port,
            )
        )
        degraded_backend_url = toxiproxy.proxy_ws_url(proxy_port)
        degraded_runtime = LocalTlsWebSocketRuntime(
            tmp_path / "degraded-tls-runtime",
            mode="proxy",
            backend_url=degraded_backend_url,
            http_backend_url=degraded_backend_url.replace("ws://", "http://", 1),
        )
        degraded_runtime.start()
        toxiproxy.client.add_toxic("monitor-upstream", _BLACKHOLE_TOXIC)
        degraded_url = _canonical_tls_docker_url(degraded_runtime)

        _insert_relay(plan, good_url, stored_at=1)
        _insert_relay(plan, degraded_url, stored_at=2)

        stack.up("monitor", build=True)
        stack.wait_until_ready(("monitor",), timeout=180.0)

        snapshot = _wait_until(
            lambda: {
                "documents": _monitor_documents(plan),
                "checkpoints": _monitor_checkpoints(plan),
                "good_sessions": good_runtime.sessions(),
                "degraded_sessions": degraded_runtime.sessions(),
            },
            is_ready=lambda current: (
                len(current["documents"]) == 4
                and len(current["checkpoints"]) == 2
                and len(current["good_sessions"]) >= 1
                and len(current["degraded_sessions"]) >= 1
                and {row["state_key"] for row in current["checkpoints"]} == {good_url, degraded_url}
            ),
            description="monitor document persistence",
            timeout=120.0,
        )
        proxy_listing = toxiproxy.client.list_proxies()
        _capture_monitor_artifacts(
            bundle,
            stack,
            relay=relay,
            toxiproxy=toxiproxy,
            good_runtime=good_runtime,
            degraded_runtime=degraded_runtime,
            proxy_listing=proxy_listing,
            name="monitor-probe-documents",
        )
        bundle.capture_db_snapshot("monitor-probe-documents", snapshot)
    finally:
        capture_stack_artifacts(bundle, stack, services=MONITOR_ARTIFACT_SERVICES)
        if degraded_runtime is not None:
            degraded_runtime.stop()
        if good_runtime is not None:
            good_runtime.stop()
        if toxiproxy is not None:
            toxiproxy.stop()
        if relay is not None:
            relay.stop()
        stack.down()

    documents_by_relay: dict[str, dict[str, dict[str, object]]] = {}
    for row in snapshot["documents"]:
        relay_documents = documents_by_relay.setdefault(str(row["relay_url"]), {})
        relay_documents[str(row["role"])] = dict(row)

    assert set(documents_by_relay) == {good_url, degraded_url}
    assert set(documents_by_relay[good_url]) == {"nip11_info", "nip66_rtt"}
    assert set(documents_by_relay[degraded_url]) == {"nip11_info", "nip66_rtt"}

    good_nip11 = _decode_document_data(documents_by_relay[good_url]["nip11_info"]["data"])
    assert good_nip11["logs"]["success"] is True
    assert "nostr-rs-relay" in str(good_nip11["data"]["software"])
    assert 11 in good_nip11["data"]["supported_nips"]

    good_rtt = _decode_document_data(documents_by_relay[good_url]["nip66_rtt"]["data"])
    assert good_rtt["logs"]["open_success"] is True
    assert isinstance(good_rtt["data"]["rtt_open"], int)
    assert good_rtt["data"]["rtt_open"] >= 0

    degraded_nip11 = _decode_document_data(documents_by_relay[degraded_url]["nip11_info"]["data"])
    assert degraded_nip11["logs"]["success"] is False
    assert degraded_nip11["logs"]["reason"] == "HTTP 504"

    degraded_rtt = _decode_document_data(documents_by_relay[degraded_url]["nip66_rtt"]["data"])
    assert degraded_rtt["logs"]["open_success"] is True
    assert degraded_rtt["logs"]["write_reason"] == "TimeoutError"

    checkpoints = {row["state_key"]: row["timestamp"] for row in snapshot["checkpoints"]}
    assert set(checkpoints) == {good_url, degraded_url}
    assert all(isinstance(timestamp, int) and timestamp > 0 for timestamp in checkpoints.values())


@pytest.mark.timeout(900)
def test_monitor_restart_respects_persisted_checkpoints(  # noqa: PLR0915
    tmp_path: Path,
) -> None:
    bundle, plan, stack = _prepare_monitor_run(
        tmp_path,
        "monitor-restart-checkpoints",
        discovery_interval=3600.9,
        timeout=1.0,
    )
    relay = None
    toxiproxy = None
    good_runtime = None
    degraded_runtime = None
    good_url = ""
    degraded_url = ""
    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        relay = start_baseline_relay(plan)
        good_runtime = LocalTlsWebSocketRuntime(
            tmp_path / "good-tls-runtime",
            mode="proxy",
            backend_url=relay.ws_url,
            http_backend_url=relay.ws_url.replace("ws://", "http://", 1),
        )
        good_runtime.start()
        good_url = _canonical_tls_docker_url(good_runtime)

        port_plan = FaultControlPortPlan.for_slot(7)
        proxy_port = port_plan.proxy_port(0)
        toxiproxy = LocalToxiproxyRuntime(
            role="mtox-restart",
            runtime_dir=tmp_path / "toxiproxy-runtime",
            network_name=plan.data_network_name,
            port_plan=port_plan,
            exposed_proxy_ports=(proxy_port,),
        )
        toxiproxy.start()
        toxiproxy.wait_until_ready()
        toxiproxy.client.create_proxy(
            ProxySpec(
                name="monitor-upstream",
                upstream_host=relay.container_name,
                upstream_port=8080,
                listen_port=proxy_port,
            )
        )
        degraded_backend_url = toxiproxy.proxy_ws_url(proxy_port)
        degraded_runtime = LocalTlsWebSocketRuntime(
            tmp_path / "degraded-tls-runtime",
            mode="proxy",
            backend_url=degraded_backend_url,
            http_backend_url=degraded_backend_url.replace("ws://", "http://", 1),
        )
        degraded_runtime.start()
        toxiproxy.client.add_toxic("monitor-upstream", _BLACKHOLE_TOXIC)
        degraded_url = _canonical_tls_docker_url(degraded_runtime)

        _insert_relay(plan, good_url, stored_at=1)
        _insert_relay(plan, degraded_url, stored_at=2)

        stack.up("monitor", build=True)
        stack.wait_until_ready(("monitor",), timeout=180.0)

        first_snapshot = _wait_until(
            lambda: {
                "documents": _monitor_documents(plan),
                "checkpoints": _monitor_checkpoints(plan),
                "log_count": _monitor_log_count(stack, "relays_available"),
                "good_sessions": good_runtime.sessions(),
                "degraded_sessions": degraded_runtime.sessions(),
            },
            is_ready=lambda current: (
                len(current["documents"]) == 4
                and len(current["checkpoints"]) == 2
                and current["log_count"] >= 1
                and len(current["good_sessions"]) >= 1
                and len(current["degraded_sessions"]) >= 1
            ),
            description="initial monitor checkpoint persistence",
            timeout=120.0,
        )

        first_checkpoints = {
            row["state_key"]: row["timestamp"] for row in first_snapshot["checkpoints"]
        }
        first_document_rows = tuple(
            (row["relay_url"], row["role"], row["associated_at"])
            for row in first_snapshot["documents"]
        )
        first_good_sessions = len(first_snapshot["good_sessions"])
        first_degraded_sessions = len(first_snapshot["degraded_sessions"])

        stack.run("restart", "monitor")
        stack.wait_until_ready(("monitor",), timeout=180.0)

        second_snapshot = _wait_until(
            lambda: {
                "documents": _monitor_documents(plan),
                "checkpoints": _monitor_checkpoints(plan),
                "log_count": _monitor_log_count(stack, "relays_available"),
                "good_sessions": good_runtime.sessions(),
                "degraded_sessions": degraded_runtime.sessions(),
            },
            is_ready=lambda current: current["log_count"] >= 2,
            description="monitor restart cycle completion",
            timeout=120.0,
        )

        proxy_listing = toxiproxy.client.list_proxies()
        _capture_monitor_artifacts(
            bundle,
            stack,
            relay=relay,
            toxiproxy=toxiproxy,
            good_runtime=good_runtime,
            degraded_runtime=degraded_runtime,
            proxy_listing=proxy_listing,
            name="monitor-restart-checkpoints",
        )
        bundle.capture_db_snapshot("monitor-restart-checkpoints-first", first_snapshot)
        bundle.capture_db_snapshot("monitor-restart-checkpoints-second", second_snapshot)
    finally:
        capture_stack_artifacts(bundle, stack, services=MONITOR_ARTIFACT_SERVICES)
        if degraded_runtime is not None:
            degraded_runtime.stop()
        if good_runtime is not None:
            good_runtime.stop()
        if toxiproxy is not None:
            toxiproxy.stop()
        if relay is not None:
            relay.stop()
        stack.down()

    second_checkpoints = {
        row["state_key"]: row["timestamp"] for row in second_snapshot["checkpoints"]
    }
    second_document_rows = tuple(
        (row["relay_url"], row["role"], row["associated_at"])
        for row in second_snapshot["documents"]
    )

    assert first_checkpoints == second_checkpoints
    assert set(second_checkpoints) == {good_url, degraded_url}
    assert first_document_rows == second_document_rows
    assert second_snapshot["log_count"] >= 2
    assert len(second_snapshot["good_sessions"]) == first_good_sessions
    assert len(second_snapshot["degraded_sessions"]) == first_degraded_sessions
