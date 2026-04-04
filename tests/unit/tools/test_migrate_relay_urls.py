"""Unit tests for relay URL migration rebuild integration."""

from __future__ import annotations

from types import SimpleNamespace

from tools import migrate_relay_urls as migrate_tool


def test_main_triggers_rebuild_after_live_relay_changes(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_password")
    monkeypatch.setattr(
        migrate_tool.argparse.ArgumentParser,
        "parse_args",
        lambda _self: SimpleNamespace(
            host="localhost",
            port=5432,
            database="bigbrotr",
            user="admin",
            dry_run=False,
        ),
    )

    def fake_run(coro):
        name = coro.cr_code.co_name
        calls.append(name)
        coro.close()
        if name == "migrate":
            return migrate_tool.MigrationResult(
                relays=migrate_tool.PhaseStats(total=1, renormalized=1),
            )
        return None

    monkeypatch.setattr(migrate_tool.asyncio, "run", fake_run)

    assert migrate_tool.main() is None
    assert calls == ["migrate", "_run_rebuild"]


def test_main_skips_rebuild_for_dry_run(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setenv("DB_ADMIN_PASSWORD", "test_password")
    monkeypatch.setattr(
        migrate_tool.argparse.ArgumentParser,
        "parse_args",
        lambda _self: SimpleNamespace(
            host="localhost",
            port=5432,
            database="bigbrotr",
            user="admin",
            dry_run=True,
        ),
    )

    def fake_run(coro):
        name = coro.cr_code.co_name
        calls.append(name)
        coro.close()
        return migrate_tool.MigrationResult()

    monkeypatch.setattr(migrate_tool.asyncio, "run", fake_run)

    assert migrate_tool.main() is None
    assert calls == ["migrate"]
