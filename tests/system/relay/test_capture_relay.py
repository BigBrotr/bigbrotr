from dataclasses import asdict
from pathlib import Path

import pytest
from nostr_sdk import Keys

from tests.system.harness import (
    LocalRelayRuntime,
    RelayEoseFrame,
    RelaySession,
    SystemArtifactBundle,
    build_signed_event,
    publish_event,
)


pytestmark = pytest.mark.system


def _create_relay_bundle(tmp_path: Path, run_name: str) -> SystemArtifactBundle:
    return SystemArtifactBundle.create(tmp_path / "artifacts", run_name)


async def test_nostr_rs_relay_capture_contract(tmp_path: Path) -> None:
    bundle = _create_relay_bundle(tmp_path, "nostr-rs-relay-capture")
    runtime = LocalRelayRuntime(role="capture", runtime_dir=tmp_path / "relay-runtime")
    keys = Keys.generate()
    first_event = build_signed_event(
        kind=30382,
        content="assertor-like capture payload",
        tags=[["d", "provider"], ["t", "assertor"]],
        keys=keys,
    )
    second_event = build_signed_event(
        kind=31990,
        content="dvm-like capture payload",
        tags=[["d", "job-1"], ["k", "5050"]],
        keys=keys,
    )

    with runtime:
        await runtime.wait_until_ready()

        async with await RelaySession.connect(runtime.ws_url) as subscriber:
            await subscriber.request("capture-sub", {"authors": [first_event.pubkey]})
            first_frame = await subscriber.receive_frame()
            first_publish = await publish_event(runtime.ws_url, first_event.payload)
            second_publish = await publish_event(runtime.ws_url, second_event.payload)
            duplicate_publish = await publish_event(runtime.ws_url, first_event.payload)
            captured_events = await subscriber.collect_event_frames(expected_count=2)
            logs = runtime.logs()

            with pytest.raises(TimeoutError):
                await subscriber.receive_frame(timeout=0.5)

    bundle.capture_container_logs("nostr-rs-relay-capture", logs)
    bundle.capture_relay_events(
        "capture-audit",
        {
            "first_frame": asdict(first_frame),
            "first_publish": asdict(first_publish),
            "second_publish": asdict(second_publish),
            "duplicate_publish": asdict(duplicate_publish),
            "captured_events": [asdict(frame) for frame in captured_events],
        },
    )

    assert isinstance(first_frame, RelayEoseFrame)
    assert first_frame.subscription_id == "capture-sub"
    assert first_publish.accepted is True
    assert second_publish.accepted is True
    assert duplicate_publish.accepted is True
    assert duplicate_publish.message.startswith("duplicate:")
    assert [frame.event["id"] for frame in captured_events] == [
        first_event.event_id,
        second_event.event_id,
    ]
    assert [frame.event["kind"] for frame in captured_events] == [30382, 31990]
    assert [frame.event["content"] for frame in captured_events] == [
        "assertor-like capture payload",
        "dvm-like capture payload",
    ]
    assert [frame.event["tags"] for frame in captured_events] == [
        [["d", "provider"], ["t", "assertor"]],
        [["d", "job-1"], ["k", "5050"]],
    ]
    assert all(frame.event["pubkey"] == first_event.pubkey for frame in captured_events)
