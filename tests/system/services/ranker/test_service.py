from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import duckdb
import pytest
import yaml

from bigbrotr.services.ranker.queries import GraphSyncCheckpoint
from bigbrotr.services.ranker.utils import RankerStore
from tests.system.deployments.baseline import (
    capture_stack_artifacts,
    create_bundle,
    create_stack,
    record_runtime_plan,
)
from tests.system.deployments.runtime_overrides import (
    BOOTSTRAP_SERVICES,
    prepare_runtime_compose_config,
)
from tests.system.harness import RuntimeAddressPlan, execute_runtime, fetch_runtime_rows


if TYPE_CHECKING:
    from pathlib import Path

    from tests.system.harness import ComposeStack, SystemArtifactBundle


pytestmark = pytest.mark.system


RANKER_ARTIFACT_SERVICES = (*BOOTSTRAP_SERVICES, "ranker")
_PUBKEY_SCORE_ROWS_SQL = """
    SELECT algorithm_id, pubkey AS subject_id, score
    FROM pubkey_score
    WHERE algorithm_id = $1
    ORDER BY pubkey
"""
_EVENT_SCORE_ROWS_SQL = """
    SELECT algorithm_id, event_id AS subject_id, score
    FROM event_score
    WHERE algorithm_id = $1
    ORDER BY event_id
"""
_ADDRESSABLE_SCORE_ROWS_SQL = """
    SELECT algorithm_id, event_address AS subject_id, score
    FROM addressable_score
    WHERE algorithm_id = $1
    ORDER BY event_address
"""
_IDENTIFIER_SCORE_ROWS_SQL = """
    SELECT algorithm_id, identifier AS subject_id, score
    FROM identifier_score
    WHERE algorithm_id = $1
    ORDER BY identifier
"""
_INSERT_CONTACT_LIST_SQL = """
    INSERT INTO contact_lists_current (
        follower_pubkey,
        source_event_id,
        source_created_at,
        source_seen_at,
        follow_count
    ) VALUES ($1, $2, $3, $4, $5)
"""
_UPDATE_CONTACT_LIST_SQL = """
    UPDATE contact_lists_current
    SET source_event_id = $2,
        source_created_at = $3,
        source_seen_at = $4,
        follow_count = $5
    WHERE follower_pubkey = $1
"""
_DELETE_FOLLOW_EDGES_SQL = """
    DELETE FROM contact_list_edges_current
    WHERE follower_pubkey = $1
"""
_INSERT_FOLLOW_EDGE_SQL = """
    INSERT INTO contact_list_edges_current (
        follower_pubkey,
        followed_pubkey,
        source_event_id,
        source_created_at,
        source_seen_at
    ) VALUES ($1, $2, $3, $4, $5)
"""
_INSERT_EVENT_STATS_SQL = """
    INSERT INTO nip85_event_stats (
        event_id,
        author_pubkey,
        comment_count,
        quote_count,
        repost_count,
        reaction_count,
        zap_count,
        zap_amount
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
"""
_INSERT_ADDRESSABLE_STATS_SQL = """
    INSERT INTO nip85_addressable_stats (
        event_address,
        author_pubkey,
        comment_count,
        quote_count,
        repost_count,
        reaction_count,
        zap_count,
        zap_amount
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
"""
_INSERT_IDENTIFIER_STATS_SQL = """
    INSERT INTO nip85_identifier_stats (
        identifier,
        comment_count,
        reaction_count,
        k_tags
    ) VALUES ($1, $2, $3, $4::TEXT[])
"""

_PUBKEY_A = "a" * 64
_PUBKEY_B = "b" * 64
_PUBKEY_C = "c" * 64
_PUBKEY_D = "d" * 64
_EVENT_ID = "11" * 32
_EVENT_ADDRESS = f"30023:{_PUBKEY_A}:article"
_IDENTIFIER_A = "isbn:9780140328721"
_IDENTIFIER_B = "geo:41.9028,12.4964"
_ALGORITHM_ID = "global-pagerank"


def _configure_ranker_runtime(
    plan: RuntimeAddressPlan,
    *,
    algorithm_id: str = _ALGORITHM_ID,
    storage_path: str = "/app/data/ranker.duckdb",
    checkpoint_path: str = "/app/data/ranker.checkpoint.json",
    max_consecutive_failures: int = 5,
) -> None:
    config_path = plan.runtime_root / "config" / "services" / "ranker.yaml"
    payload = yaml.safe_load(config_path.read_text())
    assert isinstance(payload, dict)

    payload["interval"] = 3600.0
    payload["max_consecutive_failures"] = max_consecutive_failures
    payload["algorithm_id"] = algorithm_id
    payload["storage"] = {
        "path": storage_path,
        "checkpoint_path": checkpoint_path,
    }
    payload["processing"] = {"max_duration": 60.0}
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


def _set_ranker_restart_policy(plan: RuntimeAddressPlan, restart_policy: str) -> None:
    compose_data = yaml.safe_load(plan.compose_file.read_text())
    assert isinstance(compose_data, dict)
    services = compose_data.get("services")
    assert isinstance(services, dict)
    ranker_service = services.get("ranker")
    assert isinstance(ranker_service, dict)
    ranker_service["restart"] = restart_policy
    plan.compose_file.write_text(yaml.safe_dump(compose_data, sort_keys=False))


def _prepare_ranker_run(
    tmp_path: Path,
    run_name: str,
    *,
    profile: str,
    slot: int,
    storage_path: str = "/app/data/ranker.duckdb",
    checkpoint_path: str = "/app/data/ranker.checkpoint.json",
    max_consecutive_failures: int = 5,
    restart_policy: str | None = None,
) -> tuple[SystemArtifactBundle, RuntimeAddressPlan, ComposeStack]:
    bundle = create_bundle(tmp_path, run_name)
    plan = RuntimeAddressPlan.create(profile, tmp_path / "runtime", run_name, slot=slot)
    prepare_runtime_compose_config(plan)
    _configure_ranker_runtime(
        plan,
        storage_path=storage_path,
        checkpoint_path=checkpoint_path,
        max_consecutive_failures=max_consecutive_failures,
    )
    if restart_policy is not None:
        _set_ranker_restart_policy(plan, restart_policy)
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)
    return bundle, plan, stack


def _insert_contact_list(
    plan: RuntimeAddressPlan,
    *,
    follower_pubkey: str,
    source_event_id: str,
    source_created_at: int,
    source_seen_at: int,
    follow_count: int,
) -> None:
    execute_runtime(
        plan,
        _INSERT_CONTACT_LIST_SQL,
        follower_pubkey,
        source_event_id,
        source_created_at,
        source_seen_at,
        follow_count,
    )


def _update_contact_list(
    plan: RuntimeAddressPlan,
    *,
    follower_pubkey: str,
    source_event_id: str,
    source_created_at: int,
    source_seen_at: int,
    follow_count: int,
) -> None:
    execute_runtime(
        plan,
        _UPDATE_CONTACT_LIST_SQL,
        follower_pubkey,
        source_event_id,
        source_created_at,
        source_seen_at,
        follow_count,
    )


def _delete_follow_edges(plan: RuntimeAddressPlan, *, follower_pubkey: str) -> None:
    execute_runtime(plan, _DELETE_FOLLOW_EDGES_SQL, follower_pubkey)


def _insert_follow_edge(
    plan: RuntimeAddressPlan,
    *,
    follower_pubkey: str,
    followed_pubkey: str,
    source_event_id: str,
    source_created_at: int,
    source_seen_at: int,
) -> None:
    execute_runtime(
        plan,
        _INSERT_FOLLOW_EDGE_SQL,
        follower_pubkey,
        followed_pubkey,
        source_event_id,
        source_created_at,
        source_seen_at,
    )


def _insert_event_stats(
    plan: RuntimeAddressPlan,
    *,
    event_id: str,
    author_pubkey: str,
    comment_count: int,
    quote_count: int,
    repost_count: int,
    reaction_count: int,
    zap_count: int,
    zap_amount: int,
) -> None:
    execute_runtime(
        plan,
        _INSERT_EVENT_STATS_SQL,
        event_id,
        author_pubkey,
        comment_count,
        quote_count,
        repost_count,
        reaction_count,
        zap_count,
        zap_amount,
    )


def _insert_addressable_stats(
    plan: RuntimeAddressPlan,
    *,
    event_address: str,
    author_pubkey: str,
    comment_count: int,
    quote_count: int,
    repost_count: int,
    reaction_count: int,
    zap_count: int,
    zap_amount: int,
) -> None:
    execute_runtime(
        plan,
        _INSERT_ADDRESSABLE_STATS_SQL,
        event_address,
        author_pubkey,
        comment_count,
        quote_count,
        repost_count,
        reaction_count,
        zap_count,
        zap_amount,
    )


def _insert_identifier_stats(
    plan: RuntimeAddressPlan,
    *,
    identifier: str,
    comment_count: int,
    reaction_count: int,
    k_tags: list[str],
) -> None:
    execute_runtime(
        plan,
        _INSERT_IDENTIFIER_STATS_SQL,
        identifier,
        comment_count,
        reaction_count,
        k_tags,
    )


def _seed_ranker_inputs(plan: RuntimeAddressPlan) -> None:
    _insert_contact_list(
        plan,
        follower_pubkey=_PUBKEY_A,
        source_event_id="evt-a-1",
        source_created_at=100,
        source_seen_at=10,
        follow_count=2,
    )
    _insert_contact_list(
        plan,
        follower_pubkey=_PUBKEY_D,
        source_event_id="evt-d-1",
        source_created_at=200,
        source_seen_at=20,
        follow_count=1,
    )
    _insert_follow_edge(
        plan,
        follower_pubkey=_PUBKEY_A,
        followed_pubkey=_PUBKEY_B,
        source_event_id="evt-a-1",
        source_created_at=100,
        source_seen_at=10,
    )
    _insert_follow_edge(
        plan,
        follower_pubkey=_PUBKEY_A,
        followed_pubkey=_PUBKEY_C,
        source_event_id="evt-a-1",
        source_created_at=100,
        source_seen_at=10,
    )
    _insert_follow_edge(
        plan,
        follower_pubkey=_PUBKEY_D,
        followed_pubkey=_PUBKEY_A,
        source_event_id="evt-d-1",
        source_created_at=200,
        source_seen_at=20,
    )
    _insert_event_stats(
        plan,
        event_id=_EVENT_ID,
        author_pubkey=_PUBKEY_A,
        comment_count=2,
        quote_count=1,
        repost_count=0,
        reaction_count=3,
        zap_count=1,
        zap_amount=2000,
    )
    _insert_addressable_stats(
        plan,
        event_address=_EVENT_ADDRESS,
        author_pubkey=_PUBKEY_A,
        comment_count=1,
        quote_count=0,
        repost_count=0,
        reaction_count=2,
        zap_count=0,
        zap_amount=0,
    )
    _insert_identifier_stats(
        plan,
        identifier=_IDENTIFIER_A,
        comment_count=3,
        reaction_count=1,
        k_tags=["book"],
    )
    _insert_identifier_stats(
        plan,
        identifier=_IDENTIFIER_B,
        comment_count=1,
        reaction_count=4,
        k_tags=["place", "city"],
    )


def _mutate_ranker_graph(plan: RuntimeAddressPlan) -> None:
    _update_contact_list(
        plan,
        follower_pubkey=_PUBKEY_A,
        source_event_id="evt-a-2",
        source_created_at=300,
        source_seen_at=30,
        follow_count=1,
    )
    _delete_follow_edges(plan, follower_pubkey=_PUBKEY_A)
    _insert_follow_edge(
        plan,
        follower_pubkey=_PUBKEY_A,
        followed_pubkey=_PUBKEY_D,
        source_event_id="evt-a-2",
        source_created_at=300,
        source_seen_at=30,
    )


def _score_rows(plan: RuntimeAddressPlan, query: str) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, query, _ALGORITHM_ID)


def _score_snapshot(plan: RuntimeAddressPlan) -> dict[str, tuple[dict[str, object], ...]]:
    return {
        "pubkey": _score_rows(plan, _PUBKEY_SCORE_ROWS_SQL),
        "event": _score_rows(plan, _EVENT_SCORE_ROWS_SQL),
        "addressable": _score_rows(plan, _ADDRESSABLE_SCORE_ROWS_SQL),
        "identifier": _score_rows(plan, _IDENTIFIER_SCORE_ROWS_SQL),
    }


def _ranker_store(plan: RuntimeAddressPlan) -> RankerStore:
    return RankerStore(
        db_path=plan.ranker_data_dir / "ranker.duckdb",
        checkpoint_path=plan.ranker_data_dir / "ranker.checkpoint.json",
    )


def _rank_run_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    db_path = plan.ranker_data_dir / "ranker.duckdb"
    if not db_path.is_file():
        return ()
    conn = duckdb.connect(str(db_path))
    try:
        rows = conn.execute(
            """
            SELECT run_id, algorithm_id, status, node_count, edge_count, finished_at
            FROM rank_runs
            ORDER BY run_id
            """
        ).fetchall()
    finally:
        conn.close()
    return tuple(
        {
            "run_id": row[0],
            "algorithm_id": row[1],
            "status": row[2],
            "node_count": row[3],
            "edge_count": row[4],
            "finished_at": row[5],
        }
        for row in rows
    )


def _ranker_logs(stack: ComposeStack) -> str:
    return stack.run("logs", "--no-color", "ranker", check=False).stdout


def _stop_ranker(stack: ComposeStack) -> None:
    stack.run("stop", "ranker")
    stack.wait_until_state("ranker", state="exited", timeout=120.0)


def _restart_ranker(stack: ComposeStack) -> None:
    _stop_ranker(stack)
    stack.run("rm", "-f", "ranker")
    stack.up("ranker")
    stack.wait_until_ready(("ranker",), timeout=180.0)


def _capture_ranker_artifacts(
    bundle: SystemArtifactBundle,
    stack: ComposeStack,
    plan: RuntimeAddressPlan,
    *,
    name: str,
    snapshot: dict[str, object] | None = None,
) -> None:
    bundle.capture_container_logs(f"{name}-ranker", _ranker_logs(stack))
    bundle.write_json_artifact(
        category="database",
        subdir="database",
        name=f"{name}-ranker-store",
        payload={
            "db_path": plan.ranker_data_dir / "ranker.duckdb",
            "checkpoint_path": plan.ranker_data_dir / "ranker.checkpoint.json",
            "db_exists": (plan.ranker_data_dir / "ranker.duckdb").is_file(),
            "checkpoint_exists": (plan.ranker_data_dir / "ranker.checkpoint.json").is_file(),
            "rank_runs": _rank_run_rows(plan),
        },
    )
    if snapshot is not None:
        bundle.capture_db_snapshot(name, snapshot)


def _wait_until(
    fetch_snapshot: Any,
    *,
    is_ready: Any,
    description: str,
    timeout: float = 120.0,
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


@pytest.mark.timeout(900)
def test_ranker_exports_scores_persists_private_store_and_restarts_incrementally(
    tmp_path: Path,
) -> None:
    bundle, plan, stack = _prepare_ranker_run(
        tmp_path,
        "ranker-runtime-contract",
        profile="bigbrotr",
        slot=41,
    )
    first_snapshot: dict[str, object] | None = None
    final_snapshot: dict[str, object] | None = None

    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)
        _seed_ranker_inputs(plan)

        stack.up("ranker", build=True)
        stack.wait_until_ready(("ranker",), timeout=180.0)

        first_snapshot = _wait_until(
            lambda: {
                "scores": _score_snapshot(plan),
                "duckdb_exists": (plan.ranker_data_dir / "ranker.duckdb").is_file(),
                "logs": _ranker_logs(stack),
            },
            is_ready=lambda current: (
                current["duckdb_exists"]
                and "ranker_cycle_completed" in current["logs"]
                and [row["subject_id"] for row in current["scores"]["pubkey"]]
                == [_PUBKEY_A, _PUBKEY_B, _PUBKEY_C, _PUBKEY_D]
                and [row["subject_id"] for row in current["scores"]["event"]] == [_EVENT_ID]
                and [row["subject_id"] for row in current["scores"]["addressable"]]
                == [_EVENT_ADDRESS]
                and [row["subject_id"] for row in current["scores"]["identifier"]]
                == [_IDENTIFIER_B, _IDENTIFIER_A]
            ),
            description="ranker first-cycle export",
        )
        _stop_ranker(stack)

        store = _ranker_store(plan)
        stats = store.get_graph_stats()
        assert stats.node_count == 4
        assert stats.edge_count == 3
        assert store.load_checkpoint() == GraphSyncCheckpoint(
            source_seen_at=20, follower_pubkey=_PUBKEY_D
        )
        assert store.count_rank_runs() == 1
        assert store.count_rank_runs(status="success") == 1
        assert store.count_rank_runs(status="failed") == 0
        assert store.duckdb_file_size_bytes() > 0
        assert all(
            0.0 <= float(row["score"]) <= 100.0 for row in first_snapshot["scores"]["pubkey"]
        )
        assert all(0.0 < float(row["score"]) <= 100.0 for row in first_snapshot["scores"]["event"])
        assert all(
            0.0 < float(row["score"]) <= 100.0 for row in first_snapshot["scores"]["addressable"]
        )
        assert all(
            0.0 < float(row["score"]) <= 100.0 for row in first_snapshot["scores"]["identifier"]
        )
        _capture_ranker_artifacts(
            bundle,
            stack,
            plan,
            name="ranker-first-cycle",
            snapshot=first_snapshot,
        )

        _mutate_ranker_graph(plan)
        _restart_ranker(stack)

        final_snapshot = _wait_until(
            lambda: {
                "scores": _score_snapshot(plan),
                "logs": _ranker_logs(stack),
            },
            is_ready=lambda current: (
                "ranker_cycle_completed" in current["logs"]
                and [row["subject_id"] for row in current["scores"]["pubkey"]]
                == [_PUBKEY_A, _PUBKEY_D]
                and [row["subject_id"] for row in current["scores"]["event"]] == [_EVENT_ID]
                and [row["subject_id"] for row in current["scores"]["addressable"]]
                == [_EVENT_ADDRESS]
                and [row["subject_id"] for row in current["scores"]["identifier"]]
                == [_IDENTIFIER_B, _IDENTIFIER_A]
            ),
            description="ranker restart export",
        )
        _stop_ranker(stack)

        store = _ranker_store(plan)
        stats = store.get_graph_stats()
        assert stats.node_count == 2
        assert stats.edge_count == 2
        assert store.load_checkpoint() == GraphSyncCheckpoint(
            source_seen_at=30, follower_pubkey=_PUBKEY_A
        )
        assert store.count_rank_runs() == 2
        assert store.count_rank_runs(status="success") == 2
        assert store.count_rank_runs(status="failed") == 0
        assert tuple(row["status"] for row in _rank_run_rows(plan)) == ("success", "success")
        _capture_ranker_artifacts(
            bundle,
            stack,
            plan,
            name="ranker-restart-cycle",
            snapshot=final_snapshot,
        )
    finally:
        capture_stack_artifacts(bundle, stack, services=RANKER_ARTIFACT_SERVICES)
        stack.down()


@pytest.mark.timeout(900)
def test_ranker_lilbrotr_profile_exports_scores_to_profile_owned_store(tmp_path: Path) -> None:
    bundle, plan, stack = _prepare_ranker_run(
        tmp_path,
        "ranker-lilbrotr-profile",
        profile="lilbrotr",
        slot=42,
    )
    snapshot: dict[str, object] | None = None

    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)
        _seed_ranker_inputs(plan)

        stack.up("ranker", build=True)
        stack.wait_until_ready(("ranker",), timeout=180.0)

        snapshot = _wait_until(
            lambda: {
                "scores": _score_snapshot(plan),
                "duckdb_exists": (plan.ranker_data_dir / "ranker.duckdb").is_file(),
                "logs": _ranker_logs(stack),
            },
            is_ready=lambda current: (
                current["duckdb_exists"]
                and "ranker_cycle_completed" in current["logs"]
                and [row["subject_id"] for row in current["scores"]["pubkey"]]
                == [_PUBKEY_A, _PUBKEY_B, _PUBKEY_C, _PUBKEY_D]
            ),
            description="lilbrotr ranker export",
        )
        _stop_ranker(stack)

        store = _ranker_store(plan)
        assert store.count_rank_runs(status="success") == 1
        assert store.load_checkpoint() == GraphSyncCheckpoint(
            source_seen_at=20, follower_pubkey=_PUBKEY_D
        )
        assert plan.project_name.startswith("lb-sys-")
        _capture_ranker_artifacts(
            bundle,
            stack,
            plan,
            name="ranker-lilbrotr-profile",
            snapshot=snapshot,
        )
    finally:
        capture_stack_artifacts(bundle, stack, services=RANKER_ARTIFACT_SERVICES)
        stack.down()


@pytest.mark.timeout(900)
def test_ranker_storage_failure_exits_without_partial_score_export(tmp_path: Path) -> None:
    bundle, plan, stack = _prepare_ranker_run(
        tmp_path,
        "ranker-storage-failure",
        profile="bigbrotr",
        slot=43,
        storage_path="/app/data",
        restart_policy="no",
        max_consecutive_failures=1,
    )
    failure_snapshot: dict[str, object] | None = None

    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        up_result = stack.run("up", "-d", "--build", "ranker", check=False)
        assert up_result.returncode in {0, 1}, up_result.stderr
        stack.wait_until_state("ranker", state="exited", exit_code=1, timeout=180.0)

        failure_snapshot = {
            "scores": _score_snapshot(plan),
            "duckdb_exists": (plan.ranker_data_dir / "ranker.duckdb").is_file(),
            "logs": _ranker_logs(stack),
        }
        assert failure_snapshot["scores"] == {
            "pubkey": (),
            "event": (),
            "addressable": (),
            "identifier": (),
        }
        assert failure_snapshot["duckdb_exists"] is False
        assert "ranker_failed" in failure_snapshot["logs"]
        _capture_ranker_artifacts(
            bundle,
            stack,
            plan,
            name="ranker-storage-failure",
            snapshot=failure_snapshot,
        )
    finally:
        capture_stack_artifacts(bundle, stack, services=RANKER_ARTIFACT_SERVICES)
        stack.down()
