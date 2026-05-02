from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from bigbrotr.core.brotr import Brotr
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.document import DocumentType
from bigbrotr.models.service_state import ServiceStateType
from tests.integration.harness.builders import (
    build_event_observation as _event_observation,
)
from tests.integration.harness.builders import (
    build_relay_document as _relay_document,
)
from tests.integration.harness.builders import build_service_state as _service_state
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
from tests.system.harness import (
    RuntimeAddressPlan,
    RuntimeDatabaseTarget,
    fetch_runtime_rows,
)


if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from bigbrotr.models import EventObservation, RelayDocument, ServiceState
    from tests.system.harness import ComposeStack, SystemArtifactBundle


pytestmark = pytest.mark.system


REFRESHER_ARTIFACT_SERVICES = (*BOOTSTRAP_SERVICES, "refresher")
_PUBKEY_KIND_ROWS_SQL = """
    SELECT pubkey, kind, event_count
    FROM pubkey_kind_stats
    ORDER BY pubkey, kind
"""
_CURRENT_DOCUMENT_ROWS_SQL = """
    SELECT relay_url, role, ENCODE(document_id, 'hex') AS document_id, associated_at
    FROM relay_document_current
    ORDER BY relay_url, role
"""
_CHECKPOINT_ROWS_SQL = """
    SELECT state_key, (state_value->>'timestamp')::bigint AS timestamp
    FROM service_state
    WHERE owner = 'refresher'
      AND state_type = 'checkpoint'
    ORDER BY state_key
"""


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


async def _async_seed_runtime(
    plan: RuntimeAddressPlan,
    *,
    observations: tuple[EventObservation, ...] = (),
    documents: tuple[RelayDocument, ...] = (),
    states: tuple[ServiceState, ...] = (),
) -> None:
    brotr = _runtime_brotr(plan)
    async with brotr:
        if observations:
            await brotr.insert_event_observation(list(observations), cascade=True)
        if documents:
            await brotr.insert_relay_document(list(documents), cascade=True)
        if states:
            await brotr.upsert_service_state(list(states))


def _seed_runtime(
    plan: RuntimeAddressPlan,
    *,
    observations: tuple[EventObservation, ...] = (),
    documents: tuple[RelayDocument, ...] = (),
    states: tuple[ServiceState, ...] = (),
) -> None:
    asyncio.run(
        _async_seed_runtime(
            plan,
            observations=observations,
            documents=documents,
            states=states,
        )
    )


def _configure_refresher_runtime(
    plan: RuntimeAddressPlan,
    *,
    current_targets: tuple[str, ...],
    analytics_targets: tuple[str, ...],
    periodic_targets: dict[str, bool] | None = None,
    cleanup_enabled: bool = True,
    processing: dict[str, object] | None = None,
) -> None:
    config_path = plan.runtime_root / "config" / "services" / "refresher.yaml"
    payload = yaml.safe_load(config_path.read_text())
    assert isinstance(payload, dict)

    payload["interval"] = 3600.0
    payload["current"] = {"targets": list(current_targets)}
    payload["analytics"] = {"targets": list(analytics_targets)}
    payload["cleanup"] = {"enabled": cleanup_enabled}

    periodic_payload = payload.setdefault("periodic", {})
    assert isinstance(periodic_payload, dict)
    for key in ("rolling_windows", "relay_stats_document", "nip85_followers"):
        periodic_payload[key] = False
    if periodic_targets is not None:
        periodic_payload.update(periodic_targets)

    processing_payload = payload.setdefault("processing", {})
    assert isinstance(processing_payload, dict)
    if processing is not None:
        processing_payload.update(processing)

    config_path.write_text(yaml.safe_dump(payload, sort_keys=False))


def _prepare_refresher_run(
    tmp_path: Path,
    run_name: str,
    *,
    current_targets: tuple[str, ...],
    analytics_targets: tuple[str, ...],
    periodic_targets: dict[str, bool] | None = None,
    cleanup_enabled: bool = True,
    processing: dict[str, object] | None = None,
) -> tuple[SystemArtifactBundle, RuntimeAddressPlan, ComposeStack]:
    bundle = create_bundle(tmp_path, run_name)
    plan = RuntimeAddressPlan.create("bigbrotr", tmp_path / "runtime", run_name)
    prepare_runtime_compose_config(plan)
    _configure_refresher_runtime(
        plan,
        current_targets=current_targets,
        analytics_targets=analytics_targets,
        periodic_targets=periodic_targets,
        cleanup_enabled=cleanup_enabled,
        processing=processing,
    )
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)
    return bundle, plan, stack


def _pubkey_kind_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _PUBKEY_KIND_ROWS_SQL)


def _current_document_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _CURRENT_DOCUMENT_ROWS_SQL)


def _checkpoint_rows(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _CHECKPOINT_ROWS_SQL)


def _refresher_logs(stack: ComposeStack) -> str:
    return stack.run("logs", "--no-color", "refresher", check=False).stdout


def _wait_until(
    fetch_snapshot: Callable[[], Any],
    *,
    is_ready: Callable[[Any], bool],
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


def _restart_refresher(stack: ComposeStack) -> None:
    stack.run("stop", "refresher")
    stack.wait_until_state("refresher", state="exited", timeout=60.0)
    stack.run("rm", "-f", "refresher")
    stack.up("refresher")
    stack.wait_until_ready(("refresher",), timeout=180.0)


def _capture_refresher_artifacts(
    bundle: SystemArtifactBundle,
    stack: ComposeStack,
    *,
    name: str,
) -> None:
    bundle.capture_container_logs(
        f"{name}-refresher",
        _refresher_logs(stack),
    )


@pytest.mark.timeout(900)
def test_refresher_refreshes_outputs_updates_checkpoints_and_cleans_stale_state(
    tmp_path: Path,
) -> None:
    bundle, plan, stack = _prepare_refresher_run(
        tmp_path,
        "refresher-runtime-contract",
        current_targets=("relay_document_current",),
        analytics_targets=("pubkey_kind_stats",),
        periodic_targets={"rolling_windows": True},
    )
    seeded_document = _relay_document(
        "wss://refresher-current.example.com",
        {"name": "Refresher System"},
        associated_at=110,
    )
    seeded_observation = _event_observation(
        "10" * 32,
        "wss://refresher-analytics.example.com",
        kind=1,
        pubkey="11" * 32,
        observed_at=100,
    )
    stale_state = _service_state(
        owner=ServiceName.REFRESHER,
        state_type=ServiceStateType.CHECKPOINT,
        state_key="old_target",
        state_value={"timestamp": 1},
    )

    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)
        _seed_runtime(
            plan,
            observations=(seeded_observation,),
            documents=(seeded_document,),
            states=(stale_state,),
        )

        stack.up("refresher", build=True)
        stack.wait_until_ready(("refresher",), timeout=180.0)

        snapshot = _wait_until(
            lambda: {
                "pubkey_kind_stats": _pubkey_kind_rows(plan),
                "relay_document_current": _current_document_rows(plan),
                "checkpoints": _checkpoint_rows(plan),
                "logs": _refresher_logs(stack),
            },
            is_ready=lambda current: (
                len(current["pubkey_kind_stats"]) == 1
                and len(current["relay_document_current"]) == 1
                and {row["state_key"] for row in current["checkpoints"]}
                == {"pubkey_kind_stats", "relay_document_current"}
                and "periodic_refreshed" in current["logs"]
                and "refresh_completed" in current["logs"]
            ),
            description="refresher runtime outputs",
        )
        _capture_refresher_artifacts(bundle, stack, name="refresher-runtime-contract")
        bundle.capture_db_snapshot("refresher-runtime-contract", snapshot)
    finally:
        capture_stack_artifacts(bundle, stack, services=REFRESHER_ARTIFACT_SERVICES)
        stack.down()

    pubkey_row = snapshot["pubkey_kind_stats"][0]
    current_row = snapshot["relay_document_current"][0]
    checkpoints = {row["state_key"]: row["timestamp"] for row in snapshot["checkpoints"]}

    assert pubkey_row == {"pubkey": "11" * 32, "kind": 1, "event_count": 1}
    assert current_row == {
        "relay_url": "wss://refresher-current.example.com",
        "role": DocumentType.NIP11_INFO.value,
        "document_id": seeded_document.document.content_hash.hex(),
        "associated_at": 110,
    }
    assert checkpoints == {"pubkey_kind_stats": 100, "relay_document_current": 110}
    assert "incremental_refreshed" in snapshot["logs"]
    assert "rolling_windows" in snapshot["logs"]
    assert "old_target" not in snapshot["logs"]


@pytest.mark.timeout(900)
def test_refresher_restart_resumes_from_checkpoint_without_duplicate_drift(
    tmp_path: Path,
) -> None:
    bundle, plan, stack = _prepare_refresher_run(
        tmp_path,
        "refresher-restart-contract",
        current_targets=(),
        analytics_targets=("pubkey_kind_stats",),
        processing={"max_source_window": 25},
    )
    first_observation = _event_observation(
        "20" * 32,
        "wss://refresher-restart.example.com",
        kind=1,
        pubkey="22" * 32,
        observed_at=100,
    )
    second_observation = _event_observation(
        "21" * 32,
        "wss://refresher-restart.example.com",
        kind=1,
        pubkey="33" * 32,
        observed_at=150,
    )

    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)
        _seed_runtime(plan, observations=(first_observation, second_observation))

        stack.up("refresher", build=True)
        stack.wait_until_ready(("refresher",), timeout=180.0)

        first_snapshot = _wait_until(
            lambda: {
                "pubkey_kind_stats": _pubkey_kind_rows(plan),
                "checkpoints": _checkpoint_rows(plan),
                "logs": _refresher_logs(stack),
            },
            is_ready=lambda current: (
                len(current["pubkey_kind_stats"]) == 1
                and current["pubkey_kind_stats"][0]["pubkey"] == "22" * 32
                and current["checkpoints"]
                == ({"state_key": "pubkey_kind_stats", "timestamp": 125},)
                and "refresh_completed" in current["logs"]
            ),
            description="first refresher partial cycle",
        )

        _restart_refresher(stack)

        second_snapshot = _wait_until(
            lambda: {
                "pubkey_kind_stats": _pubkey_kind_rows(plan),
                "checkpoints": _checkpoint_rows(plan),
                "logs": _refresher_logs(stack),
            },
            is_ready=lambda current: (
                len(current["pubkey_kind_stats"]) == 2
                and {row["pubkey"] for row in current["pubkey_kind_stats"]}
                == {"22" * 32, "33" * 32}
                and current["checkpoints"]
                == ({"state_key": "pubkey_kind_stats", "timestamp": 150},)
                and "refresh_completed" in current["logs"]
            ),
            description="refresher restart resume",
        )
        _capture_refresher_artifacts(bundle, stack, name="refresher-restart-contract")
        bundle.capture_db_snapshot(
            "refresher-restart-contract",
            {"first": first_snapshot, "second": second_snapshot},
        )
    finally:
        capture_stack_artifacts(bundle, stack, services=REFRESHER_ARTIFACT_SERVICES)
        stack.down()

    assert first_snapshot["pubkey_kind_stats"] == (
        {"pubkey": "22" * 32, "kind": 1, "event_count": 1},
    )
    assert second_snapshot["pubkey_kind_stats"] == (
        {"pubkey": "22" * 32, "kind": 1, "event_count": 1},
        {"pubkey": "33" * 32, "kind": 1, "event_count": 1},
    )
    assert "cutoff_reason=max_duration" not in first_snapshot["logs"]
    assert "cutoff_reason=max_duration" not in second_snapshot["logs"]
