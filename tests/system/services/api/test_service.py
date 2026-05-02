from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any
from urllib import error, parse, request

import pytest
import yaml

from bigbrotr.core.brotr import Brotr
from tests.integration.harness.builders import build_event_observation, build_relay
from tests.system.deployments.baseline import (
    capture_stack_artifacts,
    create_bundle,
    create_stack,
    record_runtime_plan,
)
from tests.system.deployments.runtime_overrides import prepare_runtime_compose_config
from tests.system.harness import RuntimeAddressPlan, fetch_runtime_rows
from tests.system.harness.compose import build_test_env_values


if TYPE_CHECKING:
    from pathlib import Path

    from tests.system.harness import ComposeStack, SystemArtifactBundle


pytestmark = pytest.mark.system


API_BOOTSTRAP_SERVICES = ("postgres", "pgbouncer")
API_ARTIFACT_SERVICES = (*API_BOOTSTRAP_SERVICES, "api")
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
        content
    FROM event
    ORDER BY encode(id, 'hex')
"""
_RELAY_STATS_ROWS_SQL = """
    SELECT relay_url, event_count
    FROM relay_stats
    ORDER BY relay_url
"""
_PLAIN_RELAY_URL = "wss://api-plain.example.com"
_OBSERVED_RELAY_URL = "wss://api-observed.example.com"
_EVENT_ID = "10" * 32
_EVENT_PUBKEY = "22" * 32
_EVENT_CONTENT = "system-api-event"


def _runtime_brotr(plan: RuntimeAddressPlan, *, role: str = "admin") -> Brotr:
    env_values = build_test_env_values(plan.profile, plan.project_name)
    users = {
        "admin": ("admin", env_values["DB_ADMIN_PASSWORD"]),
        "writer": ("writer", env_values["DB_WRITER_PASSWORD"]),
        "reader": ("reader", env_values["DB_READER_PASSWORD"]),
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


async def _async_seed_api_contract(plan: RuntimeAddressPlan) -> None:
    brotr = _runtime_brotr(plan)
    async with brotr:
        await brotr.insert_relay([build_relay(_PLAIN_RELAY_URL, stored_at=1_700_000_000)])
        await brotr.insert_event_observation(
            [
                build_event_observation(
                    _EVENT_ID,
                    _OBSERVED_RELAY_URL,
                    pubkey=_EVENT_PUBKEY,
                    created_at=1_700_000_100,
                    content=_EVENT_CONTENT,
                )
            ],
            cascade=True,
        )
        await brotr.fetchval("SELECT relay_stats_refresh($1::BIGINT, $2::BIGINT)", 0, 2_000_000_000)


def _seed_api_contract(plan: RuntimeAddressPlan) -> None:
    asyncio.run(_async_seed_api_contract(plan))


def _configure_api_runtime(plan: RuntimeAddressPlan) -> None:
    config_path = plan.runtime_root / "config" / "services" / "api.yaml"
    payload = yaml.safe_load(config_path.read_text())
    assert isinstance(payload, dict)

    payload["interval"] = 3600.0
    payload["request_timeout"] = 5.0

    config_path.write_text(yaml.safe_dump(payload, sort_keys=False))


def _prepare_api_run(
    tmp_path: Path,
    run_name: str,
    *,
    profile: str,
    slot: int,
) -> tuple[SystemArtifactBundle, RuntimeAddressPlan, ComposeStack]:
    bundle = create_bundle(tmp_path, run_name)
    plan = RuntimeAddressPlan.create(profile, tmp_path / "runtime", run_name, slot=slot)
    prepare_runtime_compose_config(plan)
    _configure_api_runtime(plan)
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)
    return bundle, plan, stack


def _api_logs(stack: ComposeStack) -> str:
    return stack.run("logs", "--no-color", "api", check=False).stdout


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
        target = parts[-1]
        if target == str(container_port):
            return int(parts[-2])

    raise RuntimeError(f"Could not resolve host port for {service_name}:{container_port}")


def _api_base_url(plan: RuntimeAddressPlan) -> str:
    return f"http://127.0.0.1:{_service_host_port(plan, 'api', 8080)}"


def _http_get_json(
    base_url: str,
    path: str,
    *,
    timeout: float = 5.0,
) -> tuple[int, object]:
    url = f"{base_url.rstrip('/')}{path}"
    req = request.Request(url, method="GET")  # noqa: S310
    try:
        with request.urlopen(req, timeout=timeout) as response:  # noqa: S310
            return int(response.status), json.loads(response.read().decode())
    except error.HTTPError as exc:
        return int(exc.code), json.loads(exc.read().decode())


def _relay_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _RELAY_ROWS_SQL)


def _event_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _EVENT_ROWS_SQL)


def _relay_stats_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _RELAY_STATS_ROWS_SQL)


def _wait_until(
    fetch_snapshot: Any,
    *,
    is_ready: Any,
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


def _capture_api_artifacts(
    bundle: SystemArtifactBundle,
    stack: ComposeStack,
    *,
    name: str,
    responses: dict[str, object],
    snapshot: dict[str, object],
) -> None:
    bundle.capture_container_logs(f"{name}-api", _api_logs(stack))
    bundle.write_json_artifact(
        category="api",
        subdir="api",
        name=f"{name}-responses",
        payload=responses,
    )
    bundle.capture_db_snapshot(name, snapshot)


@pytest.mark.timeout(900)
def test_api_bigbrotr_serves_http_surface_and_survives_restart(tmp_path: Path) -> None:
    bundle, plan, stack = _prepare_api_run(
        tmp_path,
        "api-bigbrotr-http-contract",
        profile="bigbrotr",
        slot=46,
    )
    base_url = _api_base_url(plan)
    encoded_relay = parse.quote(_OBSERVED_RELAY_URL, safe="")
    initial_snapshot: dict[str, object] | None = None
    restart_snapshot: dict[str, object] | None = None

    try:
        stack.up(*API_BOOTSTRAP_SERVICES)
        stack.wait_until_ready(API_BOOTSTRAP_SERVICES)
        _seed_api_contract(plan)

        stack.up("api", build=True)
        stack.wait_until_ready(("api",), timeout=180.0)

        initial_snapshot = _wait_until(
            lambda: {
                "health": _http_get_json(base_url, "/health"),
                "read_models": _http_get_json(base_url, "/v1/read-models"),
                "relays": _http_get_json(base_url, "/v1/relays?limit=1&include_total=true"),
                "relay_detail": _http_get_json(base_url, f"/v1/relays/{encoded_relay}"),
                "relay_stats": _http_get_json(base_url, "/v1/relay-stats?limit=10"),
                "events_disabled": _http_get_json(base_url, "/v1/events"),
                "invalid_limit": _http_get_json(base_url, "/v1/relays?limit=bad"),
                "missing_relay": _http_get_json(
                    base_url, f"/v1/relays/{parse.quote('wss://missing.example.com', safe='')}"
                ),
                "db_relays": _relay_rows(plan),
                "db_event_rows": _event_rows(plan),
                "db_relay_stats": _relay_stats_rows(plan),
            },
            is_ready=lambda current: (
                current["health"][0] == 200
                and current["read_models"][0] == 200
                and current["relays"][0] == 200
                and current["relay_detail"][0] == 200
                and current["relay_stats"][0] == 200
                and current["events_disabled"][0] == 404
                and current["invalid_limit"][0] == 400
                and current["missing_relay"][0] == 404
            ),
            description="api bigbrotr HTTP contract",
        )

        read_model_ids = [entry["id"] for entry in initial_snapshot["read_models"][1]["data"]]
        assert "relays" in read_model_ids
        assert "relay-stats" in read_model_ids
        assert "events" not in read_model_ids

        relays_meta = initial_snapshot["relays"][1]["meta"]
        assert relays_meta["read_model"] == "relays"
        assert relays_meta["total"] == 2
        assert relays_meta["limit"] == 1
        assert relays_meta["next_cursor"]
        assert initial_snapshot["relays"][1]["data"][0]["url"] in {
            _OBSERVED_RELAY_URL,
            _PLAIN_RELAY_URL,
        }

        relay_detail = initial_snapshot["relay_detail"][1]["data"]
        assert relay_detail["url"] == _OBSERVED_RELAY_URL
        assert relay_detail["network"] == "clearnet"

        relay_stats_rows = initial_snapshot["relay_stats"][1]["data"]
        assert len(relay_stats_rows) == 1
        assert relay_stats_rows[0]["relay_url"] == _OBSERVED_RELAY_URL
        assert relay_stats_rows[0]["event_count"] == 1

        assert initial_snapshot["invalid_limit"][1]["error"] == "Invalid limit or offset"
        assert initial_snapshot["missing_relay"][1]["error"] == "not found"
        assert {row["url"] for row in initial_snapshot["db_relays"]} == {
            _OBSERVED_RELAY_URL,
            _PLAIN_RELAY_URL,
        }
        assert initial_snapshot["db_event_rows"] == (
            {
                "id": _EVENT_ID,
                "pubkey": _EVENT_PUBKEY,
                "created_at": 1_700_000_100,
                "kind": 1,
                "content": _EVENT_CONTENT,
            },
        )
        assert initial_snapshot["db_relay_stats"] == (
            {"relay_url": _OBSERVED_RELAY_URL, "event_count": 1},
        )
        _capture_api_artifacts(
            bundle,
            stack,
            name="api-bigbrotr-initial",
            responses={
                "health": initial_snapshot["health"][1],
                "read_models": initial_snapshot["read_models"][1],
                "relays": initial_snapshot["relays"][1],
                "relay_detail": initial_snapshot["relay_detail"][1],
                "relay_stats": initial_snapshot["relay_stats"][1],
                "events_disabled": initial_snapshot["events_disabled"][1],
                "invalid_limit": initial_snapshot["invalid_limit"][1],
                "missing_relay": initial_snapshot["missing_relay"][1],
            },
            snapshot={
                "relays": initial_snapshot["db_relays"],
                "events": initial_snapshot["db_event_rows"],
                "relay_stats": initial_snapshot["db_relay_stats"],
            },
        )

        stack.run("restart", "api")
        stack.wait_until_ready(("api",), timeout=180.0)

        restart_snapshot = _wait_until(
            lambda: {
                "health": _http_get_json(base_url, "/health"),
                "read_models": _http_get_json(base_url, "/v1/read-models"),
                "relay_detail": _http_get_json(base_url, f"/v1/relays/{encoded_relay}"),
                "relay_stats": _http_get_json(base_url, "/v1/relay-stats?limit=10"),
            },
            is_ready=lambda current: (
                current["health"][0] == 200
                and current["read_models"][0] == 200
                and current["relay_detail"][0] == 200
                and current["relay_stats"][0] == 200
            ),
            description="api restart contract",
        )
        assert (
            restart_snapshot["read_models"][1]["data"] == initial_snapshot["read_models"][1]["data"]
        )
        assert (
            restart_snapshot["relay_detail"][1]["data"]
            == initial_snapshot["relay_detail"][1]["data"]
        )
        assert (
            restart_snapshot["relay_stats"][1]["data"] == initial_snapshot["relay_stats"][1]["data"]
        )

        api_logs = _api_logs(stack)
        assert api_logs.count("http_server_started") >= 2
        assert "request_completed" in api_logs
        assert "request_failed" in api_logs
        _capture_api_artifacts(
            bundle,
            stack,
            name="api-bigbrotr-restart",
            responses={
                "health": restart_snapshot["health"][1],
                "read_models": restart_snapshot["read_models"][1],
                "relay_detail": restart_snapshot["relay_detail"][1],
                "relay_stats": restart_snapshot["relay_stats"][1],
            },
            snapshot={
                "relays": _relay_rows(plan),
                "events": _event_rows(plan),
                "relay_stats": _relay_stats_rows(plan),
            },
        )
    finally:
        capture_stack_artifacts(bundle, stack, services=API_ARTIFACT_SERVICES)
        stack.down()


@pytest.mark.timeout(900)
def test_api_lilbrotr_profile_exposes_events_surface(tmp_path: Path) -> None:
    bundle, plan, stack = _prepare_api_run(
        tmp_path,
        "api-lilbrotr-events-surface",
        profile="lilbrotr",
        slot=47,
    )
    base_url = _api_base_url(plan)
    event_path = f"/v1/events/{_EVENT_ID}"
    snapshot: dict[str, object] | None = None

    try:
        stack.up(*API_BOOTSTRAP_SERVICES)
        stack.wait_until_ready(API_BOOTSTRAP_SERVICES)
        _seed_api_contract(plan)

        stack.up("api", build=True)
        stack.wait_until_ready(("api",), timeout=180.0)

        snapshot = _wait_until(
            lambda: {
                "health": _http_get_json(base_url, "/health"),
                "read_models": _http_get_json(base_url, "/v1/read-models"),
                "events": _http_get_json(base_url, "/v1/events?limit=10"),
                "event_detail": _http_get_json(base_url, event_path),
                "db_events": _event_rows(plan),
            },
            is_ready=lambda current: (
                current["health"][0] == 200
                and current["read_models"][0] == 200
                and current["events"][0] == 200
                and current["event_detail"][0] == 200
            ),
            description="api lilbrotr events surface",
        )

        read_model_ids = [entry["id"] for entry in snapshot["read_models"][1]["data"]]
        assert "events" in read_model_ids

        db_event = snapshot["db_events"][0]
        events_payload = snapshot["events"][1]
        assert events_payload["meta"]["read_model"] == "events"
        assert len(events_payload["data"]) == 1
        assert events_payload["data"][0]["id"] == db_event["id"]
        assert events_payload["data"][0]["pubkey"] == db_event["pubkey"]
        assert events_payload["data"][0]["kind"] == db_event["kind"]
        assert events_payload["data"][0]["content"] == db_event["content"]

        event_detail = snapshot["event_detail"][1]["data"]
        assert event_detail["id"] == db_event["id"]
        assert event_detail["pubkey"] == db_event["pubkey"]
        assert event_detail["kind"] == db_event["kind"]
        assert event_detail["content"] == db_event["content"]
        assert db_event["id"] == _EVENT_ID
        assert db_event["pubkey"] == _EVENT_PUBKEY
        assert db_event["created_at"] == 1_700_000_100
        assert db_event["kind"] == 1
        _capture_api_artifacts(
            bundle,
            stack,
            name="api-lilbrotr-events",
            responses={
                "health": snapshot["health"][1],
                "read_models": snapshot["read_models"][1],
                "events": snapshot["events"][1],
                "event_detail": snapshot["event_detail"][1],
            },
            snapshot={"events": snapshot["db_events"]},
        )
    finally:
        capture_stack_artifacts(bundle, stack, services=API_ARTIFACT_SERVICES)
        stack.down()
