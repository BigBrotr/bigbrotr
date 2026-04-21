from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

import pytest

from tests.system.harness import (
    LocalRelayRuntime,
    LocalRnostrRuntime,
    RelayEoseFrame,
    RelayEventFrame,
    RelaySession,
    SystemArtifactBundle,
    build_text_note_event,
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


@pytest.mark.parametrize(
    ("label", "runtime_factory", "expected_log_fragment"),
    [
        (
            "nostr-rs-relay",
            lambda runtime_dir: LocalRelayRuntime(role="matrix-baseline", runtime_dir=runtime_dir),
            "listening on: 0.0.0.0:8080",
        ),
        (
            "rnostr",
            lambda runtime_dir: LocalRnostrRuntime(
                role="matrix-secondary", runtime_dir=runtime_dir
            ),
            "Start http server 0.0.0.0:8080",
        ),
    ],
    ids=("nostr-rs-relay", "rnostr"),
)
async def test_secondary_relay_matrix_common_contract(
    tmp_path: Path,
    label: str,
    runtime_factory: RelayRuntimeFactory,
    expected_log_fragment: str,
) -> None:
    bundle = _create_relay_bundle(tmp_path, f"{label}-relay-matrix")
    runtime = runtime_factory(tmp_path / f"{label}-runtime")
    signed = build_text_note_event(f"{label} relay matrix contract")

    with runtime:
        await runtime.wait_until_ready()

        async with await RelaySession.connect(runtime.ws_url) as subscriber:
            await subscriber.request(f"{label}-live", {"ids": [signed.event_id]})
            first_frame = await subscriber.receive_frame()
            first_publish = await publish_event(runtime.ws_url, signed.payload)
            live_frame = await subscriber.receive_frame()
            duplicate_publish = await publish_event(runtime.ws_url, signed.payload)

            with pytest.raises(TimeoutError):
                await subscriber.receive_frame(timeout=0.5)

        queried_events = await query_events(
            runtime.ws_url,
            filters={"ids": [signed.event_id]},
            subscription_id=f"{label}-query",
        )
        logs = runtime.logs()
        inspect_payload = runtime.inspect()
        data_files = _collect_data_files(runtime.data_dir)

    bundle.capture_container_logs(f"{label}-relay-matrix", logs)
    bundle.write_json_artifact(
        category="relay",
        subdir="relay",
        name=f"{label}-matrix-inspect",
        payload=inspect_payload,
    )
    bundle.capture_relay_events(
        f"{label}-relay-matrix",
        {
            "first_frame": asdict(first_frame),
            "first_publish": asdict(first_publish),
            "live_frame": asdict(live_frame),
            "duplicate_publish": asdict(duplicate_publish),
            "queried_events": [asdict(event) for event in queried_events],
            "data_files": data_files,
        },
    )

    assert isinstance(first_frame, RelayEoseFrame)
    assert first_publish.accepted is True
    assert first_publish.event_id == signed.event_id
    assert isinstance(live_frame, RelayEventFrame)
    assert live_frame.subscription_id == f"{label}-live"
    assert live_frame.event["id"] == signed.event_id
    assert live_frame.event["content"] == f"{label} relay matrix contract"
    assert live_frame.event["pubkey"] == signed.pubkey
    assert duplicate_publish.accepted is True
    assert duplicate_publish.message.startswith("duplicate:")
    assert len(queried_events) == 1
    assert queried_events[0].event["id"] == signed.event_id
    assert queried_events[0].event["content"] == f"{label} relay matrix contract"
    assert queried_events[0].event["pubkey"] == signed.pubkey
    assert expected_log_fragment in logs
    assert data_files
