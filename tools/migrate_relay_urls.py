#!/usr/bin/env python3
"""One-shot migration: re-normalize all relay URLs using normalize_relay_url.

Run against a live PostgreSQL (services stopped, only postgres running):

    DB_ADMIN_PASSWORD=<pw> python tools/migrate_relay_urls.py [--dry-run]

Five phases:

Phase 1 — Relay table:
    For each URL in the relay table, apply normalize_relay_url + Relay().
    - Unchanged: skip.
    - Renormalized: DELETE old (CASCADE cleans event_relay, relay_metadata),
      INSERT canonical as validator candidate.
    - Invalid: DELETE outright.

Phase 2 — Validator candidates:
    For each validator checkpoint in service_state, re-normalize the state_key URL.
    - Unchanged: skip.
    - Renormalized: DELETE old, INSERT with canonical key (preserving state_value).
    - Invalid: DELETE.

Phase 3 — Finder reset:
    DELETE all finder cursors and checkpoints from service_state to force a
    full re-scan from the beginning.

Phase 4 — Orphan cleanup:
    Run orphan cleanup procedures for metadata and events detached by relay
    deletions or renormalization.

Phase 5 — Analytics rebuild:
    Rebuild summary tables and reset dependent checkpoints so incremental
    analytics and Assertor publications realign with the new relay set.

Safety:
    - Phases 1-3 run in a single transaction (all-or-nothing).
    - Phases 4-5 run only after a committed live migration.
    - Use --dry-run to preview phases 1-3 without making changes.
    - Back up your database first.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field

import asyncpg


# ---------------------------------------------------------------------------
# Bootstrap: ensure the project is importable
# ---------------------------------------------------------------------------
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import Relay
from bigbrotr.models.relay_url import normalize_relay_url


try:
    from tools.rebuild_analytics import rebuild_analytics
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from rebuild_analytics import rebuild_analytics


@dataclass
class PhaseStats:
    total: int = 0
    unchanged: int = 0
    renormalized: int = 0
    invalid: int = 0


@dataclass
class MigrationResult:
    relays: PhaseStats = field(default_factory=PhaseStats)
    candidates: PhaseStats = field(default_factory=PhaseStats)
    finder_cursors_deleted: int = 0
    finder_checkpoints_deleted: int = 0
    orphan_metadata_deleted: int = 0
    orphan_events_deleted: int = 0


def _normalize(raw_url: str) -> str | None:
    """Return canonical URL, or None if the URL is irrecoverable."""
    try:
        canonical = normalize_relay_url(raw_url)
        Relay(canonical)
        return canonical
    except (ValueError, TypeError):
        return None


async def migrate(  # noqa: PLR0912, PLR0913, PLR0915
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    dry_run: bool,
) -> MigrationResult:
    conn = await asyncpg.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
    )
    result = MigrationResult()

    try:
        async with conn.transaction():
            # =============================================================
            # Phase 1: Relay table
            # =============================================================
            print("--- Phase 1: Relay table ---\n")
            rows = await conn.fetch("SELECT url FROM relay ORDER BY url")
            result.relays.total = len(rows)
            print(f"Found {result.relays.total} relay URLs.\n")

            for row in rows:
                old_url: str = row["url"]
                canonical = _normalize(old_url)

                if canonical is None:
                    result.relays.invalid += 1
                    print(f"  INVALID  {old_url}")
                    if not dry_run:
                        await conn.execute("DELETE FROM relay WHERE url = $1", old_url)
                    continue

                if canonical == old_url:
                    result.relays.unchanged += 1
                    continue

                result.relays.renormalized += 1
                print(f"  CHANGED  {old_url}")
                print(f"        -> {canonical}")

                if not dry_run:
                    await conn.execute("DELETE FROM relay WHERE url = $1", old_url)
                    # Re-insert canonical URL as a validator candidate so it gets
                    # re-validated and promoted back into the relay table.
                    relay = Relay(canonical)
                    await conn.execute(
                        """
                        INSERT INTO service_state
                            (service_name, state_type, state_key, state_value)
                        VALUES ('validator', 'checkpoint', $1,
                                jsonb_build_object('network', $2::text, 'failures', 0))
                        ON CONFLICT DO NOTHING
                        """,
                        canonical,
                        relay.network.value,
                    )

            # =============================================================
            # Phase 2: Validator candidates (service_state)
            # =============================================================
            print("\n--- Phase 2: Validator candidates ---\n")
            rows = await conn.fetch(
                """
                SELECT state_key, state_value
                FROM service_state
                WHERE service_name = 'validator' AND state_type = 'checkpoint'
                ORDER BY state_key
                """
            )
            result.candidates.total = len(rows)
            print(f"Found {result.candidates.total} validator candidates.\n")

            for row in rows:
                old_key: str = row["state_key"]
                old_value = row["state_value"]
                canonical = _normalize(old_key)

                if canonical is None:
                    result.candidates.invalid += 1
                    print(f"  INVALID  {old_key}")
                    if not dry_run:
                        await conn.execute(
                            """
                            DELETE FROM service_state
                            WHERE service_name = 'validator'
                              AND state_type = 'checkpoint'
                              AND state_key = $1
                            """,
                            old_key,
                        )
                    continue

                if canonical == old_key:
                    result.candidates.unchanged += 1
                    continue

                result.candidates.renormalized += 1
                print(f"  RENAME   {old_key}")
                print(f"        -> {canonical}")

                if not dry_run:
                    await conn.execute(
                        """
                        DELETE FROM service_state
                        WHERE service_name = 'validator'
                          AND state_type = 'checkpoint'
                          AND state_key = $1
                        """,
                        old_key,
                    )
                    # Re-insert with canonical key, preserving state_value
                    await conn.execute(
                        """
                        INSERT INTO service_state
                            (service_name, state_type, state_key, state_value)
                        VALUES ('validator', 'checkpoint', $1, $2::jsonb)
                        ON CONFLICT DO NOTHING
                        """,
                        canonical,
                        old_value,
                    )

            # =============================================================
            # Phase 3: Reset finder state
            # =============================================================
            print("\n--- Phase 3: Reset finder state ---\n")

            if not dry_run:
                tag = await conn.execute(
                    """
                    DELETE FROM service_state
                    WHERE service_name = 'finder' AND state_type = 'cursor'
                    """
                )
                result.finder_cursors_deleted = int(tag.split()[-1])

                tag = await conn.execute(
                    """
                    DELETE FROM service_state
                    WHERE service_name = 'finder' AND state_type = 'checkpoint'
                    """
                )
                result.finder_checkpoints_deleted = int(tag.split()[-1])
            else:
                row = await conn.fetchval(
                    """
                    SELECT count(*)::int FROM service_state
                    WHERE service_name = 'finder' AND state_type = 'cursor'
                    """
                )
                result.finder_cursors_deleted = row or 0

                row = await conn.fetchval(
                    """
                    SELECT count(*)::int FROM service_state
                    WHERE service_name = 'finder' AND state_type = 'checkpoint'
                    """
                )
                result.finder_checkpoints_deleted = row or 0

            print(f"  Finder cursors:     {result.finder_cursors_deleted}")
            print(f"  Finder checkpoints: {result.finder_checkpoints_deleted}")

            if dry_run:
                raise _DryRunRollbackError

    except _DryRunRollbackError:
        pass

    # =============================================================
    # Phase 4: Orphan cleanup (outside transaction, batched)
    # =============================================================
    if not dry_run and (result.relays.renormalized or result.relays.invalid):
        print("\n--- Phase 4: Orphan cleanup ---\n")

        print("  Cleaning orphan metadata...", flush=True)
        result.orphan_metadata_deleted = await conn.fetchval("SELECT orphan_metadata_delete(10000)")
        print(f"    Deleted: {result.orphan_metadata_deleted}")

        print("  Cleaning orphan events (this may take a while)...", flush=True)
        result.orphan_events_deleted = await conn.fetchval("SELECT orphan_event_delete(10000)")
        print(f"    Deleted: {result.orphan_events_deleted}")
    elif dry_run:
        print("\n--- Phase 4: Orphan cleanup (skipped in dry-run) ---")

    await conn.close()
    return result


class _DryRunRollbackError(Exception):
    pass


async def _run_rebuild(
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
) -> None:
    brotr = Brotr.from_dict(
        {
            "pool": {
                "database": {
                    "host": host,
                    "port": port,
                    "database": database,
                    "user": user,
                    "password": password,
                }
            }
        }
    )
    async with brotr:
        await rebuild_analytics(brotr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-normalize relay URLs and reset finder state.",
        epilog="Password is read from DB_ADMIN_PASSWORD environment variable.",
    )
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--database", default="bigbrotr")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--dry-run", action="store_true", help="Preview without changes")
    args = parser.parse_args()

    password = os.environ.get("DB_ADMIN_PASSWORD")
    if not password:
        parser.error("DB_ADMIN_PASSWORD environment variable is required")

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"=== Relay URL Migration ({mode}) ===\n")

    result = asyncio.run(
        migrate(
            host=args.host,
            port=args.port,
            database=args.database,
            user=args.user,
            password=password,
            dry_run=args.dry_run,
        )
    )

    if not args.dry_run and (result.relays.renormalized or result.relays.invalid):
        print("\n--- Phase 5: Analytics rebuild ---\n")
        try:
            asyncio.run(
                _run_rebuild(
                    host=args.host,
                    port=args.port,
                    database=args.database,
                    user=args.user,
                    password=password,
                )
            )
        except Exception:
            print(
                "  Analytics rebuild failed; analytics may now be stale or unreliable "
                "until tools/rebuild_analytics.py succeeds."
            )
            raise
        print("  Analytics rebuild completed successfully.")

    print(f"\n{'=' * 40}")
    print("  Phase 1 — Relays")
    print(f"    Total:         {result.relays.total}")
    print(f"    Unchanged:     {result.relays.unchanged}")
    print(f"    Renormalized:  {result.relays.renormalized}")
    print(f"    Invalid:       {result.relays.invalid}")
    print("  Phase 2 — Validator candidates")
    print(f"    Total:         {result.candidates.total}")
    print(f"    Unchanged:     {result.candidates.unchanged}")
    print(f"    Renormalized:  {result.candidates.renormalized}")
    print(f"    Invalid:       {result.candidates.invalid}")
    print("  Phase 3 — Finder reset")
    print(f"    Cursors deleted:     {result.finder_cursors_deleted}")
    print(f"    Checkpoints deleted: {result.finder_checkpoints_deleted}")
    print("  Phase 4 — Orphan cleanup")
    print(f"    Metadata deleted:    {result.orphan_metadata_deleted}")
    print(f"    Events deleted:      {result.orphan_events_deleted}")
    rebuilt = not args.dry_run and (result.relays.renormalized or result.relays.invalid)
    print("  Phase 5 — Analytics rebuild")
    print(f"    Rebuilt:            {'yes' if rebuilt else 'no'}")
    print(f"{'=' * 40}")

    if args.dry_run and (
        result.relays.renormalized
        or result.relays.invalid
        or result.candidates.renormalized
        or result.candidates.invalid
        or result.finder_cursors_deleted
        or result.finder_checkpoints_deleted
    ):
        print("\nRun without --dry-run to apply changes.")


if __name__ == "__main__":
    main()
