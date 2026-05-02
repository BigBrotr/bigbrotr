from dataclasses import asdict
from pathlib import Path

import aiohttp
import pytest

from tests.system.harness import (
    DockerNetworkRuntime,
    FaultControlPortPlan,
    LocalRelayRuntime,
    LocalToxiproxyRuntime,
    ProxySpec,
    RelaySession,
    SystemArtifactBundle,
    ToxicSpec,
    build_signed_event,
    publish_event,
    query_events,
)


pytestmark = pytest.mark.system


def _create_relay_bundle(tmp_path: Path, run_name: str) -> SystemArtifactBundle:
    return SystemArtifactBundle.create(tmp_path / "artifacts", run_name)


def _build_fault_toxics() -> tuple[ToxicSpec, ToxicSpec, ToxicSpec]:
    return (
        ToxicSpec(
            name="latency",
            toxic_type="latency",
            stream="downstream",
            attributes={"latency": 900, "jitter": 0},
        ),
        ToxicSpec(
            name="blackhole",
            toxic_type="timeout",
            stream="downstream",
            attributes={"timeout": 0},
        ),
        ToxicSpec(
            name="reset",
            toxic_type="reset_peer",
            stream="downstream",
            attributes={"timeout": 0},
        ),
    )


async def _assert_latency_fault(
    proxied_url: str, proxy_name: str, toxic: ToxicSpec, toxiproxy: LocalToxiproxyRuntime
) -> None:
    toxiproxy.client.add_toxic(proxy_name, toxic)
    try:
        with pytest.raises(TimeoutError):
            async with await RelaySession.connect(proxied_url) as session:
                await session.request("latency", {"ids": ["0" * 64]})
                await session.receive_frame(timeout=0.2)
    finally:
        toxiproxy.client.remove_toxic(proxy_name, toxic.name)


async def _assert_blackhole_fault(
    proxied_url: str, proxy_name: str, toxic: ToxicSpec, toxiproxy: LocalToxiproxyRuntime
) -> None:
    toxiproxy.client.add_toxic(proxy_name, toxic)
    try:
        with pytest.raises(TimeoutError):
            async with await RelaySession.connect(proxied_url) as session:
                await session.request("blackhole", {"ids": ["0" * 64]})
                await session.receive_frame(timeout=0.3)
    finally:
        toxiproxy.client.remove_toxic(proxy_name, toxic.name)


async def _assert_reset_fault(
    proxied_url: str, proxy_name: str, toxic: ToxicSpec, toxiproxy: LocalToxiproxyRuntime
) -> None:
    toxiproxy.client.add_toxic(proxy_name, toxic)
    try:
        with pytest.raises((aiohttp.ClientError, OSError, RuntimeError)):
            async with await RelaySession.connect(proxied_url) as session:
                await session.request("reset", {"ids": ["0" * 64]})
                await session.receive_frame(timeout=1.0)
    finally:
        toxiproxy.client.remove_toxic(proxy_name, toxic.name)


async def _assert_disconnect_and_recovery(
    proxied_url: str, proxy_name: str, toxiproxy: LocalToxiproxyRuntime
) -> tuple[object, tuple[object, ...]]:
    toxiproxy.client.set_proxy_enabled(proxy_name, enabled=False)
    try:
        with pytest.raises((aiohttp.ClientError, OSError, TimeoutError)):
            async with await RelaySession.connect(proxied_url, connect_timeout=0.5):
                pass
    finally:
        toxiproxy.client.set_proxy_enabled(proxy_name, enabled=True)

    recovered_event = build_signed_event(kind=1, content="fault path recovered")
    publish_result = await publish_event(proxied_url, recovered_event.payload)
    recovered_rows = await query_events(
        proxied_url,
        filters={"ids": [recovered_event.event_id]},
        subscription_id="fault-recovery",
    )
    return publish_result, recovered_rows


async def test_fault_injected_relay_path_contract(tmp_path: Path) -> None:
    bundle = _create_relay_bundle(tmp_path, "nostr-rs-relay-fault-path")
    port_plan = FaultControlPortPlan.for_slot(0)
    proxy_name = "relay-main"
    proxy_port = port_plan.proxy_port(0)
    network = DockerNetworkRuntime(role="relay-fault-path", runtime_dir=tmp_path / "fault-net")
    relay = LocalRelayRuntime(
        role="fault-upstream",
        runtime_dir=tmp_path / "relay-runtime",
        network_name=network.name,
        network_aliases=("relay-upstream",),
    )
    toxiproxy = LocalToxiproxyRuntime(
        role="relay-fault-path",
        runtime_dir=tmp_path / "fault-runtime",
        network_name=network.name,
        port_plan=port_plan,
        exposed_proxy_ports=(proxy_port,),
    )
    proxied_url = toxiproxy.proxy_ws_url(proxy_port)
    latency_toxic, blackhole_toxic, reset_toxic = _build_fault_toxics()

    with network, relay, toxiproxy:
        await relay.wait_until_ready()
        toxiproxy.wait_until_ready()
        created_proxy = toxiproxy.client.create_proxy(
            ProxySpec(
                name=proxy_name,
                upstream_host="relay-upstream",
                upstream_port=8080,
                listen_port=proxy_port,
            )
        )
        await query_events(
            proxied_url,
            filters={"ids": ["0" * 64]},
            subscription_id="proxied-ready",
        )

        await _assert_latency_fault(proxied_url, proxy_name, latency_toxic, toxiproxy)
        await _assert_blackhole_fault(proxied_url, proxy_name, blackhole_toxic, toxiproxy)
        await _assert_reset_fault(proxied_url, proxy_name, reset_toxic, toxiproxy)
        publish_result, recovered_rows = await _assert_disconnect_and_recovery(
            proxied_url,
            proxy_name,
            toxiproxy,
        )
        relay_logs = relay.logs()
        toxiproxy_logs = toxiproxy.logs()
        relay_inspect = relay.inspect()
        toxiproxy_inspect = toxiproxy.inspect()
        proxy_listing = toxiproxy.client.list_proxies()

    bundle.capture_container_logs("fault-path-relay", relay_logs)
    bundle.capture_container_logs("fault-path-toxiproxy", toxiproxy_logs)
    bundle.write_json_artifact(
        category="relay",
        subdir="relay",
        name="fault-path-inspect",
        payload={
            "relay": relay_inspect,
            "toxiproxy": toxiproxy_inspect,
            "proxy": created_proxy,
            "listing": proxy_listing,
        },
    )
    bundle.capture_relay_events(
        "fault-path-recovery",
        {
            "publish_result": asdict(publish_result),
            "recovered_rows": [asdict(row) for row in recovered_rows],
        },
    )

    assert created_proxy["name"] == proxy_name
    assert publish_result.accepted is True
    assert len(recovered_rows) == 1
    assert recovered_rows[0].event["content"] == "fault path recovered"
    assert proxy_name in proxy_listing
    assert "relay-upstream:8080" in proxy_listing[proxy_name]["upstream"]
