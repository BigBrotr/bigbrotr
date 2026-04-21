from dataclasses import asdict
from pathlib import Path

import pytest

from tests.system.harness import (
    LocalRelayRuntime,
    RelayEoseFrame,
    RelayEventFrame,
    RelaySession,
    SystemArtifactBundle,
    build_text_note_event,
    publish_event,
    query_events,
)


pytestmark = pytest.mark.system


def _create_relay_bundle(tmp_path: Path, run_name: str) -> SystemArtifactBundle:
    return SystemArtifactBundle.create(tmp_path / "artifacts", run_name)


async def test_nostr_rs_relay_baseline_contract(tmp_path: Path) -> None:
    bundle = _create_relay_bundle(tmp_path, "nostr-rs-relay-baseline")
    runtime = LocalRelayRuntime(role="baseline", runtime_dir=tmp_path / "relay-runtime")

    with runtime:
        await runtime.wait_until_ready()

        signed = build_text_note_event("system baseline relay contract")
        ok = await publish_event(runtime.ws_url, signed.payload)
        queried_events = await query_events(
            runtime.ws_url,
            filters={"ids": [signed.event_id]},
            subscription_id="baseline-query",
        )

        logs = runtime.logs()
        inspect_payload = runtime.inspect()
        data_files = [path.name for path in runtime.data_files()]

    bundle.capture_container_logs("nostr-rs-relay-baseline", logs)
    bundle.write_json_artifact(
        category="relay",
        subdir="relay",
        name="baseline-inspect",
        payload=inspect_payload,
    )
    bundle.capture_relay_events(
        "baseline-query",
        {
            "publish": asdict(ok),
            "events": [asdict(event) for event in queried_events],
        },
    )
    bundle.write_json_artifact(
        category="relay",
        subdir="relay",
        name="baseline-data-files",
        payload=data_files,
    )

    assert "listening on: 0.0.0.0:8080" in logs
    assert ok.accepted is True
    assert ok.event_id == signed.event_id
    assert len(queried_events) == 1
    assert queried_events[0].event["id"] == signed.event_id
    assert queried_events[0].event["content"] == "system baseline relay contract"
    assert queried_events[0].event["pubkey"] == signed.pubkey
    assert "nostr.db" in data_files


async def test_nostr_rs_relay_live_subscribe_contract(tmp_path: Path) -> None:
    bundle = _create_relay_bundle(tmp_path, "nostr-rs-relay-live-subscribe")
    runtime = LocalRelayRuntime(role="baseline-live", runtime_dir=tmp_path / "relay-runtime")

    with runtime:
        await runtime.wait_until_ready()
        signed = build_text_note_event("system live subscribe relay contract")

        async with await RelaySession.connect(runtime.ws_url) as subscriber:
            await subscriber.request("live-sub", {"ids": [signed.event_id]})
            first_frame = await subscriber.receive_frame()
            publish_result = await publish_event(runtime.ws_url, signed.payload)
            second_frame = await subscriber.receive_frame()
            logs = runtime.logs()

    bundle.capture_container_logs("nostr-rs-relay-live-subscribe", logs)
    bundle.capture_relay_events(
        "live-subscribe",
        {
            "first_frame": asdict(first_frame),
            "publish_result": asdict(publish_result),
            "second_frame": asdict(second_frame),
        },
    )

    assert isinstance(first_frame, RelayEoseFrame)
    assert first_frame.subscription_id == "live-sub"
    assert publish_result.accepted is True
    assert publish_result.event_id == signed.event_id
    assert isinstance(second_frame, RelayEventFrame)
    assert second_frame.subscription_id == "live-sub"
    assert second_frame.event["id"] == signed.event_id
    assert second_frame.event["content"] == "system live subscribe relay contract"
