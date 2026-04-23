from __future__ import annotations

import json
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
    configure_runtime_relay_targets,
    prepare_runtime_compose_config,
    resolve_runtime_relay_url,
    start_baseline_relay,
)
from tests.system.harness import (
    FaultControlPortPlan,
    LocalToxiproxyRuntime,
    ProxySpec,
    RuntimeAddressPlan,
    ToxicSpec,
    fetch_runtime_rows,
)
from tests.system.pipelines.derivation import test_pipeline as derivation_helpers
from tests.system.pipelines.public_read import test_pipeline as public_read_helpers
from tests.system.services.assertor import test_service as assertor_helpers
from tests.system.services.dvm import test_service as dvm_helpers


if TYPE_CHECKING:
    from pathlib import Path

    from tests.system.harness import ComposeStack, LocalRelayRuntime, SystemArtifactBundle


pytestmark = pytest.mark.system


RESTART_RESUME_ARTIFACT_SERVICES = (
    *BOOTSTRAP_SERVICES,
    "api",
    "dvm",
    "refresher",
    "ranker",
    "assertor",
)
FAILURE_RESUME_ARTIFACT_SERVICES = (
    *BOOTSTRAP_SERVICES,
    "api",
    "refresher",
    "ranker",
    "assertor",
)
_NIP85_PUBKEY_ROWS_SQL = """
    SELECT *
    FROM nip85_pubkey_stats
    ORDER BY pubkey
"""
_API_NIP85_PUBKEY_PATH = "/v1/nip85-pubkey-stats?limit=10&include_total=true"
_ASSERTOR_RESET_TOXIC = ToxicSpec(
    name="restart-resume-assertor-reset",
    toxic_type="reset_peer",
    stream="downstream",
    attributes={"timeout": 0},
)


def _prepare_pipeline_run(
    tmp_path: Path,
    run_name: str,
    *,
    slot: int,
) -> tuple[SystemArtifactBundle, RuntimeAddressPlan, ComposeStack]:
    bundle = create_bundle(tmp_path, run_name)
    plan = RuntimeAddressPlan.create("bigbrotr", tmp_path / "runtime", run_name, slot=slot)
    prepare_runtime_compose_config(plan)
    derivation_helpers._configure_refresher_runtime(plan)
    derivation_helpers._configure_ranker_runtime(plan)
    public_read_helpers._configure_api_runtime(plan)
    public_read_helpers._configure_dvm_runtime(plan)
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)
    return bundle, plan, stack


def _service_logs(stack: ComposeStack, service_name: str) -> str:
    return stack.run("logs", "--no-color", service_name, check=False).stdout


def _nip85_pubkey_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    normalized: list[dict[str, object]] = []
    for row in fetch_runtime_rows(plan, _NIP85_PUBKEY_ROWS_SQL):
        current = dict(row)
        topic_counts = current.get("topic_counts")
        if isinstance(topic_counts, str):
            current["topic_counts"] = json.loads(topic_counts)
        normalized.append(current)
    return tuple(normalized)


def _publish_pubkey_stats_request(
    relay: LocalRelayRuntime,
    *,
    dvm_pubkey: str,
) -> dict[str, object]:
    return dvm_helpers._publish_request_event(
        relay,
        dvm_pubkey=dvm_pubkey,
        read_model="nip85-pubkey-stats",
        param_tags=[["param", "limit", "10"], ["param", "include_total", "true"]],
    )


def _pubkey_stats_replies(
    relay: LocalRelayRuntime,
    *,
    dvm_pubkey: str,
    request_event_id: str,
) -> tuple[Any, ...]:
    return dvm_helpers._reply_events(
        relay.ws_url,
        author=dvm_pubkey,
        request_event_id=request_event_id,
        kind=dvm_helpers._RESULT_KIND,
    )


def _assert_pubkey_read_surface_round(
    *,
    api_response: tuple[int, object],
    dvm_replies: tuple[Any, ...],
    expected_rows: tuple[dict[str, object], ...],
    request_event_id: str,
    request_pubkey: str,
) -> None:
    assert api_response[0] == 200
    api_payload = api_response[1]
    assert isinstance(api_payload, dict)
    assert api_payload["data"] == list(expected_rows)
    assert api_payload["meta"] == {
        "limit": 10,
        "offset": 0,
        "read_model": "nip85-pubkey-stats",
        "total": len(expected_rows),
    }
    assert api_payload["meta"].get("next_cursor") is None
    assert len(dvm_replies) == 1
    dvm_helpers._assert_result_reply(
        dvm_replies[0].event,
        request_event_id=request_event_id,
        request_pubkey=request_pubkey,
        expected_data=list(expected_rows),
        expected_meta={
            "limit": 10,
            "offset": 0,
            "read_model": "nip85-pubkey-stats",
            "total": len(expected_rows),
        },
    )


def _capture_pipeline_artifacts(
    bundle: SystemArtifactBundle,
    stack: ComposeStack,
    *,
    relay: LocalRelayRuntime,
    name: str,
    snapshot: dict[str, object],
    include_dvm: bool,
    toxiproxy: LocalToxiproxyRuntime | None = None,
) -> None:
    for service_name in ("api", "refresher", "ranker", "assertor"):
        bundle.capture_container_logs(f"{name}-{service_name}", _service_logs(stack, service_name))
    if include_dvm:
        bundle.capture_container_logs(f"{name}-dvm", _service_logs(stack, "dvm"))
    bundle.capture_container_logs(f"{name}-relay", relay.logs())
    bundle.capture_relay_events(f"{name}-relay-events", snapshot)
    bundle.capture_db_snapshot(name, snapshot)
    bundle.write_json_artifact(
        category="relay",
        subdir="relay",
        name=f"{name}-relay-inspect",
        payload=relay.inspect(),
    )
    if toxiproxy is not None:
        bundle.capture_container_logs(f"{name}-toxiproxy", toxiproxy.logs())
        bundle.write_json_artifact(
            category="relay",
            subdir="relay",
            name=f"{name}-toxiproxy-inspect",
            payload={
                "inspect": toxiproxy.inspect(),
                "proxies": toxiproxy.client.list_proxies(),
            },
        )


def _start_public_boundaries(
    plan: RuntimeAddressPlan,
    stack: ComposeStack,
    relay: LocalRelayRuntime,
) -> tuple[str, str, str, dict[str, object]]:
    relay_url = resolve_runtime_relay_url(plan, relay)
    configure_runtime_relay_targets(plan, relay)
    derivation_helpers._configure_assertor_runtime(plan, relay_url=relay_url)

    base_url = public_read_helpers._api_base_url(plan)
    expected_dvm_pubkey = public_read_helpers._expected_dvm_pubkey(plan)
    expected_assertor_pubkey = derivation_helpers._expected_assertor_pubkey(plan)

    stack.up("api", build=True)
    stack.up("dvm", build=True)
    stack.wait_until_ready(("api", "dvm"), timeout=180.0)

    startup_snapshot = derivation_helpers._wait_until(
        lambda: {
            "health": public_read_helpers._http_get_json(base_url, "/health"),
            "api": public_read_helpers._http_get_json(base_url, _API_NIP85_PUBKEY_PATH),
            "announcements": dvm_helpers._announcement_events(
                relay.ws_url,
                author=expected_dvm_pubkey,
            ),
            "cursor_rows": dvm_helpers._dvm_cursor_rows(plan),
            "dvm_logs": dvm_helpers._dvm_logs(stack),
        },
        is_ready=lambda current: (
            current["health"][0] == 200
            and current["api"][0] == 200
            and len(current["announcements"]) == 1
            and len(current["cursor_rows"]) == 1
            and "request_subscription_started" in current["dvm_logs"]
        ),
        description="restart-resume public boundary startup",
    )
    announcement_payload = json.loads(str(startup_snapshot["announcements"][0].event["content"]))
    assert "nip85-pubkey-stats" in announcement_payload["read_models"]
    assert startup_snapshot["api"][1]["data"] == []
    return base_url, expected_dvm_pubkey, expected_assertor_pubkey, startup_snapshot


def _run_empty_public_round(
    plan: RuntimeAddressPlan,
    base_url: str,
    relay: LocalRelayRuntime,
    *,
    expected_dvm_pubkey: str,
) -> tuple[dict[str, object], dict[str, object]]:
    initial_request = _publish_pubkey_stats_request(relay, dvm_pubkey=expected_dvm_pubkey)
    empty_snapshot = derivation_helpers._wait_until(
        lambda: {
            "api": public_read_helpers._http_get_json(base_url, _API_NIP85_PUBKEY_PATH),
            "dvm_replies": _pubkey_stats_replies(
                relay,
                dvm_pubkey=expected_dvm_pubkey,
                request_event_id=str(initial_request["event_id"]),
            ),
            "cursor_rows": dvm_helpers._dvm_cursor_rows(plan),
            "db_rows": _nip85_pubkey_rows(plan),
        },
        is_ready=lambda current: (
            len(current["dvm_replies"]) == 1
            and current["cursor_rows"][0]["cursor_id"] == initial_request["event_id"]
        ),
        description="restart-resume empty public read round",
    )
    assert empty_snapshot["db_rows"] == ()
    _assert_pubkey_read_surface_round(
        api_response=empty_snapshot["api"],
        dvm_replies=empty_snapshot["dvm_replies"],
        expected_rows=empty_snapshot["db_rows"],
        request_event_id=str(initial_request["event_id"]),
        request_pubkey=str(initial_request["pubkey"]),
    )
    return initial_request, empty_snapshot


def _complete_refresher_phase(
    plan: RuntimeAddressPlan,
    stack: ComposeStack,
    *,
    base_url: str,
) -> dict[str, object]:
    derivation_helpers._seed_pipeline_events(
        plan,
        relay_url="wss://restart-resume-pipeline.example.com",
    )

    stack.up("refresher", build=True)
    stack.wait_until_ready(("refresher",), timeout=180.0)

    facts_snapshot = derivation_helpers._wait_until(
        lambda: {
            "facts": derivation_helpers._facts_snapshot(plan),
            "api": public_read_helpers._http_get_json(base_url, _API_NIP85_PUBKEY_PATH),
            "db_rows": _nip85_pubkey_rows(plan),
            "cycles": derivation_helpers._service_log_count(
                stack,
                "refresher",
                "refresh_completed",
            ),
        },
        is_ready=lambda current: (
            current["cycles"] >= 1
            and current["facts"]["user_fact"] is not None
            and len(current["db_rows"]) >= 1
            and current["api"][0] == 200
            and current["api"][1]["data"] == list(current["db_rows"])
        ),
        description="restart-resume refresher partial completion",
    )
    stack.run("stop", "refresher")
    stack.wait_until_state("refresher", state="exited", timeout=60.0)
    return facts_snapshot


def _restart_api_with_rows(
    stack: ComposeStack,
    *,
    base_url: str,
    expected_rows: tuple[dict[str, object], ...],
) -> tuple[int, object]:
    stack.run("restart", "api")
    stack.wait_until_ready(("api",), timeout=180.0)
    api_restart_snapshot = derivation_helpers._wait_until(
        lambda: public_read_helpers._http_get_json(base_url, _API_NIP85_PUBKEY_PATH),
        is_ready=lambda current: current[0] == 200 and current[1]["data"] == list(expected_rows),
        description="restart-resume API restart",
    )
    assert api_restart_snapshot[1]["meta"]["read_model"] == "nip85-pubkey-stats"
    return api_restart_snapshot


def _run_facts_public_round(
    plan: RuntimeAddressPlan,
    base_url: str,
    relay: LocalRelayRuntime,
    *,
    expected_dvm_pubkey: str,
    expected_rows: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], dict[str, object]]:
    facts_request = _publish_pubkey_stats_request(relay, dvm_pubkey=expected_dvm_pubkey)
    public_round_snapshot = derivation_helpers._wait_until(
        lambda: {
            "api": public_read_helpers._http_get_json(base_url, _API_NIP85_PUBKEY_PATH),
            "dvm_replies": _pubkey_stats_replies(
                relay,
                dvm_pubkey=expected_dvm_pubkey,
                request_event_id=str(facts_request["event_id"]),
            ),
            "cursor_rows": dvm_helpers._dvm_cursor_rows(plan),
        },
        is_ready=lambda current: (
            len(current["dvm_replies"]) == 1
            and current["cursor_rows"][0]["cursor_id"] == facts_request["event_id"]
        ),
        description="restart-resume facts public read round",
    )
    _assert_pubkey_read_surface_round(
        api_response=public_round_snapshot["api"],
        dvm_replies=public_round_snapshot["dvm_replies"],
        expected_rows=expected_rows,
        request_event_id=str(facts_request["event_id"]),
        request_pubkey=str(facts_request["pubkey"]),
    )
    return facts_request, public_round_snapshot


def _complete_ranker_phase(
    plan: RuntimeAddressPlan,
    stack: ComposeStack,
) -> dict[str, object]:
    stack.up("ranker", build=True)
    stack.wait_until_ready(("ranker",), timeout=180.0)
    score_snapshot = derivation_helpers._wait_until(
        lambda: {
            "scores": derivation_helpers._score_snapshot(plan),
            "cycles": derivation_helpers._service_log_count(
                stack,
                "ranker",
                "ranker_cycle_completed",
            ),
        },
        is_ready=lambda current: (
            current["cycles"] >= 1
            and derivation_helpers._AUTHOR
            in derivation_helpers._score_map(current["scores"]["pubkey"])
            and derivation_helpers._ROOT_EVENT_ID
            in derivation_helpers._score_map(current["scores"]["event"])
            and derivation_helpers._EVENT_ADDRESS
            in derivation_helpers._score_map(current["scores"]["addressable"])
            and derivation_helpers._IDENTIFIER
            in derivation_helpers._score_map(current["scores"]["identifier"])
        ),
        description="restart-resume ranker partial completion",
    )
    stack.run("stop", "ranker")
    stack.wait_until_state("ranker", state="exited", timeout=60.0)
    return score_snapshot


def _publish_assertor_package(
    plan: RuntimeAddressPlan,
    stack: ComposeStack,
    relay: LocalRelayRuntime,
    *,
    expected_assertor_pubkey: str,
    score_snapshot: dict[str, object],
) -> tuple[dict[str, object], list[str], tuple[dict[str, object], ...]]:
    stack.up("assertor", build=True)
    stack.wait_until_ready(("assertor",), timeout=180.0)
    first_publication = derivation_helpers._wait_until(
        lambda: {
            "published": derivation_helpers._captured_assertor_events(relay.ws_url),
            "checkpoints": derivation_helpers._assertor_checkpoints(plan),
            "cycles": derivation_helpers._service_log_count(stack, "assertor", "cycle_completed"),
        },
        is_ready=lambda current: (
            len(current["published"]) >= 6
            and len(current["checkpoints"]) >= 6
            and current["cycles"] >= 1
        ),
        description="restart-resume assertor publication",
    )
    derivation_helpers._assert_published_pipeline_contract(
        events=first_publication["published"],
        expected_pubkey=expected_assertor_pubkey,
        score_snapshot=score_snapshot["scores"],
    )
    first_event_ids = sorted(str(frame.event["id"]) for frame in first_publication["published"])
    first_checkpoints = tuple(first_publication["checkpoints"])
    return first_publication, first_event_ids, first_checkpoints


def _assert_assertor_restart_idempotent(
    plan: RuntimeAddressPlan,
    stack: ComposeStack,
    relay: LocalRelayRuntime,
    *,
    first_event_ids: list[str],
    first_checkpoints: tuple[dict[str, object], ...],
) -> dict[str, object]:
    derivation_helpers._restart_service(stack, "assertor")
    assertor_restart_snapshot = derivation_helpers._wait_until(
        lambda: {
            "published": derivation_helpers._captured_assertor_events(relay.ws_url),
            "checkpoints": derivation_helpers._assertor_checkpoints(plan),
            "cycles": derivation_helpers._service_log_count(stack, "assertor", "cycle_completed"),
        },
        is_ready=lambda current: current["cycles"] >= 1,
        description="restart-resume assertor restart",
    )
    assert sorted(str(frame.event["id"]) for frame in assertor_restart_snapshot["published"]) == (
        first_event_ids
    )
    assert tuple(assertor_restart_snapshot["checkpoints"]) == first_checkpoints
    return assertor_restart_snapshot


def _restart_dvm_and_repeat_round(
    plan: RuntimeAddressPlan,
    stack: ComposeStack,
    relay: LocalRelayRuntime,
    *,
    expected_dvm_pubkey: str,
    prior_request: dict[str, object],
    expected_rows: tuple[dict[str, object], ...],
    api_response: tuple[int, object],
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    dvm_helpers._restart_dvm(stack)
    dvm_restart_snapshot = derivation_helpers._wait_until(
        lambda: {
            "old_replies": _pubkey_stats_replies(
                relay,
                dvm_pubkey=expected_dvm_pubkey,
                request_event_id=str(prior_request["event_id"]),
            ),
            "cursor_rows": dvm_helpers._dvm_cursor_rows(plan),
            "logs": dvm_helpers._dvm_logs(stack),
        },
        is_ready=lambda current: (
            len(current["old_replies"]) == 1
            and len(current["cursor_rows"]) == 1
            and current["cursor_rows"][0]["cursor_id"] == prior_request["event_id"]
            and "request_cursor_restored" in current["logs"]
        ),
        description="restart-resume DVM cursor restore",
    )

    repeated_request = _publish_pubkey_stats_request(relay, dvm_pubkey=expected_dvm_pubkey)
    repeated_round = derivation_helpers._wait_until(
        lambda: {
            "replies": _pubkey_stats_replies(
                relay,
                dvm_pubkey=expected_dvm_pubkey,
                request_event_id=str(repeated_request["event_id"]),
            ),
            "cursor_rows": dvm_helpers._dvm_cursor_rows(plan),
        },
        is_ready=lambda current: (
            len(current["replies"]) == 1
            and len(current["cursor_rows"]) == 1
            and current["cursor_rows"][0]["cursor_id"] == repeated_request["event_id"]
        ),
        description="restart-resume repeated DVM request",
    )
    _assert_pubkey_read_surface_round(
        api_response=api_response,
        dvm_replies=repeated_round["replies"],
        expected_rows=expected_rows,
        request_event_id=str(repeated_request["event_id"]),
        request_pubkey=str(repeated_request["pubkey"]),
    )
    repeated_payload = json.loads(str(repeated_round["replies"][0].event["content"]))
    restored_payload = json.loads(str(dvm_restart_snapshot["old_replies"][0].event["content"]))
    assert repeated_payload == restored_payload
    assert repeated_request["event_id"] != prior_request["event_id"]
    return dvm_restart_snapshot, repeated_request, repeated_round


def _start_assertor_proxy_path(
    plan: RuntimeAddressPlan,
    tmp_path: Path,
    relay: LocalRelayRuntime,
) -> LocalToxiproxyRuntime:
    port_plan = FaultControlPortPlan.for_slot(58)
    proxy_port = port_plan.proxy_port(0)
    toxiproxy = LocalToxiproxyRuntime(
        role="restart-resume-assertor",
        runtime_dir=tmp_path / "toxiproxy-runtime",
        network_name=plan.data_network_name,
        network_aliases=("restart-resume-toxiproxy",),
        port_plan=port_plan,
        exposed_proxy_ports=(proxy_port,),
    )
    toxiproxy.start()
    toxiproxy.wait_until_ready()
    toxiproxy.client.create_proxy(
        ProxySpec(
            name="restart-resume-assertor-upstream",
            upstream_host=relay.container_name,
            upstream_port=8080,
            listen_port=proxy_port,
        )
    )
    relay_url = assertor_helpers._toxiproxy_internal_ws_url(plan, toxiproxy, proxy_port)
    derivation_helpers._configure_assertor_runtime(plan, relay_url=relay_url)
    config_path = plan.runtime_root / "config" / "services" / "assertor.yaml"
    payload = yaml.safe_load(config_path.read_text())
    assert isinstance(payload, dict)
    payload["interval"] = 60.0
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False))
    return toxiproxy


def _wait_provider_only_publication(
    plan: RuntimeAddressPlan,
    stack: ComposeStack,
    relay: LocalRelayRuntime,
    *,
    base_url: str,
) -> tuple[dict[str, object], list[str], tuple[dict[str, object], ...]]:
    stack.up("api", build=True)
    stack.up("assertor", build=True)
    stack.wait_until_ready(("api", "assertor"), timeout=180.0)

    provider_only_snapshot = derivation_helpers._wait_until(
        lambda: {
            "api": public_read_helpers._http_get_json(base_url, _API_NIP85_PUBKEY_PATH),
            "published": derivation_helpers._captured_assertor_events(relay.ws_url),
            "checkpoints": derivation_helpers._assertor_checkpoints(plan),
            "cycles": derivation_helpers._service_log_count(stack, "assertor", "cycle_completed"),
        },
        is_ready=lambda current: (
            current["api"][0] == 200
            and current["api"][1]["data"] == []
            and len(current["published"]) == 2
            and len(current["checkpoints"]) == 2
            and current["cycles"] >= 1
        ),
        description="partial-completion initial provider-only publication",
    )
    provider_only_ids = sorted(
        str(frame.event["id"]) for frame in provider_only_snapshot["published"]
    )
    provider_only_checkpoints = tuple(provider_only_snapshot["checkpoints"])
    return provider_only_snapshot, provider_only_ids, provider_only_checkpoints


def _complete_public_fact_and_score_pipeline(
    plan: RuntimeAddressPlan,
    stack: ComposeStack,
    *,
    base_url: str,
) -> tuple[dict[str, object], dict[str, object]]:
    derivation_helpers._seed_pipeline_events(
        plan,
        relay_url="wss://partial-completion-pipeline.example.com",
    )

    stack.up("refresher", build=True)
    stack.wait_until_ready(("refresher",), timeout=180.0)
    facts_snapshot = derivation_helpers._wait_until(
        lambda: {
            "api": public_read_helpers._http_get_json(base_url, _API_NIP85_PUBKEY_PATH),
            "db_rows": _nip85_pubkey_rows(plan),
            "facts": derivation_helpers._facts_snapshot(plan),
            "cycles": derivation_helpers._service_log_count(
                stack,
                "refresher",
                "refresh_completed",
            ),
        },
        is_ready=lambda current: (
            current["cycles"] >= 1
            and len(current["db_rows"]) >= 1
            and current["api"][0] == 200
            and current["api"][1]["data"] == list(current["db_rows"])
            and current["facts"]["user_fact"] is not None
        ),
        description="partial-completion facts become publicly readable",
    )
    stack.run("stop", "refresher")
    stack.wait_until_state("refresher", state="exited", timeout=60.0)
    score_snapshot = _complete_ranker_phase(plan, stack)
    return facts_snapshot, score_snapshot


def _assert_failed_publish_cycle(
    plan: RuntimeAddressPlan,
    stack: ComposeStack,
    relay: LocalRelayRuntime,
    *,
    base_url: str,
    expected_rows: tuple[dict[str, object], ...],
    provider_only_ids: list[str],
    provider_only_checkpoints: tuple[dict[str, object], ...],
) -> dict[str, object]:
    failed_snapshot = derivation_helpers._wait_until(
        lambda: {
            "api": public_read_helpers._http_get_json(base_url, _API_NIP85_PUBKEY_PATH),
            "published": derivation_helpers._captured_assertor_events(relay.ws_url),
            "checkpoints": derivation_helpers._assertor_checkpoints(plan),
            "logs": assertor_helpers._assertor_logs(stack),
            "cycles": derivation_helpers._service_log_count(stack, "assertor", "cycle_completed"),
        },
        is_ready=lambda current: (
            current["cycles"] >= 2
            and current["api"][1]["data"] == list(expected_rows)
            and "user_assertion_failed" in current["logs"]
        ),
        description="partial-completion assertor failure cycle",
        timeout=240.0,
    )
    assert (
        sorted(str(frame.event["id"]) for frame in failed_snapshot["published"])
        == provider_only_ids
    )
    assert tuple(failed_snapshot["checkpoints"]) == provider_only_checkpoints
    assert "event_assertion_failed" in failed_snapshot["logs"]
    assert "addressable_assertion_failed" in failed_snapshot["logs"]
    assert "identifier_assertion_failed" in failed_snapshot["logs"]
    return failed_snapshot


def _recover_assertor_publication(
    plan: RuntimeAddressPlan,
    stack: ComposeStack,
    relay: LocalRelayRuntime,
    toxiproxy: LocalToxiproxyRuntime,
    *,
    expected_assertor_pubkey: str,
    score_snapshot: dict[str, object],
) -> dict[str, object]:
    toxiproxy.client.remove_toxic("restart-resume-assertor-upstream", _ASSERTOR_RESET_TOXIC.name)
    stack.run("restart", "assertor")
    stack.wait_until_ready(("assertor",), timeout=180.0)
    recovered_snapshot = derivation_helpers._wait_until(
        lambda: {
            "published": derivation_helpers._captured_assertor_events(relay.ws_url),
            "checkpoints": derivation_helpers._assertor_checkpoints(plan),
            "cycles": derivation_helpers._service_log_count(stack, "assertor", "cycle_completed"),
        },
        is_ready=lambda current: (
            len(current["published"]) >= 6
            and len(current["checkpoints"]) >= 6
            and current["cycles"] >= 1
        ),
        description="partial-completion recovered assertor publication",
    )
    derivation_helpers._assert_published_pipeline_contract(
        events=recovered_snapshot["published"],
        expected_pubkey=expected_assertor_pubkey,
        score_snapshot=score_snapshot["scores"],
    )
    return recovered_snapshot


@pytest.mark.timeout(1800)
def test_restart_resume_pipeline_keeps_shared_state_honest_across_public_boundaries(
    tmp_path: Path,
) -> None:
    bundle, plan, stack = _prepare_pipeline_run(
        tmp_path,
        "restart-resume-pipeline-contract",
        slot=56,
    )
    relay = None

    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        relay = start_baseline_relay(plan)
        (
            base_url,
            expected_dvm_pubkey,
            expected_assertor_pubkey,
            startup_snapshot,
        ) = _start_public_boundaries(plan, stack, relay)
        initial_request, empty_snapshot = _run_empty_public_round(
            plan,
            base_url,
            relay,
            expected_dvm_pubkey=expected_dvm_pubkey,
        )
        facts_snapshot = _complete_refresher_phase(plan, stack, base_url=base_url)
        api_restart_snapshot = _restart_api_with_rows(
            stack,
            base_url=base_url,
            expected_rows=facts_snapshot["db_rows"],
        )
        facts_request, public_round_snapshot = _run_facts_public_round(
            plan,
            base_url,
            relay,
            expected_dvm_pubkey=expected_dvm_pubkey,
            expected_rows=facts_snapshot["db_rows"],
        )
        score_snapshot = _complete_ranker_phase(plan, stack)
        first_publication, first_event_ids, first_checkpoints = _publish_assertor_package(
            plan,
            stack,
            relay,
            expected_assertor_pubkey=expected_assertor_pubkey,
            score_snapshot=score_snapshot,
        )
        assertor_restart_snapshot = _assert_assertor_restart_idempotent(
            plan,
            stack,
            relay,
            first_event_ids=first_event_ids,
            first_checkpoints=first_checkpoints,
        )
        dvm_restart_snapshot, repeated_request, repeated_round = _restart_dvm_and_repeat_round(
            plan,
            stack,
            relay,
            expected_dvm_pubkey=expected_dvm_pubkey,
            prior_request=facts_request,
            expected_rows=facts_snapshot["db_rows"],
            api_response=public_round_snapshot["api"],
        )

        _capture_pipeline_artifacts(
            bundle,
            stack,
            relay=relay,
            name="restart-resume-pipeline-contract",
            snapshot={
                "startup": startup_snapshot,
                "empty_round": {
                    "request": initial_request,
                    "snapshot": empty_snapshot,
                },
                "facts": facts_snapshot,
                "api_restart": api_restart_snapshot,
                "facts_round": {
                    "request": facts_request,
                    "snapshot": public_round_snapshot,
                },
                "scores": score_snapshot,
                "first_publication": first_publication,
                "assertor_restart": assertor_restart_snapshot,
                "dvm_restart": dvm_restart_snapshot,
                "repeated_round": {
                    "request": repeated_request,
                    "snapshot": repeated_round,
                },
            },
            include_dvm=True,
        )
    finally:
        capture_stack_artifacts(bundle, stack, services=RESTART_RESUME_ARTIFACT_SERVICES)
        if relay is not None:
            relay.stop()
        stack.down()


@pytest.mark.timeout(1800)
def test_partial_completion_pipeline_defers_publish_state_until_assertor_recovers(
    tmp_path: Path,
) -> None:
    bundle, plan, stack = _prepare_pipeline_run(
        tmp_path,
        "partial-completion-failure-contract",
        slot=57,
    )
    relay = None
    toxiproxy = None

    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        relay = start_baseline_relay(plan)
        toxiproxy = _start_assertor_proxy_path(plan, tmp_path, relay)
        base_url = public_read_helpers._api_base_url(plan)
        expected_assertor_pubkey = derivation_helpers._expected_assertor_pubkey(plan)
        (
            provider_only_snapshot,
            provider_only_ids,
            provider_only_checkpoints,
        ) = _wait_provider_only_publication(
            plan,
            stack,
            relay,
            base_url=base_url,
        )
        toxiproxy.client.add_toxic("restart-resume-assertor-upstream", _ASSERTOR_RESET_TOXIC)
        facts_snapshot, score_snapshot = _complete_public_fact_and_score_pipeline(
            plan,
            stack,
            base_url=base_url,
        )
        failed_snapshot = _assert_failed_publish_cycle(
            plan,
            stack,
            relay,
            base_url=base_url,
            expected_rows=facts_snapshot["db_rows"],
            provider_only_ids=provider_only_ids,
            provider_only_checkpoints=provider_only_checkpoints,
        )
        recovered_snapshot = _recover_assertor_publication(
            plan,
            stack,
            relay,
            toxiproxy,
            expected_assertor_pubkey=expected_assertor_pubkey,
            score_snapshot=score_snapshot,
        )

        _capture_pipeline_artifacts(
            bundle,
            stack,
            relay=relay,
            toxiproxy=toxiproxy,
            name="partial-completion-failure-contract",
            snapshot={
                "provider_only": provider_only_snapshot,
                "facts": facts_snapshot,
                "scores": score_snapshot,
                "failed": failed_snapshot,
                "recovered": recovered_snapshot,
            },
            include_dvm=False,
        )
    finally:
        capture_stack_artifacts(bundle, stack, services=FAILURE_RESUME_ARTIFACT_SERVICES)
        if toxiproxy is not None:
            toxiproxy.stop()
        if relay is not None:
            relay.stop()
        stack.down()
