from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

import pytest
import yaml
from nostr_sdk import Keys

from bigbrotr.core.brotr import Brotr
from bigbrotr.models.constants import EventKind
from tests.integration.harness.builders import (
    build_event_address,
    build_event_observation,
)
from tests.system.deployments.baseline import (
    capture_stack_artifacts,
    create_bundle,
    create_stack,
    record_runtime_plan,
)
from tests.system.deployments.runtime_overrides import (
    BOOTSTRAP_SERVICES,
    prepare_runtime_compose_config,
    resolve_runtime_relay_url,
    start_baseline_relay,
)
from tests.system.harness import (
    RuntimeAddressPlan,
    RuntimeDatabaseTarget,
    fetch_runtime_rows,
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


DERIVATION_PIPELINE_ARTIFACT_SERVICES = (*BOOTSTRAP_SERVICES, "refresher", "ranker", "assertor")
_AUTHOR = "a1" * 32
_FOLLOWER_B = "b2" * 32
_FOLLOWER_C = "c3" * 32
_ROOT_EVENT_ID = "d4" * 32
_EVENT_ADDRESS = build_event_address(30023, _AUTHOR, "article")
_IDENTIFIER = "isbn:9780140328721"
_PIPELINE_RELAY_HINT = "wss://relay.derivation.example.com"
_ASSERTOR_CAPTURE_KINDS = [
    int(EventKind.SET_METADATA),
    int(EventKind.NIP85_TRUSTED_PROVIDER_LIST),
    int(EventKind.NIP85_USER_ASSERTION),
    int(EventKind.NIP85_EVENT_ASSERTION),
    int(EventKind.NIP85_ADDRESSABLE_ASSERTION),
    int(EventKind.NIP85_IDENTIFIER_ASSERTION),
]
_CONTACT_LIST_ROWS_SQL = """
    SELECT
        follower_pubkey,
        source_event_id,
        follow_count
    FROM contact_lists_current
    ORDER BY follower_pubkey
"""
_CONTACT_EDGE_ROWS_SQL = """
    SELECT follower_pubkey, followed_pubkey
    FROM contact_list_edges_current
    ORDER BY follower_pubkey, followed_pubkey
"""
_USER_FACT_SQL = """
    SELECT follower_count, following_count, post_count
    FROM nip85_pubkey_stats
    WHERE pubkey = $1
"""
_EVENT_FACT_SQL = """
    SELECT comment_count, reaction_count
    FROM nip85_event_stats
    WHERE event_id = $1
"""
_ADDRESSABLE_FACT_SQL = """
    SELECT comment_count
    FROM nip85_addressable_stats
    WHERE event_address = $1
"""
_IDENTIFIER_FACT_SQL = """
    SELECT comment_count, reaction_count, k_tags
    FROM nip85_identifier_stats
    WHERE identifier = $1
"""
_ASSERTOR_CHECKPOINT_ROWS_SQL = """
    SELECT
        state_key,
        state_value->>'hash' AS hash,
        (state_value->>'timestamp')::bigint AS timestamp
    FROM service_state
    WHERE owner = 'assertor'
      AND state_type = 'checkpoint'
    ORDER BY state_key
"""
_SCORE_ROWS_SQL = {
    "pubkey": """
        SELECT pubkey AS subject_id, score
        FROM pubkey_score
        WHERE algorithm_id = $1
        ORDER BY pubkey
    """,
    "event": """
        SELECT event_id AS subject_id, score
        FROM event_score
        WHERE algorithm_id = $1
        ORDER BY event_id
    """,
    "addressable": """
        SELECT event_address AS subject_id, score
        FROM addressable_score
        WHERE algorithm_id = $1
        ORDER BY event_address
    """,
    "identifier": """
        SELECT identifier AS subject_id, score
        FROM identifier_score
        WHERE algorithm_id = $1
        ORDER BY identifier
    """,
}


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


async def _async_seed_pipeline_events(plan: RuntimeAddressPlan, *, relay_url: str) -> None:
    brotr = _runtime_brotr(plan)
    async with brotr:
        await brotr.insert_event_observation(
            [
                build_event_observation(
                    "10" * 32,
                    relay_url,
                    kind=3,
                    pubkey=_AUTHOR,
                    created_at=100,
                    tags=[["p", _FOLLOWER_B], ["p", _FOLLOWER_C]],
                ),
                build_event_observation(
                    "11" * 32,
                    relay_url,
                    kind=3,
                    pubkey=_FOLLOWER_B,
                    created_at=101,
                    tags=[["p", _AUTHOR]],
                ),
                build_event_observation(
                    "12" * 32,
                    relay_url,
                    kind=3,
                    pubkey=_FOLLOWER_C,
                    created_at=102,
                    tags=[["p", _AUTHOR]],
                ),
                build_event_observation(
                    _ROOT_EVENT_ID,
                    relay_url,
                    kind=1,
                    pubkey=_AUTHOR,
                    created_at=200,
                    tags=[["t", "nostr"], ["t", "books"]],
                    content="Root note",
                ),
                build_event_observation(
                    "21" * 32,
                    relay_url,
                    kind=1,
                    pubkey=_FOLLOWER_B,
                    created_at=201,
                    tags=[["e", _ROOT_EVENT_ID], ["p", _AUTHOR]],
                    content="Reply",
                ),
                build_event_observation(
                    "22" * 32,
                    relay_url,
                    kind=7,
                    pubkey=_FOLLOWER_C,
                    created_at=202,
                    tags=[["e", _ROOT_EVENT_ID], ["p", _AUTHOR]],
                    content="+",
                ),
                build_event_observation(
                    "23" * 32,
                    relay_url,
                    kind=30023,
                    pubkey=_AUTHOR,
                    created_at=203,
                    tags=[["d", "article"], ["t", "nostr"]],
                    content="Addressable article",
                ),
                build_event_observation(
                    "24" * 32,
                    relay_url,
                    kind=1,
                    pubkey=_FOLLOWER_B,
                    created_at=204,
                    tags=[["a", _EVENT_ADDRESS], ["p", _AUTHOR]],
                    content="Addressable comment",
                ),
                build_event_observation(
                    "25" * 32,
                    relay_url,
                    kind=1,
                    pubkey=_FOLLOWER_B,
                    created_at=205,
                    tags=[["i", _IDENTIFIER], ["k", "book"], ["k", "isbn"]],
                    content="Identifier comment",
                ),
                build_event_observation(
                    "26" * 32,
                    relay_url,
                    kind=7,
                    pubkey=_FOLLOWER_C,
                    created_at=206,
                    tags=[["i", _IDENTIFIER], ["k", "isbn"]],
                    content="+",
                ),
            ],
            cascade=True,
        )


def _seed_pipeline_events(plan: RuntimeAddressPlan, *, relay_url: str) -> None:
    asyncio.run(_async_seed_pipeline_events(plan, relay_url=relay_url))


def _configure_refresher_runtime(plan: RuntimeAddressPlan) -> None:
    config_path = plan.runtime_root / "config" / "services" / "refresher.yaml"
    payload = yaml.safe_load(config_path.read_text())
    assert isinstance(payload, dict)

    payload["interval"] = 3600.0
    payload["processing"] = {
        "max_source_window": None,
        "max_duration": None,
        "max_targets_per_cycle": None,
        "continue_on_target_error": False,
    }
    payload["current"] = {"targets": ["replaceable_event_current", "addressable_event_current"]}
    payload["analytics"] = {
        "targets": [
            "pubkey_kind_stats",
            "pubkey_relay_stats",
            "relay_kind_stats",
            "pubkey_stats",
            "kind_stats",
            "relay_stats",
            "contact_lists_current",
            "contact_list_edges_current",
            "nip85_pubkey_stats",
            "nip85_event_stats",
            "nip85_addressable_stats",
            "nip85_identifier_stats",
        ]
    }
    payload["periodic"] = {
        "rolling_windows": False,
        "relay_stats_document": False,
        "nip85_followers": True,
    }
    payload["cleanup"] = {"enabled": True}

    config_path.write_text(yaml.safe_dump(payload, sort_keys=False))


def _configure_ranker_runtime(plan: RuntimeAddressPlan) -> None:
    config_path = plan.runtime_root / "config" / "services" / "ranker.yaml"
    payload = yaml.safe_load(config_path.read_text())
    assert isinstance(payload, dict)

    payload["interval"] = 3600.0
    payload["algorithm_id"] = "global-pagerank"
    payload["processing"] = {"max_duration": None}
    payload["sync"] = {
        "batch_size": 10,
        "max_batches": None,
        "max_followers_per_cycle": None,
    }
    payload["facts_stage"] = {
        "batch_size": 10,
        "max_event_rows": None,
        "max_addressable_rows": None,
        "max_identifier_rows": None,
    }
    payload["export"] = {
        "batch_size": 10,
        "max_batches_per_subject": None,
    }
    payload["cleanup"] = {"rank_runs_retention": 100}

    config_path.write_text(yaml.safe_dump(payload, sort_keys=False))


def _configure_assertor_runtime(plan: RuntimeAddressPlan, *, relay_url: str) -> None:
    config_path = plan.runtime_root / "config" / "services" / "assertor.yaml"
    payload = yaml.safe_load(config_path.read_text())
    assert isinstance(payload, dict)

    payload["interval"] = 3600.0
    payload["algorithm_id"] = "global-pagerank"
    payload["selection"] = {
        "batch_size": 100,
        "min_events": 1,
        "top_topics": 5,
        "kinds": [30382, 30383, 30384, 30385],
    }
    payload["cleanup"] = {"remove_stale_checkpoints": True}
    payload["publishing"] = {
        "relays": [relay_url],
        "allow_insecure": False,
    }
    payload["provider_profile"] = {
        "enabled": True,
        "kind0_content": {
            "name": "BigBrotr Global PageRank",
            "about": "NIP-85 trusted assertion provider",
            "website": "https://bigbrotr.com",
            "extra_fields": {"software": "bigbrotr"},
        },
    }
    payload["trusted_provider_list"] = {
        "enabled": True,
        "relay_hint": _PIPELINE_RELAY_HINT,
        "tag_names": ["rank"],
        "content": "",
    }

    config_path.write_text(yaml.safe_dump(payload, sort_keys=False))


def _prepare_derivation_run(
    tmp_path: Path,
    run_name: str,
    *,
    slot: int,
) -> tuple[SystemArtifactBundle, RuntimeAddressPlan, ComposeStack]:
    bundle = create_bundle(tmp_path, run_name)
    plan = RuntimeAddressPlan.create("bigbrotr", tmp_path / "runtime", run_name, slot=slot)
    prepare_runtime_compose_config(plan)
    _configure_refresher_runtime(plan)
    _configure_ranker_runtime(plan)
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)
    return bundle, plan, stack


def _service_logs(stack: ComposeStack, service_name: str) -> str:
    return stack.run("logs", "--no-color", service_name, check=False).stdout


def _service_log_count(stack: ComposeStack, service_name: str, needle: str) -> int:
    return _service_logs(stack, service_name).count(needle)


def _restart_service(stack: ComposeStack, service_name: str) -> None:
    stack.run("stop", service_name)
    stack.wait_until_state(service_name, state="exited", timeout=120.0)
    stack.run("rm", "-f", service_name)
    stack.up(service_name)
    stack.wait_until_ready((service_name,), timeout=180.0)


def _contact_list_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _CONTACT_LIST_ROWS_SQL)


def _contact_edge_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _CONTACT_EDGE_ROWS_SQL)


def _facts_snapshot(plan: RuntimeAddressPlan) -> dict[str, object]:
    user_rows = fetch_runtime_rows(plan, _USER_FACT_SQL, _AUTHOR)
    event_rows = fetch_runtime_rows(plan, _EVENT_FACT_SQL, _ROOT_EVENT_ID)
    addressable_rows = fetch_runtime_rows(plan, _ADDRESSABLE_FACT_SQL, _EVENT_ADDRESS)
    identifier_rows = fetch_runtime_rows(plan, _IDENTIFIER_FACT_SQL, _IDENTIFIER)
    return {
        "contact_lists": _contact_list_rows(plan),
        "contact_edges": _contact_edge_rows(plan),
        "user_fact": user_rows[0] if user_rows else None,
        "event_fact": event_rows[0] if event_rows else None,
        "addressable_fact": addressable_rows[0] if addressable_rows else None,
        "identifier_fact": identifier_rows[0] if identifier_rows else None,
    }


def _score_rows(plan: RuntimeAddressPlan, subject_type: str) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _SCORE_ROWS_SQL[subject_type], "global-pagerank")


def _score_snapshot(plan: RuntimeAddressPlan) -> dict[str, tuple[dict[str, object], ...]]:
    return {
        "pubkey": _score_rows(plan, "pubkey"),
        "event": _score_rows(plan, "event"),
        "addressable": _score_rows(plan, "addressable"),
        "identifier": _score_rows(plan, "identifier"),
    }


def _score_map(rows: tuple[dict[str, object], ...]) -> dict[str, int]:
    return {str(row["subject_id"]): int(float(row["score"])) for row in rows}


def _assertor_checkpoints(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _ASSERTOR_CHECKPOINT_ROWS_SQL)


def _captured_assertor_events(ws_url: str) -> tuple[RelayEventFrame, ...]:
    return asyncio.run(
        query_events(
            ws_url,
            filters={"kinds": _ASSERTOR_CAPTURE_KINDS},
            subscription_id="derivation-pipeline-capture",
        )
    )


def _expected_assertor_pubkey(plan: RuntimeAddressPlan) -> str:
    private_key = build_test_env_values(plan.profile, plan.project_name)[
        "NOSTR_PRIVATE_KEY_ASSERTOR"
    ]
    return Keys.parse(private_key).public_key().to_hex()


def _tag_values(event: dict[str, object], tag_name: str) -> list[str]:
    values: list[str] = []
    raw_tags = event.get("tags")
    if not isinstance(raw_tags, list):
        return values
    for tag in raw_tags:
        if isinstance(tag, list) and len(tag) > 1 and tag[0] == tag_name:
            values.append(str(tag[1]))
    return values


def _find_event_by_kind_and_d(
    events: tuple[RelayEventFrame, ...],
    *,
    kind: int,
    d_value: str,
) -> dict[str, object]:
    for frame in events:
        event = frame.event
        if int(event["kind"]) != kind:
            continue
        if _tag_values(event, "d") == [d_value]:
            return event
    raise AssertionError(f"missing published event for kind={kind} subject={d_value}")


def _assert_published_pipeline_contract(
    *,
    events: tuple[RelayEventFrame, ...],
    expected_pubkey: str,
    score_snapshot: dict[str, tuple[dict[str, object], ...]],
) -> None:
    events_by_kind: dict[int, list[dict[str, object]]] = {}
    for frame in events:
        events_by_kind.setdefault(int(frame.event["kind"]), []).append(frame.event)

    metadata_events = events_by_kind.get(int(EventKind.SET_METADATA), [])
    trusted_provider_events = events_by_kind.get(int(EventKind.NIP85_TRUSTED_PROVIDER_LIST), [])
    assert len(metadata_events) == 1
    assert len(trusted_provider_events) == 1
    assert all(str(frame.event["pubkey"]) == expected_pubkey for frame in events)

    metadata_content = json.loads(str(metadata_events[0]["content"]))
    assert metadata_content["name"] == "BigBrotr Global PageRank"
    assert metadata_content["about"] == "NIP-85 trusted assertion provider"
    assert metadata_content["website"] == "https://bigbrotr.com"
    assert metadata_content["software"] == "bigbrotr"
    assert metadata_content["algorithm_id"] == "global-pagerank"
    assert trusted_provider_events[0]["tags"] == [
        ["30382:rank", expected_pubkey, _PIPELINE_RELAY_HINT],
        ["30383:rank", expected_pubkey, _PIPELINE_RELAY_HINT],
        ["30384:rank", expected_pubkey, _PIPELINE_RELAY_HINT],
        ["30385:rank", expected_pubkey, _PIPELINE_RELAY_HINT],
    ]

    pubkey_scores = _score_map(score_snapshot["pubkey"])
    event_scores = _score_map(score_snapshot["event"])
    addressable_scores = _score_map(score_snapshot["addressable"])
    identifier_scores = _score_map(score_snapshot["identifier"])

    user_event = _find_event_by_kind_and_d(
        events,
        kind=int(EventKind.NIP85_USER_ASSERTION),
        d_value=_AUTHOR,
    )
    event_event = _find_event_by_kind_and_d(
        events,
        kind=int(EventKind.NIP85_EVENT_ASSERTION),
        d_value=_ROOT_EVENT_ID,
    )
    addressable_event = _find_event_by_kind_and_d(
        events,
        kind=int(EventKind.NIP85_ADDRESSABLE_ASSERTION),
        d_value=_EVENT_ADDRESS,
    )
    identifier_event = _find_event_by_kind_and_d(
        events,
        kind=int(EventKind.NIP85_IDENTIFIER_ASSERTION),
        d_value=_IDENTIFIER,
    )

    assert _tag_values(user_event, "rank") == [str(pubkey_scores[_AUTHOR])]
    assert _tag_values(event_event, "rank") == [str(event_scores[_ROOT_EVENT_ID])]
    assert _tag_values(event_event, "p") == [_AUTHOR]
    assert _tag_values(addressable_event, "a") == [_EVENT_ADDRESS]
    assert _tag_values(addressable_event, "p") == [_AUTHOR]
    assert _tag_values(addressable_event, "rank") == [str(addressable_scores[_EVENT_ADDRESS])]
    assert _tag_values(identifier_event, "d") == [_IDENTIFIER]
    assert _tag_values(identifier_event, "i") == [_IDENTIFIER]
    assert _tag_values(identifier_event, "rank") == [str(identifier_scores[_IDENTIFIER])]
    assert sorted(_tag_values(identifier_event, "k")) == ["book", "isbn"]


def _wait_until(
    fetch_snapshot: Any,
    *,
    is_ready: Any,
    description: str,
    timeout: float = 180.0,
    poll_interval: float = 1.0,
) -> Any:
    deadline = time.monotonic() + timeout
    last_snapshot = fetch_snapshot()
    while time.monotonic() < deadline:
        last_snapshot = fetch_snapshot()
        if is_ready(last_snapshot):
            return last_snapshot
        time.sleep(poll_interval)
    raise RuntimeError(f"Timed out waiting for {description}: {last_snapshot!r}")


def _capture_derivation_artifacts(
    bundle: SystemArtifactBundle,
    stack: ComposeStack,
    *,
    relay: LocalRelayRuntime | None,
    name: str,
    snapshot: dict[str, object] | None = None,
) -> None:
    for service_name in ("refresher", "ranker", "assertor"):
        bundle.capture_container_logs(
            f"{name}-{service_name}",
            _service_logs(stack, service_name),
        )
    if relay is not None:
        bundle.capture_container_logs(f"{name}-relay", relay.logs())
        bundle.write_json_artifact(
            category="relay",
            subdir="relay",
            name=f"{name}-relay-inspect",
            payload=relay.inspect(),
        )
    if snapshot is not None:
        bundle.capture_db_snapshot(name, snapshot)


@pytest.mark.timeout(1500)
def test_derivation_pipeline_publishes_ranked_provider_package_without_restart_drift(
    tmp_path: Path,
) -> None:
    bundle, plan, stack = _prepare_derivation_run(
        tmp_path,
        "derivation-pipeline-contract",
        slot=54,
    )
    relay = None
    first_snapshot: dict[str, object] | None = None
    restart_snapshot: dict[str, object] | None = None

    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        relay = start_baseline_relay(plan)
        relay_url = resolve_runtime_relay_url(plan, relay)
        _configure_assertor_runtime(plan, relay_url=relay_url)
        _seed_pipeline_events(plan, relay_url="wss://derivation-pipeline.example.com")

        stack.up("refresher", build=True)
        stack.wait_until_ready(("refresher",), timeout=180.0)

        refresher_snapshot = _wait_until(
            lambda: {
                "facts": _facts_snapshot(plan),
                "cycle_count": _service_log_count(stack, "refresher", "refresh_completed"),
            },
            is_ready=lambda current: (
                len(current["facts"]["contact_lists"]) == 3
                and len(current["facts"]["contact_edges"]) == 4
                and current["facts"]["user_fact"] is not None
                and int(current["facts"]["user_fact"]["follower_count"]) == 2
                and int(current["facts"]["user_fact"]["following_count"]) == 2
                and int(current["facts"]["user_fact"]["post_count"]) >= 1
                and current["facts"]["event_fact"] == {"comment_count": 1, "reaction_count": 1}
                and current["facts"]["addressable_fact"] == {"comment_count": 1}
                and current["facts"]["identifier_fact"] is not None
                and int(current["facts"]["identifier_fact"]["comment_count"]) == 1
                and int(current["facts"]["identifier_fact"]["reaction_count"]) == 1
                and current["facts"]["identifier_fact"]["k_tags"] == ["book", "isbn"]
                and current["cycle_count"] >= 1
            ),
            description="derivation refresher outputs",
        )

        stack.up("ranker", build=True)
        stack.wait_until_ready(("ranker",), timeout=180.0)

        _wait_until(
            lambda: {
                "scores": _score_snapshot(plan),
                "cycle_count": _service_log_count(stack, "ranker", "ranker_cycle_completed"),
            },
            is_ready=lambda current: (
                _AUTHOR in _score_map(current["scores"]["pubkey"])
                and _ROOT_EVENT_ID in _score_map(current["scores"]["event"])
                and _EVENT_ADDRESS in _score_map(current["scores"]["addressable"])
                and _IDENTIFIER in _score_map(current["scores"]["identifier"])
                and current["cycle_count"] >= 1
            ),
            description="derivation ranker exports",
        )

        stack.up("assertor", build=True)
        stack.wait_until_ready(("assertor",), timeout=180.0)

        first_snapshot = _wait_until(
            lambda: {
                "facts": refresher_snapshot["facts"],
                "scores": _score_snapshot(plan),
                "published": _captured_assertor_events(relay.ws_url),
                "checkpoints": _assertor_checkpoints(plan),
                "refresher_cycles": _service_log_count(stack, "refresher", "refresh_completed"),
                "ranker_cycles": _service_log_count(stack, "ranker", "ranker_cycle_completed"),
                "assertor_cycles": _service_log_count(stack, "assertor", "cycle_completed"),
            },
            is_ready=lambda current: (
                len(current["published"]) >= 6
                and len(current["checkpoints"]) >= 6
                and current["assertor_cycles"] >= 1
            ),
            description="derivation assertor publication",
        )
        _assert_published_pipeline_contract(
            events=first_snapshot["published"],
            expected_pubkey=_expected_assertor_pubkey(plan),
            score_snapshot=first_snapshot["scores"],
        )

        first_event_ids = sorted(str(frame.event["id"]) for frame in first_snapshot["published"])
        first_checkpoint_rows = tuple(first_snapshot["checkpoints"])
        _capture_derivation_artifacts(
            bundle,
            stack,
            relay=relay,
            name="derivation-first-cycle",
            snapshot=first_snapshot,
        )

        _restart_service(stack, "refresher")
        refresher_restart = _wait_until(
            lambda: {
                "facts": _facts_snapshot(plan),
                "cycle_count": _service_log_count(stack, "refresher", "refresh_completed"),
            },
            is_ready=lambda current: current["cycle_count"] >= 1,
            description="derivation refresher restart cycle",
        )
        assert refresher_restart["facts"] == first_snapshot["facts"]

        _restart_service(stack, "ranker")
        ranker_restart = _wait_until(
            lambda: {
                "scores": _score_snapshot(plan),
                "cycle_count": _service_log_count(stack, "ranker", "ranker_cycle_completed"),
            },
            is_ready=lambda current: current["cycle_count"] >= 1,
            description="derivation ranker restart cycle",
        )
        assert ranker_restart["scores"] == first_snapshot["scores"]

        _restart_service(stack, "assertor")
        restart_snapshot = _wait_until(
            lambda: {
                "scores": _score_snapshot(plan),
                "published": _captured_assertor_events(relay.ws_url),
                "checkpoints": _assertor_checkpoints(plan),
                "assertor_cycles": _service_log_count(stack, "assertor", "cycle_completed"),
            },
            is_ready=lambda current: current["assertor_cycles"] >= 1,
            description="derivation assertor restart cycle",
        )

        restart_event_ids = sorted(
            str(frame.event["id"]) for frame in restart_snapshot["published"]
        )
        assert restart_snapshot["scores"] == first_snapshot["scores"]
        assert restart_snapshot["checkpoints"] == first_checkpoint_rows
        assert restart_event_ids == first_event_ids

        _capture_derivation_artifacts(
            bundle,
            stack,
            relay=relay,
            name="derivation-restart-cycle",
            snapshot={
                "first": first_snapshot,
                "refresher_restart": refresher_restart,
                "ranker_restart": ranker_restart,
                "second": restart_snapshot,
            },
        )
    finally:
        capture_stack_artifacts(bundle, stack, services=DERIVATION_PIPELINE_ARTIFACT_SERVICES)
        if relay is not None:
            relay.stop()
        stack.down()
