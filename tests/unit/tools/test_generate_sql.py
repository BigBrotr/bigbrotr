"""Unit tests for storage-profile-aware SQL generation."""

from __future__ import annotations

from tools import generate_sql


def test_generated_sql_matches_builtin_deployment_set() -> None:
    generated = generate_sql.generate()

    deployment_names = {path.split("/")[1] for path in generated if path.startswith("deployments/")}

    assert deployment_names == set(generate_sql.GENERATED_DEPLOYMENTS)


def test_bigbrotr_uses_full_archive_event_schema() -> None:
    generated = generate_sql.generate()
    event_sql = generated["deployments/bigbrotr/postgres/init/02_tables_core.sql"]

    assert "tags JSONB NOT NULL" in event_sql
    assert "content TEXT NOT NULL" in event_sql
    assert "sig BYTEA NOT NULL" in event_sql


def test_lilbrotr_uses_lightweight_archive_event_schema() -> None:
    generated = generate_sql.generate()
    event_sql = generated["deployments/lilbrotr/postgres/init/02_tables_core.sql"]

    assert "tags JSONB," in event_sql
    assert "content TEXT," in event_sql
    assert "sig BYTEA," in event_sql
    assert "always NULL" in event_sql
