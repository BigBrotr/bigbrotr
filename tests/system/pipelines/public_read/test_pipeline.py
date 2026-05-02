from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any
from urllib import parse, request

import pytest
import yaml
from nostr_sdk import Keys

from bigbrotr.core.brotr import Brotr
from tests.integration.harness.builders import build_relay
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
    RuntimeDatabaseTarget,
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


PUBLIC_READ_ARTIFACT_SERVICES = (*BOOTSTRAP_SERVICES, "api", "dvm")
_RESULT_KIND = 6050
_REQUEST_KIND = 5050
_REQUESTER_KEYS = Keys.parse(
    "71a1f9f06318b8074f8f3d7e7f00d7e0e0ca6abbb23772e0f5a4ed70854b71d7"  # pragma: allowlist secret
)
_RELAY_ROWS_SQL = """
    SELECT url, network, stored_at
    FROM relay
    ORDER BY url
"""
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
_INITIAL_RELAYS = (
    build_relay("wss://api-plain.example.com", stored_at=1_700_000_000),
    build_relay("wss://api-observed.example.com", stored_at=1_700_000_100),
)
_ADDED_RELAY = build_relay("wss://api-added.example.com", stored_at=1_700_000_200)


def _runtime_brotr(plan: RuntimeAddressPlan, *, role: str = "admin") -> Brotr:
    target = RuntimeDatabaseTarget.for_plan(plan, role=role)
    return Brotr.from_dict(
        {
            "pool": {
                "database": {
                    "host": target.host,
                    "port": target.port,
                    "database": target.database,
                    "user": target.user,
                    "password": target.password,
                }
            }
        }
    )


async def _async_insert_relays(plan: RuntimeAddressPlan, relays: tuple[Any, ...]) -> None:
    brotr = _runtime_brotr(plan, role="writer")
    async with brotr:
        await brotr.insert_relay(list(relays))


def _insert_relays(plan: RuntimeAddressPlan, relays: tuple[Any, ...]) -> None:
    asyncio.run(_async_insert_relays(plan, relays))


def _configure_api_runtime(plan: RuntimeAddressPlan) -> None:
    config_path = plan.runtime_root / "config" / "services" / "api.yaml"
    payload = yaml.safe_load(config_path.read_text())
    assert isinstance(payload, dict)
    payload["interval"] = 3600.0
    payload["request_timeout"] = 5.0
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False))


def _configure_dvm_runtime(plan: RuntimeAddressPlan) -> None:
    config_path = plan.runtime_root / "config" / "services" / "dvm.yaml"
    payload = yaml.safe_load(config_path.read_text())
    assert isinstance(payload, dict)
    payload["interval"] = 60.0
    payload["fetch_timeout"] = 5.0
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False))


def _prepare_public_read_run(
    tmp_path: Path,
    run_name: str,
    *,
    slot: int,
) -> tuple[SystemArtifactBundle, RuntimeAddressPlan, ComposeStack]:
    bundle = create_bundle(tmp_path, run_name)
    plan = RuntimeAddressPlan.create("bigbrotr", tmp_path / "runtime", run_name, slot=slot)
    prepare_runtime_compose_config(plan)
    _configure_api_runtime(plan)
    _configure_dvm_runtime(plan)
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)
    return bundle, plan, stack


def _api_logs(stack: ComposeStack) -> str:
    return stack.run("logs", "--no-color", "api", check=False).stdout


def _dvm_logs(stack: ComposeStack) -> str:
    return stack.run("logs", "--no-color", "dvm", check=False).stdout


def _service_host_port(plan: RuntimeAddressPlan, service_name: str, container_port: int) -> int:
    compose_data = yaml.safe_load(plan.compose_file.read_text())
    assert isinstance(compose_data, dict)
    services = compose_data.get("services")
    assert isinstance(services, dict)
    service_data = services.get(service_name)
    assert isinstance(service_data, dict)
    ports = service_data.get("ports")
    assert isinstance(ports, list)

    for spec in ports:
        if not isinstance(spec, str):
            continue
        parts = spec.split(":")
        if len(parts) < 3:
            continue
        if parts[-1] == str(container_port):
            return int(parts[-2])

    raise RuntimeError(f"Could not resolve host port for {service_name}:{container_port}")


def _api_base_url(plan: RuntimeAddressPlan) -> str:
    return f"http://127.0.0.1:{_service_host_port(plan, 'api', 8080)}"


def _http_get_json(base_url: str, path: str, *, timeout: float = 5.0) -> tuple[int, object]:
    req = request.Request(f"{base_url.rstrip('/')}{path}", method="GET")  # noqa: S310
    with request.urlopen(req, timeout=timeout) as response:  # noqa: S310
        return int(response.status), json.loads(response.read().decode())


def _relay_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _RELAY_ROWS_SQL)


def _dvm_cursor_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _DVM_CURSOR_ROWS_SQL)


def _expected_dvm_pubkey(plan: RuntimeAddressPlan) -> str:
    private_key = build_test_env_values(plan.profile, plan.project_name)["NOSTR_PRIVATE_KEY_DVM"]
    return Keys.parse(private_key).public_key().to_hex()


def _announcement_events(ws_url: str, *, author: str) -> tuple[RelayEventFrame, ...]:
    return asyncio.run(
        query_events(
            ws_url,
            filters={"kinds": [31990], "authors": [author]},
            subscription_id="public-read-dvm-announcement",
        )
    )


def _reply_events(
    ws_url: str,
    *,
    author: str,
    request_event_id: str,
) -> tuple[RelayEventFrame, ...]:
    return asyncio.run(
        query_events(
            ws_url,
            filters={"kinds": [_RESULT_KIND], "authors": [author], "#e": [request_event_id]},
            subscription_id=f"public-read-reply-{request_event_id[:8]}",
        )
    )


def _publish_relays_request(relay: LocalRelayRuntime, *, dvm_pubkey: str) -> dict[str, object]:
    request_event = build_signed_event(
        kind=_REQUEST_KIND,
        content="",
        tags=[
            ["p", dvm_pubkey],
            ["param", "read_model", "relays"],
            ["param", "limit", "10"],
            ["param", "include_total", "true"],
        ],
        keys=_REQUESTER_KEYS,
    )
    ok = asyncio.run(publish_event(relay.ws_url, request_event.payload))
    assert ok.accepted is True
    return {
        "event_id": request_event.event_id,
        "pubkey": request_event.pubkey,
        "payload": request_event.payload,
    }


def _wait_until(
    fetch_snapshot: Any,
    *,
    is_ready: Any,
    description: str,
    timeout: float = 120.0,
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


def _capture_public_read_artifacts(
    bundle: SystemArtifactBundle,
    stack: ComposeStack,
    *,
    relay: LocalRelayRuntime,
    name: str,
    snapshot: dict[str, object],
) -> None:
    bundle.capture_container_logs(f"{name}-api", _api_logs(stack))
    bundle.capture_container_logs(f"{name}-dvm", _dvm_logs(stack))
    bundle.capture_container_logs(f"{name}-relay", relay.logs())
    bundle.capture_db_snapshot(name, snapshot)
    bundle.write_json_artifact(
        category="relay",
        subdir="relay",
        name=f"{name}-relay-inspect",
        payload=relay.inspect(),
    )


def _await_public_read_startup(
    *,
    plan: RuntimeAddressPlan,
    stack: ComposeStack,
    base_url: str,
    relay: LocalRelayRuntime,
    dvm_pubkey: str,
) -> dict[str, object]:
    return _wait_until(
        lambda: {
            "health": _http_get_json(base_url, "/health"),
            "read_models": _http_get_json(base_url, "/v1/read-models"),
            "announcements": _announcement_events(relay.ws_url, author=dvm_pubkey),
            "cursor_rows": _dvm_cursor_rows(plan),
            "db_relays": _relay_rows(plan),
            "dvm_logs": _dvm_logs(stack),
        },
        is_ready=lambda current: (
            current["health"][0] == 200
            and current["read_models"][0] == 200
            and len(current["announcements"]) == 1
            and len(current["cursor_rows"]) == 1
            and len(current["db_relays"]) >= 2
            and "request_subscription_started" in current["dvm_logs"]
        ),
        description="public read startup contract",
    )


def _await_public_read_round(
    *,
    plan: RuntimeAddressPlan,
    base_url: str,
    relay: LocalRelayRuntime,
    dvm_pubkey: str,
    detail_url: str,
) -> tuple[dict[str, object], dict[str, object]]:
    request_payload = _publish_relays_request(relay, dvm_pubkey=dvm_pubkey)
    snapshot = _wait_until(
        lambda: {
            "api_relays": _http_get_json(base_url, "/v1/relays?limit=10&include_total=true"),
            "api_detail": _http_get_json(base_url, detail_url),
            "dvm_replies": _reply_events(
                relay.ws_url,
                author=dvm_pubkey,
                request_event_id=str(request_payload["event_id"]),
            ),
            "cursor_rows": _dvm_cursor_rows(plan),
            "db_relays": _relay_rows(plan),
        },
        is_ready=lambda current: (
            current["api_relays"][0] == 200
            and current["api_detail"][0] == 200
            and len(current["dvm_replies"]) == 1
            and current["cursor_rows"][0]["cursor_id"] == request_payload["event_id"]
        ),
        description=f"public read request {request_payload['event_id'][:8]}",
        timeout=180.0,
    )
    return request_payload, snapshot


def _assert_public_read_round(
    *,
    snapshot: dict[str, object],
    expected_rows: tuple[dict[str, object], ...],
    expected_total: int,
    expected_detail: dict[str, object],
) -> None:
    api_relays_payload = snapshot["api_relays"][1]
    dvm_relays_payload = json.loads(str(snapshot["dvm_replies"][0].event["content"]))
    assert api_relays_payload["data"] == list(expected_rows)
    assert dvm_relays_payload["data"] == list(expected_rows)
    assert api_relays_payload["meta"]["read_model"] == "relays"
    assert api_relays_payload["meta"]["total"] == expected_total
    assert dvm_relays_payload["meta"] == {
        "limit": 10,
        "offset": 0,
        "read_model": "relays",
        "total": expected_total,
    }
    assert snapshot["api_detail"][1]["data"] == expected_detail


@pytest.mark.timeout(1200)
def test_public_read_pipeline_exposes_shared_relay_state_through_api_and_dvm(
    tmp_path: Path,
) -> None:
    bundle, plan, stack = _prepare_public_read_run(
        tmp_path,
        "public-read-pipeline-contract",
        slot=55,
    )
    relay = None
    initial_snapshot: dict[str, object] | None = None
    updated_snapshot: dict[str, object] | None = None

    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        relay = start_baseline_relay(plan)
        configure_runtime_relay_targets(plan, relay)
        _insert_relays(plan, _INITIAL_RELAYS)

        base_url = _api_base_url(plan)
        expected_dvm_pubkey = _expected_dvm_pubkey(plan)

        stack.up("api", build=True)
        stack.up("dvm", build=True)
        stack.wait_until_ready(("api", "dvm"), timeout=180.0)

        startup_snapshot = _await_public_read_startup(
            plan=plan,
            stack=stack,
            base_url=base_url,
            relay=relay,
            dvm_pubkey=expected_dvm_pubkey,
        )
        announcement_content = json.loads(
            str(startup_snapshot["announcements"][0].event["content"])
        )
        assert "relays" in announcement_content["read_models"]

        encoded_first_relay = parse.quote(str(_INITIAL_RELAYS[0].url), safe="")
        first_request, initial_snapshot = _await_public_read_round(
            plan=plan,
            base_url=base_url,
            relay=relay,
            dvm_pubkey=expected_dvm_pubkey,
            detail_url=f"/v1/relays/{encoded_first_relay}",
        )
        _assert_public_read_round(
            snapshot=initial_snapshot,
            expected_rows=initial_snapshot["db_relays"],
            expected_total=2,
            expected_detail={
                "url": str(_INITIAL_RELAYS[0].url),
                "network": _INITIAL_RELAYS[0].network.value,
                "stored_at": _INITIAL_RELAYS[0].stored_at,
            },
        )

        _capture_public_read_artifacts(
            bundle,
            stack,
            relay=relay,
            name="public-read-initial",
            snapshot={
                "startup": startup_snapshot,
                "first_request": first_request,
                "initial": initial_snapshot,
            },
        )

        _insert_relays(plan, (_ADDED_RELAY,))

        encoded_added_relay = parse.quote(str(_ADDED_RELAY.url), safe="")
        second_request, updated_snapshot = _await_public_read_round(
            plan=plan,
            base_url=base_url,
            relay=relay,
            dvm_pubkey=expected_dvm_pubkey,
            detail_url=f"/v1/relays/{encoded_added_relay}",
        )
        _assert_public_read_round(
            snapshot=updated_snapshot,
            expected_rows=updated_snapshot["db_relays"],
            expected_total=3,
            expected_detail={
                "url": str(_ADDED_RELAY.url),
                "network": _ADDED_RELAY.network.value,
                "stored_at": _ADDED_RELAY.stored_at,
            },
        )

        final_api_logs = _api_logs(stack)
        final_dvm_logs = _dvm_logs(stack)
        assert "request_completed" in final_api_logs
        assert "announcement_published" in final_dvm_logs
        assert final_dvm_logs.count("job_completed") >= 2

        _capture_public_read_artifacts(
            bundle,
            stack,
            relay=relay,
            name="public-read-updated",
            snapshot={
                "initial": initial_snapshot,
                "second_request": second_request,
                "updated": updated_snapshot,
            },
        )
    finally:
        capture_stack_artifacts(bundle, stack, services=PUBLIC_READ_ARTIFACT_SERVICES)
        if relay is not None:
            relay.stop()
        stack.down()
