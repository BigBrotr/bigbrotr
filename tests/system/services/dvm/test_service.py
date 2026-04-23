from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

import pytest
import yaml
from nostr_sdk import Keys

from bigbrotr.core.brotr import Brotr
from tests.integration.harness.builders import build_event_observation, build_relay
from tests.system.deployments.baseline import (
    capture_stack_artifacts,
    create_bundle,
    create_stack,
    record_runtime_plan,
)
from tests.system.deployments.runtime_overrides import (
    BOOTSTRAP_SERVICES,
    configure_runtime_relay_targets,
    prepare_runtime_compose_config,
    start_baseline_relay,
)
from tests.system.harness import (
    RuntimeAddressPlan,
    build_signed_event,
    fetch_runtime_rows,
    publish_event,
    query_events,
)
from tests.system.harness.compose import build_test_env_values


if TYPE_CHECKING:
    from pathlib import Path

    from tests.system.harness import (
        ComposeStack,
        LocalRelayRuntime,
        RelayEventFrame,
        SystemArtifactBundle,
    )


pytestmark = pytest.mark.system


DVM_ARTIFACT_SERVICES = (*BOOTSTRAP_SERVICES, "dvm")
_DVM_CURSOR_ROWS_SQL = """
    SELECT
        state_key,
        (state_value->>'timestamp')::bigint AS timestamp,
        state_value->>'id' AS cursor_id
    FROM service_state
    WHERE owner = 'dvm'
      AND state_type = 'cursor'
    ORDER BY state_key
"""
_RELAY_ROWS_SQL = """
    SELECT url, network, stored_at
    FROM relay
    ORDER BY url
"""
_EVENT_ROWS_SQL = """
    SELECT
        encode(id, 'hex') AS id,
        encode(pubkey, 'hex') AS pubkey,
        created_at,
        kind,
        tags,
        tagvalues,
        content,
        encode(sig, 'hex') AS sig
    FROM event
    ORDER BY encode(id, 'hex')
"""
_RELAY_URL = "wss://dvm-relay.example.com"
_EVENT_ID = "20" * 32
_EVENT_PUBKEY = "33" * 32
_EVENT_CONTENT = "system-dvm-event"
_REQUEST_KIND = 5050
_RESULT_KIND = 6050
_ERROR_KIND = 7000
_SEED_RETRY_ATTEMPTS = 5
_SEED_RETRY_DELAY_SECONDS = 1.0
_REQUESTER_KEYS = Keys.parse(
    "71a1f9f06318b8074f8f3d7e7f00d7e0e0ca6abbb23772e0f5a4ed70854b71d7"  # pragma: allowlist secret
)


def _runtime_brotr(plan: RuntimeAddressPlan, *, role: str = "admin") -> Brotr:
    env_values = build_test_env_values(plan.profile, plan.project_name)
    users = {
        "admin": ("admin", env_values["DB_ADMIN_PASSWORD"]),
        "writer": ("writer", env_values["DB_WRITER_PASSWORD"]),
    }
    user, password = users[role]
    return Brotr.from_dict(
        {
            "pool": {
                "database": {
                    "host": "127.0.0.1",
                    "port": plan.ports.db,
                    "database": plan.profile,
                    "user": user,
                    "password": password,
                }
            }
        }
    )


async def _async_seed_dvm_contract(plan: RuntimeAddressPlan) -> None:
    brotr = _runtime_brotr(plan)
    async with brotr:
        await brotr.insert_relay([build_relay(_RELAY_URL, stored_at=1_700_000_000)])
        await brotr.insert_event_observation(
            [
                build_event_observation(
                    _EVENT_ID,
                    _RELAY_URL,
                    pubkey=_EVENT_PUBKEY,
                    created_at=1_700_000_100,
                    content=_EVENT_CONTENT,
                )
            ],
            cascade=True,
        )


def _seed_dvm_contract(plan: RuntimeAddressPlan) -> None:
    last_error: ConnectionError | OSError | None = None
    for attempt in range(_SEED_RETRY_ATTEMPTS):
        try:
            asyncio.run(_async_seed_dvm_contract(plan))
            return
        except (ConnectionError, OSError) as exc:
            last_error = exc
            if attempt + 1 >= _SEED_RETRY_ATTEMPTS:
                break
            time.sleep(_SEED_RETRY_DELAY_SECONDS)

    assert last_error is not None
    raise last_error


def _configure_dvm_runtime(plan: RuntimeAddressPlan, *, interval: float) -> None:
    config_path = plan.runtime_root / "config" / "services" / "dvm.yaml"
    payload = yaml.safe_load(config_path.read_text())
    assert isinstance(payload, dict)

    payload["interval"] = interval
    payload["fetch_timeout"] = 5.0

    config_path.write_text(yaml.safe_dump(payload, sort_keys=False))


def _prepare_dvm_run(
    tmp_path: Path,
    run_name: str,
    *,
    profile: str,
    slot: int,
    interval: float = 60.0,
) -> tuple[SystemArtifactBundle, RuntimeAddressPlan, ComposeStack]:
    bundle = create_bundle(tmp_path, run_name)
    plan = RuntimeAddressPlan.create(profile, tmp_path / "runtime", run_name, slot=slot)
    prepare_runtime_compose_config(plan)
    _configure_dvm_runtime(plan, interval=interval)
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)
    return bundle, plan, stack


def _dvm_logs(stack: ComposeStack) -> str:
    return stack.run("logs", "--no-color", "dvm", check=False).stdout


def _dvm_cursor_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _DVM_CURSOR_ROWS_SQL)


def _relay_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _RELAY_ROWS_SQL)


def _event_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _EVENT_ROWS_SQL)


def _expected_dvm_pubkey(plan: RuntimeAddressPlan) -> str:
    private_key = build_test_env_values(plan.profile, plan.project_name)["NOSTR_PRIVATE_KEY_DVM"]
    return Keys.parse(private_key).public_key().to_hex()


def _announcement_events(ws_url: str, *, author: str) -> tuple[RelayEventFrame, ...]:
    return asyncio.run(
        query_events(
            ws_url,
            filters={"kinds": [31990], "authors": [author]},
            subscription_id="dvm-announcement-capture",
        )
    )


def _reply_events(
    ws_url: str,
    *,
    author: str,
    request_event_id: str,
    kind: int,
) -> tuple[RelayEventFrame, ...]:
    return asyncio.run(
        query_events(
            ws_url,
            filters={"kinds": [kind], "authors": [author], "#e": [request_event_id]},
            subscription_id=f"dvm-reply-{request_event_id[:8]}-{kind}",
        )
    )


def _publish_request_event(
    relay: LocalRelayRuntime,
    *,
    dvm_pubkey: str,
    read_model: str,
    param_tags: list[list[str]] | None = None,
) -> dict[str, object]:
    tags = [["p", dvm_pubkey], ["param", "read_model", read_model]]
    if param_tags is not None:
        tags.extend(param_tags)
    request_event = build_signed_event(
        kind=_REQUEST_KIND,
        content="",
        tags=tags,
        keys=_REQUESTER_KEYS,
    )
    ok = asyncio.run(publish_event(relay.ws_url, request_event.payload))
    assert ok.accepted is True
    assert ok.event_id == request_event.event_id
    return {
        "event_id": request_event.event_id,
        "pubkey": request_event.pubkey,
        "payload": request_event.payload,
    }


def _restart_dvm(stack: ComposeStack) -> None:
    stack.run("stop", "dvm")
    stack.wait_until_state("dvm", state="exited", timeout=60.0)
    stack.run("rm", "-f", "dvm")
    stack.up("dvm")
    stack.wait_until_ready(("dvm",), timeout=180.0)


def _wait_until(
    fetch_snapshot: Any,
    *,
    is_ready: Any,
    description: str,
    timeout: float = 90.0,
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


def _tag_values(event: dict[str, object], tag_name: str) -> list[list[str]]:
    values: list[list[str]] = []
    raw_tags = event.get("tags")
    if not isinstance(raw_tags, list):
        return values
    for tag in raw_tags:
        if isinstance(tag, list) and tag and tag[0] == tag_name:
            values.append([str(item) for item in tag])
    return values


def _capture_dvm_artifacts(
    bundle: SystemArtifactBundle,
    stack: ComposeStack,
    *,
    relay: LocalRelayRuntime,
    name: str,
    snapshot: dict[str, object],
) -> None:
    bundle.capture_container_logs(f"{name}-dvm", _dvm_logs(stack))
    bundle.capture_container_logs(f"{name}-relay", relay.logs())
    bundle.capture_relay_events(f"{name}-relay-events", snapshot)
    bundle.capture_db_snapshot(name, snapshot)
    bundle.write_json_artifact(
        category="relay",
        subdir="relay",
        name=f"{name}-relay-inspect",
        payload=relay.inspect(),
    )


def _assert_startup_announcement(
    announcement: dict[str, object],
    *,
    expected_pubkey: str,
    expected_name: str,
    expected_about: str,
    expected_d_tag: str,
    events_enabled: bool,
) -> None:
    content = json.loads(str(announcement["content"]))
    assert str(announcement["pubkey"]) == expected_pubkey
    assert content["name"] == expected_name
    assert content["about"] == expected_about
    assert "relays" in content["read_models"]
    assert ("events" in content["read_models"]) is events_enabled
    assert _tag_values(announcement, "d") == [["d", expected_d_tag]]
    assert _tag_values(announcement, "k") == [["k", str(_REQUEST_KIND)]]


def _assert_result_reply(
    result_event: dict[str, object],
    *,
    request_event_id: str,
    request_pubkey: str,
    expected_data: list[dict[str, object]],
    expected_meta: dict[str, object],
) -> None:
    content = json.loads(str(result_event["content"]))
    assert content["data"] == expected_data
    assert content["meta"] == expected_meta
    assert _tag_values(result_event, "e") == [["e", request_event_id]]
    assert _tag_values(result_event, "p") == [["p", request_pubkey]]
    request_tags = _tag_values(result_event, "request")
    assert len(request_tags) == 1
    assert json.loads(request_tags[0][1]) == {
        "id": request_event_id,
        "kind": _REQUEST_KIND,
    }
    assert _tag_values(result_event, "amount") == []


def _assert_error_reply(
    error_event: dict[str, object],
    *,
    request_event_id: str,
    request_pubkey: str,
    expected_status: str,
) -> None:
    assert int(error_event["kind"]) == _ERROR_KIND
    assert str(error_event["content"]) == ""
    assert _tag_values(error_event, "e") == [["e", request_event_id]]
    assert _tag_values(error_event, "p") == [["p", request_pubkey]]
    assert _tag_values(error_event, "status") == [["status", "error", expected_status]]


@pytest.mark.timeout(900)
def test_dvm_bigbrotr_announces_handles_requests_and_restores_cursor(tmp_path: Path) -> None:
    bundle, plan, stack = _prepare_dvm_run(
        tmp_path,
        "dvm-bigbrotr-relay-contract",
        profile="bigbrotr",
        slot=48,
    )
    relay = None
    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        relay = start_baseline_relay(plan)
        configure_runtime_relay_targets(plan, relay)
        _seed_dvm_contract(plan)

        expected_pubkey = _expected_dvm_pubkey(plan)

        stack.up("dvm", build=True)
        stack.wait_until_ready(("dvm",), timeout=180.0)

        startup_snapshot = _wait_until(
            lambda: {
                "announcements": _announcement_events(relay.ws_url, author=expected_pubkey),
                "cursor_rows": _dvm_cursor_rows(plan),
            },
            is_ready=lambda current: (
                len(current["announcements"]) == 1 and len(current["cursor_rows"]) == 1
            ),
            description="dvm startup announcement and cursor initialization",
        )
        startup_announcement = startup_snapshot["announcements"][0].event
        _assert_startup_announcement(
            startup_announcement,
            expected_pubkey=expected_pubkey,
            expected_name="BigBrotr DVM",
            expected_about="Read-only access to BigBrotr relay monitoring data",
            expected_d_tag="bigbrotr-dvm",
            events_enabled=False,
        )
        assert startup_snapshot["cursor_rows"] == (
            {
                "cursor_id": "0" * 64,
                "state_key": "job_requests",
                "timestamp": startup_snapshot["cursor_rows"][0]["timestamp"],
            },
        )

        relay_request = _publish_request_event(
            relay,
            dvm_pubkey=expected_pubkey,
            read_model="relays",
            param_tags=[["param", "limit", "1"], ["param", "include_total", "true"]],
        )
        relay_snapshot = _wait_until(
            lambda: {
                "replies": _reply_events(
                    relay.ws_url,
                    author=expected_pubkey,
                    request_event_id=str(relay_request["event_id"]),
                    kind=_RESULT_KIND,
                ),
                "cursor_rows": _dvm_cursor_rows(plan),
                "relay_rows": _relay_rows(plan),
            },
            is_ready=lambda current: (
                len(current["replies"]) == 1
                and len(current["cursor_rows"]) == 1
                and current["cursor_rows"][0]["cursor_id"] == relay_request["event_id"]
            ),
            description="dvm relay result event",
        )
        relay_result = relay_snapshot["replies"][0].event
        _assert_result_reply(
            relay_result,
            request_event_id=str(relay_request["event_id"]),
            request_pubkey=str(relay_request["pubkey"]),
            expected_data=list(relay_snapshot["relay_rows"]),
            expected_meta={
                "limit": 1,
                "offset": 0,
                "read_model": "relays",
                "total": 1,
            },
        )

        disabled_request = _publish_request_event(
            relay,
            dvm_pubkey=expected_pubkey,
            read_model="events",
        )
        disabled_snapshot = _wait_until(
            lambda: {
                "replies": _reply_events(
                    relay.ws_url,
                    author=expected_pubkey,
                    request_event_id=str(disabled_request["event_id"]),
                    kind=_ERROR_KIND,
                ),
                "cursor_rows": _dvm_cursor_rows(plan),
            },
            is_ready=lambda current: (
                len(current["replies"]) == 1
                and len(current["cursor_rows"]) == 1
                and current["cursor_rows"][0]["cursor_id"] == disabled_request["event_id"]
            ),
            description="dvm disabled read-model error",
        )
        disabled_error = disabled_snapshot["replies"][0].event
        _assert_error_reply(
            disabled_error,
            request_event_id=str(disabled_request["event_id"]),
            request_pubkey=str(disabled_request["pubkey"]),
            expected_status="Invalid or disabled read model: events",
        )

        _restart_dvm(stack)
        post_restart_snapshot = _wait_until(
            lambda: {
                "restored_results": _reply_events(
                    relay.ws_url,
                    author=expected_pubkey,
                    request_event_id=str(relay_request["event_id"]),
                    kind=_RESULT_KIND,
                ),
                "restored_errors": _reply_events(
                    relay.ws_url,
                    author=expected_pubkey,
                    request_event_id=str(disabled_request["event_id"]),
                    kind=_ERROR_KIND,
                ),
                "cursor_rows": _dvm_cursor_rows(plan),
                "logs": _dvm_logs(stack),
            },
            is_ready=lambda current: (
                len(current["restored_results"]) == 1
                and len(current["restored_errors"]) == 1
                and len(current["cursor_rows"]) == 1
                and current["cursor_rows"][0]["cursor_id"] == disabled_request["event_id"]
                and "request_cursor_restored" in current["logs"]
            ),
            description="dvm restart cursor restore without duplicate replay",
            timeout=120.0,
        )

        replay_request = _publish_request_event(
            relay,
            dvm_pubkey=expected_pubkey,
            read_model="relays",
            param_tags=[["param", "limit", "1"]],
        )
        replay_snapshot = _wait_until(
            lambda: {
                "replies": _reply_events(
                    relay.ws_url,
                    author=expected_pubkey,
                    request_event_id=str(replay_request["event_id"]),
                    kind=_RESULT_KIND,
                ),
                "cursor_rows": _dvm_cursor_rows(plan),
            },
            is_ready=lambda current: (
                len(current["replies"]) == 1
                and len(current["cursor_rows"]) == 1
                and current["cursor_rows"][0]["cursor_id"] == replay_request["event_id"]
            ),
            description="dvm post-restart request processing",
        )
        final_logs = _dvm_logs(stack)
        final_snapshot = {
            "startup": {
                "announcements": [frame.event for frame in startup_snapshot["announcements"]],
                "cursor_rows": startup_snapshot["cursor_rows"],
            },
            "relay_request": relay_request,
            "relay_result": relay_result,
            "disabled_request": disabled_request,
            "disabled_error": disabled_error,
            "post_restart": {
                "cursor_rows": post_restart_snapshot["cursor_rows"],
                "restored_results": [
                    frame.event for frame in post_restart_snapshot["restored_results"]
                ],
                "restored_errors": [
                    frame.event for frame in post_restart_snapshot["restored_errors"]
                ],
            },
            "replay_request": replay_request,
            "replay_result": replay_snapshot["replies"][0].event,
            "final_cursor_rows": replay_snapshot["cursor_rows"],
        }
        _capture_dvm_artifacts(
            bundle,
            stack,
            relay=relay,
            name="dvm-bigbrotr-relay-contract",
            snapshot=final_snapshot,
        )

        assert "announcement_published" in final_logs
        assert "request_cursor_restored" in final_logs
        assert "job_received" in final_logs
        assert "job_completed" in final_logs
    finally:
        capture_stack_artifacts(bundle, stack, services=DVM_ARTIFACT_SERVICES)
        if relay is not None:
            relay.stop()


@pytest.mark.timeout(900)
def test_dvm_lilbrotr_exposes_events_read_model_over_relay(tmp_path: Path) -> None:
    bundle, plan, stack = _prepare_dvm_run(
        tmp_path,
        "dvm-lilbrotr-events-contract",
        profile="lilbrotr",
        slot=49,
    )
    relay = None
    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        relay = start_baseline_relay(plan)
        configure_runtime_relay_targets(plan, relay)
        _seed_dvm_contract(plan)

        expected_pubkey = _expected_dvm_pubkey(plan)

        stack.up("dvm", build=True)
        stack.wait_until_ready(("dvm",), timeout=180.0)

        startup_snapshot = _wait_until(
            lambda: {
                "announcements": _announcement_events(relay.ws_url, author=expected_pubkey),
                "cursor_rows": _dvm_cursor_rows(plan),
            },
            is_ready=lambda current: (
                len(current["announcements"]) == 1 and len(current["cursor_rows"]) == 1
            ),
            description="lilbrotr dvm startup announcement",
        )
        startup_announcement = startup_snapshot["announcements"][0].event
        _assert_startup_announcement(
            startup_announcement,
            expected_pubkey=expected_pubkey,
            expected_name="LilBrotr DVM",
            expected_about="Read-only access to LilBrotr relay monitoring data",
            expected_d_tag="lilbrotr-dvm",
            events_enabled=True,
        )

        event_request = _publish_request_event(
            relay,
            dvm_pubkey=expected_pubkey,
            read_model="events",
            param_tags=[["param", "limit", "10"], ["param", "include_total", "true"]],
        )
        event_snapshot = _wait_until(
            lambda: {
                "replies": _reply_events(
                    relay.ws_url,
                    author=expected_pubkey,
                    request_event_id=str(event_request["event_id"]),
                    kind=_RESULT_KIND,
                ),
                "error_replies": _reply_events(
                    relay.ws_url,
                    author=expected_pubkey,
                    request_event_id=str(event_request["event_id"]),
                    kind=_ERROR_KIND,
                ),
                "cursor_rows": _dvm_cursor_rows(plan),
                "event_rows": _event_rows(plan),
            },
            is_ready=lambda current: (
                len(current["replies"]) == 1
                and len(current["error_replies"]) == 0
                and len(current["cursor_rows"]) == 1
                and current["cursor_rows"][0]["cursor_id"] == event_request["event_id"]
            ),
            description="lilbrotr dvm events result",
        )
        event_result = event_snapshot["replies"][0].event
        _assert_result_reply(
            event_result,
            request_event_id=str(event_request["event_id"]),
            request_pubkey=str(event_request["pubkey"]),
            expected_data=list(event_snapshot["event_rows"]),
            expected_meta={
                "limit": 10,
                "offset": 0,
                "read_model": "events",
                "total": 1,
            },
        )

        final_snapshot = {
            "startup": {
                "announcements": [frame.event for frame in startup_snapshot["announcements"]],
                "cursor_rows": startup_snapshot["cursor_rows"],
            },
            "event_request": event_request,
            "event_result": event_result,
            "event_rows": event_snapshot["event_rows"],
            "cursor_rows": event_snapshot["cursor_rows"],
        }
        _capture_dvm_artifacts(
            bundle,
            stack,
            relay=relay,
            name="dvm-lilbrotr-events-contract",
            snapshot=final_snapshot,
        )

        final_logs = _dvm_logs(stack)
        assert "announcement_published" in final_logs
        assert "job_received" in final_logs
        assert "job_completed" in final_logs
    finally:
        capture_stack_artifacts(bundle, stack, services=DVM_ARTIFACT_SERVICES)
        if relay is not None:
            relay.stop()
