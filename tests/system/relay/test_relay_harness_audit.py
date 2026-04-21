import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

import aiohttp
import pytest
from nostr_sdk import Keys

from tests.system.harness import (
    DockerNetworkRuntime,
    FaultControlPortPlan,
    LocalRelayRuntime,
    LocalRnostrRuntime,
    LocalToxiproxyRuntime,
    ProxySpec,
    RelayEoseFrame,
    RelayEventFrame,
    RelaySession,
    SystemArtifactBundle,
    build_text_note_event,
    docker_container_exists,
    docker_network_exists,
    publish_event,
    query_events,
)


pytestmark = pytest.mark.system


RelayRuntimeFactory = Callable[[Path], LocalRelayRuntime | LocalRnostrRuntime]


def _create_relay_bundle(tmp_path: Path, run_name: str) -> SystemArtifactBundle:
    return SystemArtifactBundle.create(tmp_path / "artifacts", run_name)


def _collect_data_files(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


def _assert_manifest_files_exist(bundle: SystemArtifactBundle) -> None:
    payload = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    records = payload["records"]
    assert records
    for record in records:
        assert (bundle.root / record["relative_path"]).exists()


async def _capture_role_audit(
    *,
    bundle: SystemArtifactBundle,
    runtime: LocalRelayRuntime,
    event_content: str,
) -> None:
    event = build_text_note_event(event_content)

    assert docker_container_exists(runtime.container_name) is False
    with runtime:
        await runtime.wait_until_ready()

        async with await RelaySession.connect(runtime.ws_url) as subscriber:
            await subscriber.request("capture-audit", {"ids": [event.event_id]})
            first_frame = await subscriber.receive_frame()
            first_publish = await publish_event(runtime.ws_url, event.payload)
            live_frame = await subscriber.receive_frame()
            duplicate_publish = await publish_event(runtime.ws_url, event.payload)

            with pytest.raises(TimeoutError):
                await subscriber.receive_frame(timeout=0.5)

        logs = runtime.logs()
        inspect_payload = runtime.inspect()

    assert docker_container_exists(runtime.container_name) is False

    bundle.capture_container_logs("audit-capture", logs)
    bundle.write_json_artifact(
        category="relay",
        subdir="relay",
        name="capture-audit-inspect",
        payload=inspect_payload,
    )
    bundle.capture_relay_events(
        "capture-audit",
        {
            "first_frame": asdict(first_frame),
            "first_publish": asdict(first_publish),
            "live_frame": asdict(live_frame),
            "duplicate_publish": asdict(duplicate_publish),
        },
    )

    assert isinstance(first_frame, RelayEoseFrame)
    assert isinstance(live_frame, RelayEventFrame)
    assert first_publish.accepted is True
    assert duplicate_publish.accepted is True
    assert duplicate_publish.message.startswith("duplicate:")


async def _fault_role_audit(*, bundle: SystemArtifactBundle, tmp_path: Path) -> None:
    port_plan = FaultControlPortPlan.for_slot(2)
    proxy_name = "relay-audit"
    proxy_port = port_plan.proxy_port(0)
    network = DockerNetworkRuntime(role="relay-audit", runtime_dir=tmp_path / "fault-net")
    relay = LocalRelayRuntime(
        role="audit-fault-upstream",
        runtime_dir=tmp_path / "fault-relay-runtime",
        network_name=network.name,
        network_aliases=("relay-upstream",),
    )
    toxiproxy = LocalToxiproxyRuntime(
        role="relay-audit",
        runtime_dir=tmp_path / "fault-runtime",
        network_name=network.name,
        port_plan=port_plan,
        exposed_proxy_ports=(proxy_port,),
    )
    proxied_url = toxiproxy.proxy_ws_url(proxy_port)

    assert docker_network_exists(network.name) is False
    assert docker_container_exists(relay.container_name) is False
    assert docker_container_exists(toxiproxy.container_name) is False
    with network, relay, toxiproxy:
        await relay.wait_until_ready()
        toxiproxy.wait_until_ready()
        proxy_payload = toxiproxy.client.create_proxy(
            ProxySpec(
                name=proxy_name,
                upstream_host="relay-upstream",
                upstream_port=8080,
                listen_port=proxy_port,
            )
        )

        initial_event = build_text_note_event("relay fault audit")
        initial_publish = await publish_event(proxied_url, initial_event.payload)
        initial_rows = await query_events(
            proxied_url,
            filters={"ids": [initial_event.event_id]},
            subscription_id="fault-audit-initial",
        )

        toxiproxy.client.set_proxy_enabled(proxy_name, enabled=False)
        try:
            with pytest.raises((aiohttp.ClientError, OSError, TimeoutError)):
                async with await RelaySession.connect(proxied_url, connect_timeout=0.5):
                    pass
        finally:
            toxiproxy.client.set_proxy_enabled(proxy_name, enabled=True)

        recovered_event = build_text_note_event("relay fault audit recovered")
        recovered_publish = await publish_event(proxied_url, recovered_event.payload)
        recovered_rows = await query_events(
            proxied_url,
            filters={"ids": [recovered_event.event_id]},
            subscription_id="fault-audit-recovered",
        )
        relay_logs = relay.logs()
        toxiproxy_logs = toxiproxy.logs()
        relay_inspect = relay.inspect()
        toxiproxy_inspect = toxiproxy.inspect()

    assert docker_container_exists(relay.container_name) is False
    assert docker_container_exists(toxiproxy.container_name) is False
    assert docker_network_exists(network.name) is False

    bundle.capture_container_logs("audit-fault-relay", relay_logs)
    bundle.capture_container_logs("audit-fault-toxiproxy", toxiproxy_logs)
    bundle.write_json_artifact(
        category="relay",
        subdir="relay",
        name="fault-audit-inspect",
        payload={
            "relay": relay_inspect,
            "toxiproxy": toxiproxy_inspect,
            "proxy": proxy_payload,
            "data_files": _collect_data_files(relay.data_dir),
        },
    )
    bundle.capture_relay_events(
        "fault-audit",
        {
            "initial_publish": asdict(initial_publish),
            "initial_rows": [asdict(row) for row in initial_rows],
            "recovered_publish": asdict(recovered_publish),
            "recovered_rows": [asdict(row) for row in recovered_rows],
        },
    )

    assert initial_publish.accepted is True
    assert len(initial_rows) == 1
    assert initial_rows[0].event["content"] == "relay fault audit"
    assert recovered_publish.accepted is True
    assert len(recovered_rows) == 1
    assert recovered_rows[0].event["content"] == "relay fault audit recovered"


@pytest.mark.parametrize(
    ("label", "runtime_factory", "expected_log_fragment"),
    [
        (
            "nostr-rs-relay",
            lambda runtime_dir: LocalRelayRuntime(role="audit-baseline", runtime_dir=runtime_dir),
            "listening on: 0.0.0.0:8080",
        ),
        (
            "rnostr",
            lambda runtime_dir: LocalRnostrRuntime(role="audit-secondary", runtime_dir=runtime_dir),
            "Start http server 0.0.0.0:8080",
        ),
    ],
    ids=("nostr-rs-relay", "rnostr"),
)
async def test_relay_publish_read_cycles_stay_deterministic(
    tmp_path: Path,
    label: str,
    runtime_factory: RelayRuntimeFactory,
    expected_log_fragment: str,
) -> None:
    bundle = _create_relay_bundle(tmp_path, f"{label}-relay-harness-audit")
    keys = Keys.generate()
    observed_pubkey: str | None = None

    for cycle in range(2):
        runtime = runtime_factory(tmp_path / f"{label}-runtime-{cycle}")
        event = build_text_note_event(f"{label} deterministic cycle {cycle}", keys=keys)

        assert docker_container_exists(runtime.container_name) is False
        with runtime:
            await runtime.wait_until_ready()
            publish_result = await publish_event(runtime.ws_url, event.payload)
            queried_events = await query_events(
                runtime.ws_url,
                filters={"ids": [event.event_id]},
                subscription_id=f"{label}-cycle-{cycle}",
            )
            logs = runtime.logs()
            inspect_payload = runtime.inspect()
            data_files = _collect_data_files(runtime.data_dir)

        assert docker_container_exists(runtime.container_name) is False

        bundle.capture_container_logs(f"{label}-cycle-{cycle}", logs)
        bundle.write_json_artifact(
            category="relay",
            subdir="relay",
            name=f"{label}-cycle-{cycle}-inspect",
            payload=inspect_payload,
        )
        bundle.capture_relay_events(
            f"{label}-cycle-{cycle}",
            {
                "publish_result": asdict(publish_result),
                "queried_events": [asdict(row) for row in queried_events],
                "data_files": data_files,
            },
        )

        if observed_pubkey is None:
            observed_pubkey = event.pubkey

        assert publish_result.accepted is True
        assert publish_result.event_id == event.event_id
        assert len(queried_events) == 1
        assert queried_events[0].event["id"] == event.event_id
        assert queried_events[0].event["content"] == f"{label} deterministic cycle {cycle}"
        assert queried_events[0].event["pubkey"] == observed_pubkey
        assert expected_log_fragment in logs
        assert data_files

    _assert_manifest_files_exist(bundle)


async def test_relay_role_artifacts_and_teardown_are_auditable(tmp_path: Path) -> None:
    bundle = _create_relay_bundle(tmp_path, "relay-role-audit")
    capture_runtime = LocalRelayRuntime(
        role="audit-capture", runtime_dir=tmp_path / "capture-runtime"
    )

    await _capture_role_audit(
        bundle=bundle,
        runtime=capture_runtime,
        event_content="relay capture audit",
    )
    await _fault_role_audit(bundle=bundle, tmp_path=tmp_path)

    _assert_manifest_files_exist(bundle)
