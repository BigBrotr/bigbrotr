from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from bigbrotr.models.constants import EventKind
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
    resolve_runtime_relay_url,
    start_baseline_relay,
)
from tests.system.harness import RuntimeAddressPlan
from tests.system.services.api import test_service as api_helpers
from tests.system.services.assertor import test_service as assertor_helpers
from tests.system.services.dvm import test_service as dvm_helpers
from tests.system.services.ranker import test_service as ranker_helpers


pytestmark = pytest.mark.system


_PROFILES = ("bigbrotr", "lilbrotr")


def _load_service_config(profile: str, service_name: str) -> dict[str, object]:
    payload = yaml.safe_load(
        Path(f"deployments/{profile}/config/services/{service_name}.yaml").read_text()
    )
    assert isinstance(payload, dict)
    return payload


def _enabled_read_model_ids(config: dict[str, object]) -> tuple[str, ...]:
    read_models = config.get("read_models")
    assert isinstance(read_models, dict)
    enabled: list[str] = []
    for name, value in read_models.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            continue
        if value.get("enabled") is True:
            enabled.append(name)
    return tuple(enabled)


def _score_snapshot_signature(
    scores: dict[str, tuple[dict[str, object], ...]],
) -> dict[str, tuple[tuple[str, str], ...]]:
    return {
        name: tuple((str(row["subject_id"]), str(row["score"])) for row in rows)
        for name, rows in scores.items()
    }


def _rank_run_signature(
    rows: tuple[dict[str, object], ...],
) -> tuple[tuple[int, str, str, int, int], ...]:
    return tuple(
        (
            int(row["run_id"]),
            str(row["algorithm_id"]),
            str(row["status"]),
            int(row["node_count"]),
            int(row["edge_count"]),
        )
        for row in rows
    )


def _api_event_rows_signature(
    rows: tuple[dict[str, object], ...],
) -> tuple[tuple[str, str, int, int], ...]:
    return tuple(
        (
            str(row["id"]),
            str(row["pubkey"]),
            int(row["created_at"]),
            int(row["kind"]),
        )
        for row in rows
    )


def _dvm_event_rows_signature(
    rows: tuple[dict[str, object], ...],
) -> tuple[tuple[str, str, int, int, str], ...]:
    return tuple(
        (
            str(row["id"]),
            str(row["pubkey"]),
            int(row["created_at"]),
            int(row["kind"]),
            json.dumps(row["tagvalues"], sort_keys=True),
        )
        for row in rows
    )


def _assertor_events_by_kind(events: list[dict[str, object]]) -> dict[int, dict[str, object]]:
    mapping = {int(event["kind"]): event for event in events}
    assert set(mapping) == set(assertor_helpers._ASSERTOR_KINDS)
    return mapping


def _normalize_assertor_event(
    event: dict[str, object],
    *,
    provider_pubkey: str,
) -> dict[str, object]:
    normalized: dict[str, object] = {"kind": int(event["kind"])}
    raw_tags = event.get("tags")
    assert isinstance(raw_tags, list)

    tags: list[list[str]] = []
    for raw_tag in raw_tags:
        assert isinstance(raw_tag, list)
        tag = [str(item) for item in raw_tag]
        if (
            int(event["kind"]) == int(EventKind.NIP85_TRUSTED_PROVIDER_LIST)
            and len(tag) > 1
            and tag[1] == provider_pubkey
        ):
            tag[1] = "<provider-pubkey>"
        tags.append(tag)

    if int(event["kind"]) == int(EventKind.SET_METADATA):
        content = json.loads(str(event["content"]))
        content["name"] = "<profile-name>"
        content["software"] = "<profile-software>"
        normalized["content"] = content
    else:
        normalized["content"] = str(event["content"])

    normalized["tags"] = tags
    return normalized


def _prepare_assertor_profile_run(
    tmp_path: Path,
    run_name: str,
    *,
    profile: str,
    slot: int,
):
    bundle = create_bundle(tmp_path, run_name)
    plan = RuntimeAddressPlan.create(profile, tmp_path / "runtime", run_name, slot=slot)
    prepare_runtime_compose_config(plan)
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)
    return bundle, plan, stack


def _configure_assertor_profile_runtime(plan: RuntimeAddressPlan, *, relay_url: str) -> None:
    config_path = plan.runtime_root / "config" / "services" / "assertor.yaml"
    payload = yaml.safe_load(config_path.read_text())
    assert isinstance(payload, dict)

    payload["interval"] = 3600.0
    payload["algorithm_id"] = assertor_helpers._ALGORITHM_ID
    payload["selection"] = {
        "batch_size": 25,
        "min_events": 1,
        "top_topics": 5,
        "kinds": [30382, 30383, 30384, 30385],
    }
    payload["cleanup"] = {"remove_stale_checkpoints": True}
    payload["publishing"] = {
        "relays": [relay_url],
        "allow_insecure": False,
    }

    config_path.write_text(yaml.safe_dump(payload, sort_keys=False))


def _run_ranker_profile_contract(
    tmp_path: Path,
    *,
    profile: str,
    run_name: str,
    slot: int,
) -> dict[str, object]:
    bundle, plan, stack = ranker_helpers._prepare_ranker_run(
        tmp_path,
        run_name,
        profile=profile,
        slot=slot,
    )
    snapshot: dict[str, object] | None = None

    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)
        ranker_helpers._seed_ranker_inputs(plan)

        stack.up("ranker", build=True)
        stack.wait_until_ready(("ranker",), timeout=180.0)

        snapshot = ranker_helpers._wait_until(
            lambda: {
                "scores": ranker_helpers._score_snapshot(plan),
                "duckdb_exists": (plan.ranker_data_dir / "ranker.duckdb").is_file(),
                "logs": ranker_helpers._ranker_logs(stack),
            },
            is_ready=lambda current: (
                current["duckdb_exists"]
                and "ranker_cycle_completed" in current["logs"]
                and [row["subject_id"] for row in current["scores"]["pubkey"]]
                == [
                    ranker_helpers._PUBKEY_A,
                    ranker_helpers._PUBKEY_B,
                    ranker_helpers._PUBKEY_C,
                    ranker_helpers._PUBKEY_D,
                ]
            ),
            description=f"{profile} ranker parity export",
        )
        ranker_helpers._stop_ranker(stack)

        store = ranker_helpers._ranker_store(plan)
        result = {
            "profile": profile,
            "project_name": plan.project_name,
            "scores": snapshot["scores"],
            "checkpoint": store.load_checkpoint(),
            "rank_run_rows": ranker_helpers._rank_run_rows(plan),
            "graph_stats": store.get_graph_stats(),
        }
        ranker_helpers._capture_ranker_artifacts(
            bundle,
            stack,
            plan,
            name=f"{profile}-runtime-parity",
            snapshot=result,
        )
        return result
    finally:
        capture_stack_artifacts(bundle, stack, services=ranker_helpers.RANKER_ARTIFACT_SERVICES)
        stack.down()


def _run_api_profile_contract(
    tmp_path: Path,
    *,
    profile: str,
    run_name: str,
    slot: int,
) -> dict[str, object]:
    bundle, plan, stack = api_helpers._prepare_api_run(
        tmp_path,
        run_name,
        profile=profile,
        slot=slot,
    )
    service_config = _load_service_config(profile, "api")
    event_route_expected = "events" in _enabled_read_model_ids(service_config)

    try:
        stack.up(*api_helpers.API_BOOTSTRAP_SERVICES)
        stack.wait_until_ready(api_helpers.API_BOOTSTRAP_SERVICES)
        api_helpers._seed_api_contract(plan)

        stack.up("api", build=True)
        stack.wait_until_ready(("api",), timeout=180.0)

        base_url = api_helpers._api_base_url(plan)
        encoded_relay = api_helpers.parse.quote(api_helpers._OBSERVED_RELAY_URL, safe="")
        snapshot = api_helpers._wait_until(
            lambda: {
                "health": api_helpers._http_get_json(base_url, "/health"),
                "read_models": api_helpers._http_get_json(base_url, "/v1/read-models"),
                "relays": api_helpers._http_get_json(base_url, "/v1/relays?limit=10"),
                "relay_detail": api_helpers._http_get_json(base_url, f"/v1/relays/{encoded_relay}"),
                "relay_stats": api_helpers._http_get_json(base_url, "/v1/relay-stats?limit=10"),
                "events": api_helpers._http_get_json(base_url, "/v1/events?limit=10"),
                "db_relays": api_helpers._relay_rows(plan),
                "db_events": api_helpers._event_rows(plan),
                "db_relay_stats": api_helpers._relay_stats_rows(plan),
            },
            is_ready=lambda current: (
                current["health"][0] == 200
                and current["read_models"][0] == 200
                and current["relays"][0] == 200
                and current["relay_detail"][0] == 200
                and current["relay_stats"][0] == 200
                and current["events"][0] == (200 if event_route_expected else 404)
            ),
            description=f"{profile} API parity contract",
        )

        api_helpers._capture_api_artifacts(
            bundle,
            stack,
            name=f"{profile}-runtime-parity",
            responses={
                "health": snapshot["health"][1],
                "read_models": snapshot["read_models"][1],
                "relays": snapshot["relays"][1],
                "relay_detail": snapshot["relay_detail"][1],
                "relay_stats": snapshot["relay_stats"][1],
                "events": snapshot["events"][1],
            },
            snapshot={
                "relays": snapshot["db_relays"],
                "events": snapshot["db_events"],
                "relay_stats": snapshot["db_relay_stats"],
            },
        )
        return {
            "profile": profile,
            "config": service_config,
            "snapshot": snapshot,
        }
    finally:
        capture_stack_artifacts(bundle, stack, services=api_helpers.API_ARTIFACT_SERVICES)
        stack.down()


def _run_dvm_profile_contract(
    tmp_path: Path,
    *,
    profile: str,
    run_name: str,
    slot: int,
) -> dict[str, object]:
    bundle, plan, stack = dvm_helpers._prepare_dvm_run(
        tmp_path,
        run_name,
        profile=profile,
        slot=slot,
    )
    relay = None
    service_config = _load_service_config(profile, "dvm")
    event_route_expected = "events" in _enabled_read_model_ids(service_config)

    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        relay = start_baseline_relay(plan)
        configure_runtime_relay_targets(plan, relay)
        dvm_helpers._seed_dvm_contract(plan)

        expected_pubkey = dvm_helpers._expected_dvm_pubkey(plan)
        stack.up("dvm", build=True)
        stack.wait_until_ready(("dvm",), timeout=180.0)

        startup_snapshot = dvm_helpers._wait_until(
            lambda: {
                "announcements": dvm_helpers._announcement_events(
                    relay.ws_url, author=expected_pubkey
                ),
                "cursor_rows": dvm_helpers._dvm_cursor_rows(plan),
            },
            is_ready=lambda current: (
                len(current["announcements"]) == 1 and len(current["cursor_rows"]) == 1
            ),
            description=f"{profile} DVM startup announcement",
        )

        relays_request = dvm_helpers._publish_request_event(
            relay,
            dvm_pubkey=expected_pubkey,
            read_model="relays",
            param_tags=[["param", "limit", "1"], ["param", "include_total", "true"]],
        )
        relays_snapshot = dvm_helpers._wait_until(
            lambda: {
                "replies": dvm_helpers._reply_events(
                    relay.ws_url,
                    author=expected_pubkey,
                    request_event_id=str(relays_request["event_id"]),
                    kind=dvm_helpers._RESULT_KIND,
                ),
                "cursor_rows": dvm_helpers._dvm_cursor_rows(plan),
                "relay_rows": dvm_helpers._relay_rows(plan),
            },
            is_ready=lambda current: (
                len(current["replies"]) == 1
                and len(current["cursor_rows"]) == 1
                and current["cursor_rows"][0]["cursor_id"] == relays_request["event_id"]
            ),
            description=f"{profile} DVM relays result",
        )

        events_request = dvm_helpers._publish_request_event(
            relay,
            dvm_pubkey=expected_pubkey,
            read_model="events",
            param_tags=[["param", "limit", "10"], ["param", "include_total", "true"]],
        )
        events_snapshot = dvm_helpers._wait_until(
            lambda: {
                "results": dvm_helpers._reply_events(
                    relay.ws_url,
                    author=expected_pubkey,
                    request_event_id=str(events_request["event_id"]),
                    kind=dvm_helpers._RESULT_KIND,
                ),
                "errors": dvm_helpers._reply_events(
                    relay.ws_url,
                    author=expected_pubkey,
                    request_event_id=str(events_request["event_id"]),
                    kind=dvm_helpers._ERROR_KIND,
                ),
                "cursor_rows": dvm_helpers._dvm_cursor_rows(plan),
                "event_rows": dvm_helpers._event_rows(plan),
            },
            is_ready=lambda current: (
                len(current["cursor_rows"]) == 1
                and current["cursor_rows"][0]["cursor_id"] == events_request["event_id"]
                and len(current["results"]) == (1 if event_route_expected else 0)
                and len(current["errors"]) == (0 if event_route_expected else 1)
            ),
            description=f"{profile} DVM events profile difference",
        )

        final_snapshot = {
            "startup": {
                "announcements": [frame.event for frame in startup_snapshot["announcements"]],
                "cursor_rows": startup_snapshot["cursor_rows"],
            },
            "relays_request": relays_request,
            "relays_result": relays_snapshot["replies"][0].event,
            "relay_rows": relays_snapshot["relay_rows"],
            "events_request": events_request,
            "events_result": (
                events_snapshot["results"][0].event if events_snapshot["results"] else None
            ),
            "events_error": (
                events_snapshot["errors"][0].event if events_snapshot["errors"] else None
            ),
            "event_rows": events_snapshot["event_rows"],
            "cursor_rows": events_snapshot["cursor_rows"],
        }
        dvm_helpers._capture_dvm_artifacts(
            bundle,
            stack,
            relay=relay,
            name=f"{profile}-runtime-parity",
            snapshot=final_snapshot,
        )
        return {
            "profile": profile,
            "config": service_config,
            "pubkey": expected_pubkey,
            "snapshot": final_snapshot,
        }
    finally:
        capture_stack_artifacts(bundle, stack, services=dvm_helpers.DVM_ARTIFACT_SERVICES)
        if relay is not None:
            relay.stop()
        stack.down()


def _run_assertor_profile_contract(
    tmp_path: Path,
    *,
    profile: str,
    run_name: str,
    slot: int,
) -> dict[str, object]:
    bundle, plan, stack = _prepare_assertor_profile_run(
        tmp_path,
        run_name,
        profile=profile,
        slot=slot,
    )
    relay = None
    service_config = _load_service_config(profile, "assertor")

    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        relay = start_baseline_relay(plan)
        relay_url = resolve_runtime_relay_url(plan, relay)
        _configure_assertor_profile_runtime(plan, relay_url=relay_url)
        assertor_helpers._seed_assertor_inputs(plan)

        stack.up("assertor", build=True)
        stack.wait_until_ready(("assertor",), timeout=180.0)

        snapshot = assertor_helpers._wait_until(
            lambda: {
                "events": assertor_helpers._captured_assertor_events(relay.ws_url),
                "checkpoints": assertor_helpers._assertor_checkpoints(plan),
                "cycle_count": assertor_helpers._assertor_log_count(stack, "cycle_completed"),
            },
            is_ready=lambda current: (
                len(current["events"]) == 6
                and len(current["checkpoints"]) == 6
                and current["cycle_count"] >= 1
            ),
            description=f"{profile} assertor parity publication",
        )

        final_snapshot = {
            "events": [frame.event for frame in snapshot["events"]],
            "checkpoints": snapshot["checkpoints"],
        }
        assertor_helpers._capture_assertor_artifacts(
            bundle,
            stack,
            relay=relay,
            name=f"{profile}-runtime-parity",
            snapshot=final_snapshot,
        )
        return {
            "profile": profile,
            "config": service_config,
            "pubkey": assertor_helpers._expected_assertor_pubkey(plan),
            "snapshot": final_snapshot,
        }
    finally:
        capture_stack_artifacts(bundle, stack, services=assertor_helpers.ASSERTOR_ARTIFACT_SERVICES)
        if relay is not None:
            relay.stop()
        stack.down()


@pytest.mark.timeout(1800)
def test_ranker_profiles_preserve_shared_score_contract_and_isolate_private_store(
    tmp_path: Path,
) -> None:
    bigbrotr = _run_ranker_profile_contract(
        tmp_path,
        profile="bigbrotr",
        run_name="ranker-bigbrotr-runtime-parity",
        slot=80,
    )
    lilbrotr = _run_ranker_profile_contract(
        tmp_path,
        profile="lilbrotr",
        run_name="ranker-lilbrotr-runtime-parity",
        slot=81,
    )

    assert _score_snapshot_signature(bigbrotr["scores"]) == _score_snapshot_signature(
        lilbrotr["scores"]
    )
    assert bigbrotr["checkpoint"] == lilbrotr["checkpoint"]
    assert _rank_run_signature(bigbrotr["rank_run_rows"]) == _rank_run_signature(
        lilbrotr["rank_run_rows"]
    )
    assert bigbrotr["graph_stats"] == lilbrotr["graph_stats"]
    assert str(bigbrotr["project_name"]).startswith("bb-sys-")
    assert str(lilbrotr["project_name"]).startswith("lb-sys-")


@pytest.mark.timeout(1800)
def test_api_profiles_expose_only_intended_public_surface_differences(tmp_path: Path) -> None:
    api_results = {
        profile: _run_api_profile_contract(
            tmp_path,
            profile=profile,
            run_name=f"api-{profile}-runtime-parity",
            slot=82 + index,
        )
        for index, profile in enumerate(_PROFILES)
    }

    big_api = api_results["bigbrotr"]
    lil_api = api_results["lilbrotr"]
    big_api_ids = {entry["id"] for entry in big_api["snapshot"]["read_models"][1]["data"]}
    lil_api_ids = {entry["id"] for entry in lil_api["snapshot"]["read_models"][1]["data"]}

    assert big_api_ids == set(_enabled_read_model_ids(big_api["config"]))
    assert lil_api_ids == set(_enabled_read_model_ids(lil_api["config"]))
    assert lil_api_ids - big_api_ids == {"events", "event-observations"}
    assert big_api["snapshot"]["relays"][1] == lil_api["snapshot"]["relays"][1]
    assert big_api["snapshot"]["relay_detail"][1] == lil_api["snapshot"]["relay_detail"][1]
    assert big_api["snapshot"]["relay_stats"][1] == lil_api["snapshot"]["relay_stats"][1]
    assert big_api["snapshot"]["db_relays"] == lil_api["snapshot"]["db_relays"]
    assert big_api["snapshot"]["db_relay_stats"] == lil_api["snapshot"]["db_relay_stats"]
    assert big_api["snapshot"]["events"][0] == 404
    assert lil_api["snapshot"]["events"][0] == 200
    assert _api_event_rows_signature(big_api["snapshot"]["db_events"]) == _api_event_rows_signature(
        lil_api["snapshot"]["db_events"]
    )
    assert big_api["snapshot"]["db_events"][0]["content"] == api_helpers._EVENT_CONTENT
    assert lil_api["snapshot"]["db_events"][0]["content"] is None
    assert lil_api["snapshot"]["events"][1]["data"][0]["id"] == api_helpers._EVENT_ID


@pytest.mark.timeout(1800)
def test_dvm_profiles_expose_only_intended_public_surface_differences(tmp_path: Path) -> None:
    dvm_results = {
        profile: _run_dvm_profile_contract(
            tmp_path,
            profile=profile,
            run_name=f"dvm-{profile}-runtime-parity",
            slot=84 + index,
        )
        for index, profile in enumerate(_PROFILES)
    }

    big_dvm = dvm_results["bigbrotr"]
    lil_dvm = dvm_results["lilbrotr"]
    big_announcement = big_dvm["snapshot"]["startup"]["announcements"][0]
    lil_announcement = lil_dvm["snapshot"]["startup"]["announcements"][0]
    big_config = big_dvm["config"]
    lil_config = lil_dvm["config"]
    big_name = str(big_config.get("name", "BigBrotr DVM"))
    big_about = str(big_config.get("about", "Read-only access to BigBrotr relay monitoring data"))
    big_d_tag = str(big_config.get("d_tag", "bigbrotr-dvm"))

    big_content = json.loads(str(big_announcement["content"]))
    lil_content = json.loads(str(lil_announcement["content"]))
    assert str(big_announcement["pubkey"]) == big_dvm["pubkey"]
    assert str(lil_announcement["pubkey"]) == lil_dvm["pubkey"]
    assert big_content["name"] == big_name
    assert lil_content["name"] == lil_config["name"]
    assert big_content["about"] == big_about
    assert lil_content["about"] == lil_config["about"]
    assert set(big_content["read_models"]) == set(_enabled_read_model_ids(big_config))
    assert set(lil_content["read_models"]) == set(_enabled_read_model_ids(lil_config))
    assert dvm_helpers._tag_values(big_announcement, "d") == [["d", big_d_tag]]
    assert dvm_helpers._tag_values(lil_announcement, "d") == [["d", str(lil_config["d_tag"])]]
    assert big_dvm["snapshot"]["relay_rows"] == lil_dvm["snapshot"]["relay_rows"]
    assert (
        big_dvm["snapshot"]["relays_result"]["content"]
        == lil_dvm["snapshot"]["relays_result"]["content"]
    )
    assert _dvm_event_rows_signature(
        big_dvm["snapshot"]["event_rows"]
    ) == _dvm_event_rows_signature(lil_dvm["snapshot"]["event_rows"])
    assert any(row["content"] is not None for row in big_dvm["snapshot"]["event_rows"])
    assert all(row["content"] is None for row in lil_dvm["snapshot"]["event_rows"])
    assert any(row["tags"] is not None for row in big_dvm["snapshot"]["event_rows"])
    assert all(row["tags"] is None for row in lil_dvm["snapshot"]["event_rows"])
    assert any(row["sig"] is not None for row in big_dvm["snapshot"]["event_rows"])
    assert all(row["sig"] is None for row in lil_dvm["snapshot"]["event_rows"])
    assert big_dvm["snapshot"]["events_result"] is None
    assert big_dvm["snapshot"]["events_error"] is not None
    assert lil_dvm["snapshot"]["events_result"] is not None
    assert lil_dvm["snapshot"]["events_error"] is None
    assert dvm_helpers._tag_values(big_dvm["snapshot"]["events_error"], "status") == [
        ["status", "error", "Invalid or disabled read model: events"]
    ]
    assert json.loads(str(lil_dvm["snapshot"]["events_result"]["content"]))["data"] == list(
        lil_dvm["snapshot"]["event_rows"]
    )


@pytest.mark.timeout(1800)
def test_assertor_profiles_preserve_assertion_payloads_and_only_vary_provider_identity(
    tmp_path: Path,
) -> None:
    results = {
        profile: _run_assertor_profile_contract(
            tmp_path,
            profile=profile,
            run_name=f"assertor-{profile}-runtime-parity",
            slot=86 + index,
        )
        for index, profile in enumerate(_PROFILES)
    }

    bigbrotr = results["bigbrotr"]
    lilbrotr = results["lilbrotr"]
    big_events = _assertor_events_by_kind(bigbrotr["snapshot"]["events"])
    lil_events = _assertor_events_by_kind(lilbrotr["snapshot"]["events"])
    big_config = bigbrotr["config"]
    lil_config = lilbrotr["config"]

    big_metadata = json.loads(str(big_events[int(EventKind.SET_METADATA)]["content"]))
    lil_metadata = json.loads(str(lil_events[int(EventKind.SET_METADATA)]["content"]))
    assert big_metadata["name"] == big_config["provider_profile"]["kind0_content"]["name"]
    assert lil_metadata["name"] == lil_config["provider_profile"]["kind0_content"]["name"]
    assert big_metadata["about"] == big_config["provider_profile"]["kind0_content"]["about"]
    assert lil_metadata["about"] == lil_config["provider_profile"]["kind0_content"]["about"]
    assert big_metadata["website"] == big_config["provider_profile"]["kind0_content"]["website"]
    assert lil_metadata["website"] == lil_config["provider_profile"]["kind0_content"]["website"]
    assert (
        big_metadata["software"]
        == big_config["provider_profile"]["kind0_content"]["extra_fields"]["software"]
    )
    assert (
        lil_metadata["software"]
        == lil_config["provider_profile"]["kind0_content"]["extra_fields"]["software"]
    )

    expected_big_tags = [
        [f"{kind}:rank", bigbrotr["pubkey"], big_config["trusted_provider_list"]["relay_hint"]]
        for kind in ("30382", "30383", "30384", "30385")
    ]
    expected_lil_tags = [
        [f"{kind}:rank", lilbrotr["pubkey"], lil_config["trusted_provider_list"]["relay_hint"]]
        for kind in ("30382", "30383", "30384", "30385")
    ]
    assert big_events[int(EventKind.NIP85_TRUSTED_PROVIDER_LIST)]["tags"] == expected_big_tags
    assert lil_events[int(EventKind.NIP85_TRUSTED_PROVIDER_LIST)]["tags"] == expected_lil_tags

    normalized_big = {
        kind: _normalize_assertor_event(event, provider_pubkey=bigbrotr["pubkey"])
        for kind, event in sorted(big_events.items())
    }
    normalized_lil = {
        kind: _normalize_assertor_event(event, provider_pubkey=lilbrotr["pubkey"])
        for kind, event in sorted(lil_events.items())
    }
    assert normalized_big == normalized_lil
    assert tuple(row["state_key"] for row in bigbrotr["snapshot"]["checkpoints"]) == tuple(
        row["state_key"] for row in lilbrotr["snapshot"]["checkpoints"]
    )
