from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from tools import generate_sql

from tests.system.deployments.baseline import (
    capture_stack_artifacts,
    create_bundle,
    create_stack,
    record_runtime_plan,
)
from tests.system.deployments.runtime_overrides import prepare_runtime_compose_config
from tests.system.harness import RuntimeAddressPlan, fetch_runtime_rows, fetch_runtime_value


pytestmark = pytest.mark.system


_PROFILES = ("bigbrotr", "lilbrotr")
_PROFILE_SLOTS = {"bigbrotr": 92, "lilbrotr": 93}
_EXPECTED_INIT_NON_SQL = {"01_roles.sh", "98_grants.sh", "README.md"}
_EXPECTED_POSTGRES_MOUNTS = (
    "./data/postgres:/var/lib/postgresql/data",
    "./postgres/init:/docker-entrypoint-initdb.d:ro",
    "./postgres/postgresql.conf:/etc/postgresql/postgresql.conf:ro",
)
_ALLOWED_SQL_DIFFS = {"02_tables_core.sql", "05_functions_crud.sql", "99_verify.sql"}
_EXPECTED_RUNTIME_ROLES = ("admin", "ranker", "reader", "refresher", "writer")
_EVENT_COLUMN_SQL = """
    SELECT column_name, is_nullable, udt_name
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'event'
      AND column_name = ANY($1::text[])
    ORDER BY column_name
"""
_EVENT_INSERT_SQL = """
    SELECT pg_get_functiondef(p.oid)
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND p.proname = 'event_insert'
"""
_ROLE_SQL = """
    SELECT rolname
    FROM pg_roles
    WHERE rolname = ANY($1::text[])
    ORDER BY rolname
"""
_PARTITION_SQL = """
    SELECT count(*)::int
    FROM pg_inherits i
    JOIN pg_class parent ON parent.oid = i.inhparent
    WHERE parent.relname = 'event'
"""


def _normalize_profile_tokens(value: str) -> str:
    normalized = value
    for source, target in (
        ("bigbrotr", "<profile>"),
        ("lilbrotr", "<profile>"),
        ("LilBrotr", "Brotr"),
    ):
        normalized = normalized.replace(source, target)
    return normalized


def _generated_sql_for_profile(profile: str) -> dict[str, str]:
    prefix = f"deployments/{profile}/postgres/init/"
    return {
        Path(path).name: content
        for path, content in generate_sql.generate().items()
        if path.startswith(prefix)
    }


def _deployment_sql_for_profile(profile: str) -> dict[str, str]:
    init_dir = Path(f"deployments/{profile}/postgres/init")
    return {path.name: path.read_text() for path in sorted(init_dir.glob("*.sql"))}


def _deployment_init_assets(profile: str) -> set[str]:
    init_dir = Path(f"deployments/{profile}/postgres/init")
    return {path.name for path in init_dir.iterdir()}


def _postgres_mounts(profile: str) -> tuple[str, ...]:
    compose = yaml.safe_load(Path(f"deployments/{profile}/docker-compose.yaml").read_text())
    assert isinstance(compose, dict)
    services = compose.get("services")
    assert isinstance(services, dict)
    postgres = services.get("postgres")
    assert isinstance(postgres, dict)
    volumes = postgres.get("volumes")
    assert isinstance(volumes, list)
    return tuple(str(volume) for volume in volumes)


def _event_schema_signature(sql: str) -> tuple[tuple[str, str, str], ...]:
    if (
        "tags JSONB NOT NULL" in sql
        and "content TEXT NOT NULL" in sql
        and "sig BYTEA NOT NULL" in sql
    ):
        return (
            ("content", "NO", "text"),
            ("sig", "NO", "bytea"),
            ("tags", "NO", "jsonb"),
        )
    if "tags JSONB," in sql and "content TEXT," in sql and "sig BYTEA," in sql:
        return (
            ("content", "YES", "text"),
            ("sig", "YES", "bytea"),
            ("tags", "YES", "jsonb"),
        )
    raise AssertionError("Unrecognized event schema signature")


def _event_insert_signature(sql: str) -> str:
    normalized = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    normalized = re.sub(r"--[^\n]*", "", normalized)
    normalized = " ".join(normalized.split())
    if (
        "INSERT INTO event (id, pubkey, created_at, kind, tags, tagvalues, content, sig)"
        in normalized
    ):
        return "full"
    if "INSERT INTO event (id, pubkey, created_at, kind, tagvalues)" in normalized:
        return "lightweight"
    raise AssertionError("Unrecognized event_insert signature")


def _runtime_event_schema_signature(
    rows: tuple[dict[str, object], ...],
) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (
            str(row["column_name"]),
            str(row["is_nullable"]),
            str(row["udt_name"]),
        )
        for row in rows
    )


def _run_runtime_sql_contract(
    tmp_path: Path,
    *,
    profile: str,
    run_name: str,
) -> dict[str, object]:
    bundle = create_bundle(tmp_path, run_name)
    plan = RuntimeAddressPlan.create(
        profile,
        tmp_path / "runtime",
        run_name,
        slot=_PROFILE_SLOTS[profile],
    )
    prepare_runtime_compose_config(plan)
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)

    try:
        stack.up("postgres")
        stack.wait_until_ready(("postgres",), timeout=180.0)

        snapshot = {
            "event_columns": fetch_runtime_rows(
                plan,
                _EVENT_COLUMN_SQL,
                ["content", "sig", "tags"],
            ),
            "event_insert": fetch_runtime_value(plan, _EVENT_INSERT_SQL),
            "roles": fetch_runtime_rows(plan, _ROLE_SQL, list(_EXPECTED_RUNTIME_ROLES)),
            "partition_count": fetch_runtime_value(plan, _PARTITION_SQL),
            "reader_identity": fetch_runtime_value(plan, "SELECT current_user", role="reader"),
            "writer_identity": fetch_runtime_value(plan, "SELECT current_user", role="writer"),
        }
        bundle.capture_db_snapshot(f"{profile}-sql-asset-parity", snapshot)
        return snapshot
    finally:
        capture_stack_artifacts(bundle, stack, services=("postgres",))
        stack.down()


def test_generated_sql_and_deployment_init_assets_only_differ_on_intended_profile_overrides() -> (
    None
):
    generated = {profile: _generated_sql_for_profile(profile) for profile in _PROFILES}
    deployed = {profile: _deployment_sql_for_profile(profile) for profile in _PROFILES}

    for profile in _PROFILES:
        assert deployed[profile] == generated[profile]
        assert _deployment_init_assets(profile) == (
            set(generated[profile]) | _EXPECTED_INIT_NON_SQL
        )
        assert _postgres_mounts(profile) == _EXPECTED_POSTGRES_MOUNTS

    diff_files = {
        name
        for name in generated["bigbrotr"]
        if generated["bigbrotr"][name] != generated["lilbrotr"][name]
    }
    assert diff_files == _ALLOWED_SQL_DIFFS

    assert _event_schema_signature(generated["bigbrotr"]["02_tables_core.sql"]) == (
        ("content", "NO", "text"),
        ("sig", "NO", "bytea"),
        ("tags", "NO", "jsonb"),
    )
    assert _event_schema_signature(generated["lilbrotr"]["02_tables_core.sql"]) == (
        ("content", "YES", "text"),
        ("sig", "YES", "bytea"),
        ("tags", "YES", "jsonb"),
    )
    assert _event_insert_signature(generated["bigbrotr"]["05_functions_crud.sql"]) == "full"
    assert _event_insert_signature(generated["lilbrotr"]["05_functions_crud.sql"]) == "lightweight"
    big_verify = generated["bigbrotr"]["99_verify.sql"]
    lil_verify = generated["lilbrotr"]["99_verify.sql"]
    assert "Brotr database schema initialized successfully" in big_verify
    assert "LilBrotr database schema initialized successfully" in lil_verify
    assert "Current Tables (3):" in big_verify
    assert "Current Tables (5):" in lil_verify
    assert "Public Score Tables (4):" in big_verify
    assert "NIP-85 Summary Tables (4):" in lil_verify
    assert "Event table tags, content, and sig are nullable (always NULL)." in lil_verify


@pytest.mark.parametrize("profile", _PROFILES)
@pytest.mark.timeout(900)
def test_profile_runtime_schema_matches_generated_sql_contract(
    tmp_path: Path,
    profile: str,
) -> None:
    generated = _generated_sql_for_profile(profile)
    snapshot = _run_runtime_sql_contract(
        tmp_path,
        profile=profile,
        run_name=f"{profile}-sql-asset-parity",
    )

    assert _runtime_event_schema_signature(snapshot["event_columns"]) == _event_schema_signature(
        generated["02_tables_core.sql"]
    )
    assert _event_insert_signature(str(snapshot["event_insert"])) == _event_insert_signature(
        generated["05_functions_crud.sql"]
    )
    assert tuple(str(row["rolname"]) for row in snapshot["roles"]) == _EXPECTED_RUNTIME_ROLES
    assert snapshot["partition_count"] == 16
    assert snapshot["reader_identity"] == "reader"
    assert snapshot["writer_identity"] == "writer"
