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
from tests.integration.harness.builders import build_event_observation
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
    FaultControlPortPlan,
    LocalRelayRuntime,
    LocalToxiproxyRuntime,
    ProxySpec,
    RuntimeAddressPlan,
    ToxicSpec,
    fetch_runtime_rows,
    query_events,
)
from tests.system.harness.compose import build_test_env_values


if TYPE_CHECKING:
    from pathlib import Path

    from tests.system.harness import ComposeStack, RelayEventFrame, SystemArtifactBundle


pytestmark = pytest.mark.system


ASSERTOR_ARTIFACT_SERVICES = (*BOOTSTRAP_SERVICES, "assertor")
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
_ASSERTOR_SCORE_INSERT_QUERIES = {
    "pubkey_score": """
        INSERT INTO pubkey_score (algorithm_id, pubkey, score)
        VALUES ($1, $2, $3)
    """,
    "event_score": """
        INSERT INTO event_score (algorithm_id, event_id, score)
        VALUES ($1, $2, $3)
    """,
    "addressable_score": """
        INSERT INTO addressable_score (algorithm_id, event_address, score)
        VALUES ($1, $2, $3)
    """,
    "identifier_score": """
        INSERT INTO identifier_score (algorithm_id, identifier, score)
        VALUES ($1, $2, $3)
    """,
}
_ASSERTOR_KINDS = [
    int(EventKind.SET_METADATA),
    int(EventKind.NIP85_TRUSTED_PROVIDER_LIST),
    int(EventKind.NIP85_USER_ASSERTION),
    int(EventKind.NIP85_EVENT_ASSERTION),
    int(EventKind.NIP85_ADDRESSABLE_ASSERTION),
    int(EventKind.NIP85_IDENTIFIER_ASSERTION),
]
_FAULT_RESET_TOXIC = ToxicSpec(
    name="assertor-reset",
    toxic_type="reset_peer",
    stream="downstream",
    attributes={"timeout": 0},
)
_ALGORITHM_ID = "global-pagerank"
_AUTHOR = "c1" * 32
_REPLIER = "d1" * 32
_ROOT_EVENT_ID = "a0" * 32
_REPLY_EVENT_ID = "a1" * 32
_EVENT_ADDRESS = f"30023:{_AUTHOR}:article"
_IDENTIFIER = "isbn:9780140328721"
_SOURCE_RELAY_URL = "wss://assertor-source.example.com"
_PUBLIC_RELAY_HINT = "wss://relay.assertor.example.com"


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


async def _refresh_assertor_facts(brotr: Brotr) -> None:
    for table in (
        "pubkey_kind_stats",
        "pubkey_relay_stats",
        "relay_kind_stats",
        "pubkey_stats",
        "kind_stats",
        "relay_stats",
        "nip85_pubkey_stats",
        "nip85_event_stats",
        "nip85_addressable_stats",
        "nip85_identifier_stats",
    ):
        await brotr.fetchval(f"SELECT {table}_refresh($1::BIGINT, $2::BIGINT)", 0, 2_000_000_000)


async def _async_seed_assertor_inputs(plan: RuntimeAddressPlan) -> None:
    brotr = _runtime_brotr(plan)
    async with brotr:
        await brotr.insert_event_observation(
            [
                build_event_observation(
                    _ROOT_EVENT_ID,
                    _SOURCE_RELAY_URL,
                    pubkey=_AUTHOR,
                    created_at=1_700_000_000,
                    tags=[],
                ),
                build_event_observation(
                    _REPLY_EVENT_ID,
                    _SOURCE_RELAY_URL,
                    pubkey=_REPLIER,
                    created_at=1_700_000_100,
                    tags=[["e", _ROOT_EVENT_ID], ["p", _AUTHOR]],
                ),
            ],
            cascade=True,
        )
        await _refresh_assertor_facts(brotr)
        await brotr.execute(
            """
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
            """,
            _EVENT_ADDRESS,
            _AUTHOR,
            2,
            1,
            0,
            4,
            1,
            2000,
        )
        await brotr.execute(
            """
            INSERT INTO nip85_identifier_stats (identifier, comment_count, reaction_count, k_tags)
            VALUES ($1, $2, $3, $4::TEXT[])
            """,
            _IDENTIFIER,
            3,
            5,
            ["book", "isbn"],
        )
        for table_name, subject_id, score in (
            ("pubkey_score", _AUTHOR, 89.0),
            ("event_score", _ROOT_EVENT_ID, 81.0),
            ("addressable_score", _EVENT_ADDRESS, 84.0),
            ("identifier_score", _IDENTIFIER, 73.0),
        ):
            await brotr.execute(
                _ASSERTOR_SCORE_INSERT_QUERIES[table_name],
                _ALGORITHM_ID,
                subject_id,
                score,
            )


def _seed_assertor_inputs(plan: RuntimeAddressPlan) -> None:
    asyncio.run(_async_seed_assertor_inputs(plan))


def _configure_assertor_runtime(
    plan: RuntimeAddressPlan,
    *,
    relay_url: str,
    relay_hint: str,
    interval: float,
) -> None:
    config_path = plan.runtime_root / "config" / "services" / "assertor.yaml"
    payload = yaml.safe_load(config_path.read_text())
    assert isinstance(payload, dict)

    payload["interval"] = interval
    payload["algorithm_id"] = _ALGORITHM_ID
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
        "relay_hint": relay_hint,
        "tag_names": ["rank"],
        "content": "",
    }

    config_path.write_text(yaml.safe_dump(payload, sort_keys=False))


def _prepare_assertor_run(
    tmp_path: Path,
    run_name: str,
    *,
    slot: int,
) -> tuple[SystemArtifactBundle, RuntimeAddressPlan, ComposeStack]:
    bundle = create_bundle(tmp_path, run_name)
    plan = RuntimeAddressPlan.create("bigbrotr", tmp_path / "runtime", run_name, slot=slot)
    prepare_runtime_compose_config(plan)
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)
    return bundle, plan, stack


def _assertor_logs(stack: ComposeStack) -> str:
    return stack.run("logs", "--no-color", "assertor", check=False).stdout


def _assertor_log_count(stack: ComposeStack, text: str) -> int:
    return _assertor_logs(stack).count(text)


def _assertor_checkpoints(plan: RuntimeAddressPlan) -> tuple[dict[str, object], ...]:
    return fetch_runtime_rows(plan, _ASSERTOR_CHECKPOINT_ROWS_SQL)


def _captured_assertor_events(ws_url: str) -> tuple[RelayEventFrame, ...]:
    return asyncio.run(
        query_events(
            ws_url,
            filters={"kinds": _ASSERTOR_KINDS},
            subscription_id="assertor-capture",
        )
    )


def _expected_assertor_pubkey(plan: RuntimeAddressPlan) -> str:
    private_key = build_test_env_values(plan.profile, plan.project_name)[
        "NOSTR_PRIVATE_KEY_ASSERTOR"
    ]
    return Keys.parse(private_key).public_key().to_hex()


def _toxiproxy_internal_ws_url(
    plan: RuntimeAddressPlan,
    toxiproxy: LocalToxiproxyRuntime,
    proxy_port: int,
) -> str:
    inspect_payload = toxiproxy.inspect()
    networks = inspect_payload.get("NetworkSettings", {}).get("Networks", {})
    if not isinstance(networks, dict):
        raise RuntimeError("Toxiproxy inspect payload did not include network settings")

    network_payload = networks.get(plan.data_network_name)
    if not isinstance(network_payload, dict):
        raise RuntimeError(f"Toxiproxy is not attached to network {plan.data_network_name!r}")

    ip_address = network_payload.get("IPAddress")
    if not isinstance(ip_address, str) or not ip_address:
        raise RuntimeError(f"Toxiproxy network {plan.data_network_name!r} did not report an IP")

    return f"ws://{ip_address}:{proxy_port}"


def _tag_values(event: dict[str, object], tag_name: str) -> list[str]:
    values: list[str] = []
    raw_tags = event.get("tags")
    if not isinstance(raw_tags, list):
        return values
    for tag in raw_tags:
        if isinstance(tag, list) and len(tag) > 1 and tag[0] == tag_name:
            values.append(str(tag[1]))
    return values


def _assert_full_provider_package(
    events: tuple[RelayEventFrame, ...],
    *,
    expected_pubkey: str,
    relay_hint: str,
) -> None:
    assert len(events) == 6
    events_by_kind = {int(frame.event["kind"]): frame.event for frame in events}
    assert set(events_by_kind) == set(_ASSERTOR_KINDS)
    assert all(str(event["pubkey"]) == expected_pubkey for event in events_by_kind.values())

    metadata_content = json.loads(str(events_by_kind[int(EventKind.SET_METADATA)]["content"]))
    assert metadata_content["name"] == "BigBrotr Global PageRank"
    assert metadata_content["about"] == "NIP-85 trusted assertion provider"
    assert metadata_content["software"] == "bigbrotr"

    trusted_provider_tags = events_by_kind[int(EventKind.NIP85_TRUSTED_PROVIDER_LIST)]["tags"]
    assert trusted_provider_tags == [
        ["30382:rank", expected_pubkey, relay_hint],
        ["30383:rank", expected_pubkey, relay_hint],
        ["30384:rank", expected_pubkey, relay_hint],
        ["30385:rank", expected_pubkey, relay_hint],
    ]
    assert _tag_values(events_by_kind[int(EventKind.NIP85_USER_ASSERTION)], "rank") == ["89"]
    assert _tag_values(events_by_kind[int(EventKind.NIP85_EVENT_ASSERTION)], "rank") == ["81"]
    assert _tag_values(events_by_kind[int(EventKind.NIP85_EVENT_ASSERTION)], "p") == [_AUTHOR]
    assert _tag_values(events_by_kind[int(EventKind.NIP85_ADDRESSABLE_ASSERTION)], "a") == [
        _EVENT_ADDRESS
    ]
    assert _tag_values(events_by_kind[int(EventKind.NIP85_ADDRESSABLE_ASSERTION)], "p") == [_AUTHOR]
    assert _tag_values(events_by_kind[int(EventKind.NIP85_ADDRESSABLE_ASSERTION)], "rank") == ["84"]
    assert _tag_values(events_by_kind[int(EventKind.NIP85_IDENTIFIER_ASSERTION)], "d") == [
        _IDENTIFIER
    ]
    assert _tag_values(events_by_kind[int(EventKind.NIP85_IDENTIFIER_ASSERTION)], "i") == [
        _IDENTIFIER
    ]
    assert _tag_values(events_by_kind[int(EventKind.NIP85_IDENTIFIER_ASSERTION)], "rank") == ["73"]
    assert sorted(_tag_values(events_by_kind[int(EventKind.NIP85_IDENTIFIER_ASSERTION)], "k")) == [
        "book",
        "isbn",
    ]


def _state_rows_by_key(
    rows: tuple[dict[str, object], ...],
) -> dict[str, dict[str, int | str]]:
    return {
        str(row["state_key"]): {
            "hash": str(row["hash"]),
            "timestamp": int(row["timestamp"]),
        }
        for row in rows
    }


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


def _capture_assertor_artifacts(
    bundle: SystemArtifactBundle,
    stack: ComposeStack,
    *,
    relay: LocalRelayRuntime | None = None,
    toxiproxy: LocalToxiproxyRuntime | None = None,
    name: str,
    snapshot: dict[str, object] | None = None,
) -> None:
    bundle.capture_container_logs(f"{name}-assertor", _assertor_logs(stack))
    if relay is not None:
        bundle.capture_container_logs(f"{name}-relay", relay.logs())
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
    if snapshot is not None:
        bundle.capture_db_snapshot(name, snapshot)


@pytest.mark.timeout(900)
def test_assertor_publishes_provider_package_and_skips_duplicates_on_restart(
    tmp_path: Path,
) -> None:
    bundle, plan, stack = _prepare_assertor_run(
        tmp_path,
        "assertor-provider-package",
        slot=44,
    )
    relay = None
    first_snapshot: dict[str, object] | None = None
    second_snapshot: dict[str, object] | None = None

    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        relay = start_baseline_relay(plan)
        relay_url = resolve_runtime_relay_url(plan, relay)
        _configure_assertor_runtime(
            plan,
            relay_url=relay_url,
            relay_hint=_PUBLIC_RELAY_HINT,
            interval=3600.0,
        )
        _seed_assertor_inputs(plan)

        stack.up("assertor", build=True)
        stack.wait_until_ready(("assertor",), timeout=180.0)

        first_snapshot = _wait_until(
            lambda: {
                "events": _captured_assertor_events(relay.ws_url),
                "checkpoints": _assertor_checkpoints(plan),
                "cycle_count": _assertor_log_count(stack, "cycle_completed"),
            },
            is_ready=lambda current: (
                len(current["events"]) == 6
                and len(current["checkpoints"]) == 6
                and current["cycle_count"] >= 1
            ),
            description="assertor first publication cycle",
        )
        _assert_full_provider_package(
            first_snapshot["events"],
            expected_pubkey=_expected_assertor_pubkey(plan),
            relay_hint=_PUBLIC_RELAY_HINT,
        )
        first_state_by_key = {
            str(row["state_key"]): {
                "hash": str(row["hash"]),
                "timestamp": int(row["timestamp"]),
            }
            for row in first_snapshot["checkpoints"]
        }
        expected_keys = {
            f"{_ALGORITHM_ID}:0:provider_profile",
            f"{_ALGORITHM_ID}:10040:trusted_provider_list",
            f"{_ALGORITHM_ID}:30382:{_AUTHOR}",
            f"{_ALGORITHM_ID}:30383:{_ROOT_EVENT_ID}",
            f"{_ALGORITHM_ID}:30384:{_EVENT_ADDRESS}",
            f"{_ALGORITHM_ID}:30385:{_IDENTIFIER}",
        }
        assert set(first_state_by_key) == expected_keys
        _capture_assertor_artifacts(
            bundle,
            stack,
            relay=relay,
            name="assertor-first-cycle",
            snapshot=first_snapshot,
        )

        stack.run("restart", "assertor")
        stack.wait_until_ready(("assertor",), timeout=180.0)

        second_snapshot = _wait_until(
            lambda: {
                "events": _captured_assertor_events(relay.ws_url),
                "checkpoints": _assertor_checkpoints(plan),
                "cycle_count": _assertor_log_count(stack, "cycle_completed"),
            },
            is_ready=lambda current: current["cycle_count"] >= 2,
            description="assertor restart cycle",
        )
        second_state_by_key = {
            str(row["state_key"]): {
                "hash": str(row["hash"]),
                "timestamp": int(row["timestamp"]),
            }
            for row in second_snapshot["checkpoints"]
        }
        assert len(second_snapshot["events"]) == 6
        assert second_state_by_key == first_state_by_key
        _capture_assertor_artifacts(
            bundle,
            stack,
            relay=relay,
            name="assertor-restart-cycle",
            snapshot=second_snapshot,
        )
    finally:
        capture_stack_artifacts(bundle, stack, services=ASSERTOR_ARTIFACT_SERVICES)
        if relay is not None:
            relay.stop()
        stack.down()


@pytest.mark.timeout(1200)
def test_assertor_publish_failure_does_not_persist_checkpoint_hashes(tmp_path: Path) -> None:
    bundle, plan, stack = _prepare_assertor_run(
        tmp_path,
        "assertor-publish-failure",
        slot=45,
    )
    relay = None
    toxiproxy = None
    initial_snapshot: dict[str, object] | None = None
    failed_snapshot: dict[str, object] | None = None

    try:
        stack.up(*BOOTSTRAP_SERVICES)
        stack.wait_until_ready(BOOTSTRAP_SERVICES)

        relay = start_baseline_relay(plan)
        port_plan = FaultControlPortPlan.for_slot(46)
        proxy_port = port_plan.proxy_port(0)
        toxiproxy = LocalToxiproxyRuntime(
            role="assertor-failure",
            runtime_dir=tmp_path / "toxiproxy-runtime",
            network_name=plan.data_network_name,
            network_aliases=("assertor-toxiproxy",),
            port_plan=port_plan,
            exposed_proxy_ports=(proxy_port,),
        )
        toxiproxy.start()
        toxiproxy.wait_until_ready()
        toxiproxy.client.create_proxy(
            ProxySpec(
                name="assertor-upstream",
                upstream_host=relay.container_name,
                upstream_port=8080,
                listen_port=proxy_port,
            )
        )
        relay_url = _toxiproxy_internal_ws_url(plan, toxiproxy, proxy_port)

        _configure_assertor_runtime(
            plan,
            relay_url=relay_url,
            relay_hint=_PUBLIC_RELAY_HINT,
            interval=60.0,
        )

        stack.up("assertor", build=True)
        stack.wait_until_ready(("assertor",), timeout=180.0)

        initial_snapshot = _wait_until(
            lambda: {
                "events": _captured_assertor_events(relay.ws_url),
                "checkpoints": _assertor_checkpoints(plan),
                "cycle_count": _assertor_log_count(stack, "cycle_completed"),
            },
            is_ready=lambda current: (
                len(current["events"]) == 2
                and len(current["checkpoints"]) == 2
                and current["cycle_count"] >= 1
            ),
            description="assertor initial provider publication cycle",
        )
        initial_state_by_key = _state_rows_by_key(initial_snapshot["checkpoints"])
        assert set(initial_state_by_key) == {
            f"{_ALGORITHM_ID}:0:provider_profile",
            f"{_ALGORITHM_ID}:10040:trusted_provider_list",
        }
        initial_event_ids = [str(frame.event["id"]) for frame in initial_snapshot["events"]]

        toxiproxy.client.add_toxic("assertor-upstream", _FAULT_RESET_TOXIC)
        _seed_assertor_inputs(plan)

        failed_snapshot = _wait_until(
            lambda: {
                "events": _captured_assertor_events(relay.ws_url),
                "checkpoints": _assertor_checkpoints(plan),
                "cycle_count": _assertor_log_count(stack, "cycle_completed"),
                "logs": _assertor_logs(stack),
            },
            is_ready=lambda current: (
                current["cycle_count"] >= 2 and "user_assertion_failed" in current["logs"]
            ),
            description="assertor failed publish cycle",
            timeout=150.0,
        )
        assert [str(frame.event["id"]) for frame in failed_snapshot["events"]] == initial_event_ids
        assert _state_rows_by_key(failed_snapshot["checkpoints"]) == initial_state_by_key
        assert "user_assertion_failed" in failed_snapshot["logs"]
        assert "event_assertion_failed" in failed_snapshot["logs"]
        assert "addressable_assertion_failed" in failed_snapshot["logs"]
        assert "identifier_assertion_failed" in failed_snapshot["logs"]
        _capture_assertor_artifacts(
            bundle,
            stack,
            relay=relay,
            toxiproxy=toxiproxy,
            name="assertor-failure-cycle",
            snapshot=failed_snapshot,
        )
    finally:
        capture_stack_artifacts(bundle, stack, services=ASSERTOR_ARTIFACT_SERVICES)
        if toxiproxy is not None:
            toxiproxy.stop()
        if relay is not None:
            relay.stop()
        stack.down()
