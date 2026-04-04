#!/usr/bin/env python3
"""One-shot analytics rebuild for summary tables and related checkpoints.

The rebuild is intended for destructive maintenance windows or after fixing
logic bugs in incremental analytics. It:

1. Refreshes bounded materialized views in dependency order
2. Truncates summary tables
3. Replays incremental summary refresh from ``after=0`` to ``until``
4. Runs periodic reconciliation functions
5. Aligns refresher checkpoints
6. Clears assertor checkpoints so corrected assertions can be republished

By default the CLI loads deployment-specific admin DB config from
``deployments/<deployment>/config/brotr.yaml`` and therefore expects
``DB_ADMIN_PASSWORD`` in the environment.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bigbrotr.core.brotr import Brotr
from bigbrotr.core.yaml import load_yaml
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.refresher.configs import DEFAULT_MATVIEWS, DEFAULT_SUMMARIES
from bigbrotr.services.refresher.queries import (
    refresh_nip85_followers,
    refresh_relay_metadata,
    refresh_rolling_windows,
    refresh_summary,
)


if TYPE_CHECKING:
    from argparse import Namespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_DEPLOYMENTS = ("bigbrotr", "lilbrotr")
SUMMARY_TABLES = list(DEFAULT_SUMMARIES)
MATVIEWS = list(DEFAULT_MATVIEWS)
TRUNCATE_SQL = (
    "TRUNCATE "
    "pubkey_kind_stats, "
    "pubkey_relay_stats, "
    "relay_kind_stats, "
    "pubkey_stats, "
    "kind_stats, "
    "relay_stats, "
    "nip85_pubkey_stats, "
    "nip85_event_stats"
)


@dataclass(slots=True)
class RebuildResult:
    """Execution summary for one rebuild run."""

    until: int
    matviews_refreshed: list[str] = field(default_factory=list)
    summaries_refreshed: dict[str, int] = field(default_factory=dict)
    periodic_tasks: list[str] = field(default_factory=list)
    refresher_checkpoints_upserted: int = 0
    assertor_checkpoints_deleted: int = 0


def _deployment_brotr_config(deployment: str) -> Path:
    return PROJECT_ROOT / "deployments" / deployment / "config" / "brotr.yaml"


def _runtime_config(
    *,
    deployment: str,
    host: str | None = None,
    port: int | None = None,
    database: str | None = None,
    user: str | None = None,
) -> dict:
    """Load deployment config and optionally override DB connection fields."""
    config = deepcopy(load_yaml(str(_deployment_brotr_config(deployment))))
    pool = config.setdefault("pool", {})
    db = pool.setdefault("database", {})

    if host is not None:
        db["host"] = host
    if port is not None:
        db["port"] = port
    if database is not None:
        db["database"] = database
    if user is not None:
        db["user"] = user

    return config


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the rebuild tool."""
    parser = argparse.ArgumentParser(
        description="Rebuild analytics summary tables and reset dependent checkpoints.",
    )
    parser.add_argument(
        "--deployment",
        choices=SUPPORTED_DEPLOYMENTS,
        required=True,
        help="Deployment config to use (bigbrotr or lilbrotr).",
    )
    parser.add_argument(
        "--until",
        type=int,
        help="Inclusive upper seen_at watermark to rebuild to (default: current wall clock).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned rebuild sequence without touching the database.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm execution for a live rebuild.",
    )
    parser.add_argument(
        "--host",
        help="Override database host from deployment config (useful outside Docker).",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Override database port from deployment config.",
    )
    parser.add_argument(
        "--database",
        help="Override database name from deployment config.",
    )
    parser.add_argument(
        "--user",
        help="Override database user from deployment config.",
    )
    args = parser.parse_args(argv)
    if not args.dry_run and not args.yes:
        parser.error("--yes is required for a live rebuild")
    return args


async def rebuild_analytics(
    brotr: Brotr,
    *,
    until: int | None = None,
) -> RebuildResult:
    """Rebuild analytics end-to-end on an already connected ``Brotr`` instance."""
    watermark = until if until is not None else int(time.time())
    result = RebuildResult(until=watermark)

    for view in MATVIEWS:
        await brotr.refresh_materialized_view(view)
        result.matviews_refreshed.append(view)

    await brotr.execute(TRUNCATE_SQL)

    for table in SUMMARY_TABLES:
        rows = await refresh_summary(brotr, table, 0, watermark)
        result.summaries_refreshed[table] = rows

    await refresh_rolling_windows(brotr)
    result.periodic_tasks.append("rolling_windows")
    await refresh_relay_metadata(brotr)
    result.periodic_tasks.append("relay_stats_metadata")
    await refresh_nip85_followers(brotr)
    result.periodic_tasks.append("nip85_followers")

    result.refresher_checkpoints_upserted = await brotr.upsert_service_state(
        [
            ServiceState(
                service_name=ServiceName.REFRESHER,
                state_type=ServiceStateType.CHECKPOINT,
                state_key=table,
                state_value={"timestamp": watermark},
            )
            for table in SUMMARY_TABLES
        ]
    )

    assertor_states = await brotr.get_service_state(
        ServiceName.ASSERTOR,
        ServiceStateType.CHECKPOINT,
    )
    if assertor_states:
        result.assertor_checkpoints_deleted = await brotr.delete_service_state(
            service_names=[s.service_name for s in assertor_states],
            state_types=[s.state_type for s in assertor_states],
            state_keys=[s.state_key for s in assertor_states],
        )

    return result


async def _run_from_args(args: Namespace) -> RebuildResult:
    brotr = Brotr.from_dict(
        _runtime_config(
            deployment=args.deployment,
            host=args.host,
            port=args.port,
            database=args.database,
            user=args.user,
        )
    )
    async with brotr:
        return await rebuild_analytics(brotr, until=args.until)


def _print_dry_run(deployment: str, until: int | None) -> None:
    watermark = until if until is not None else int(time.time())
    print("=== Analytics Rebuild (DRY RUN) ===\n")
    print(f"Deployment: {deployment}")
    print(f"Until:      {watermark}")
    print("\nPhase 1 — Materialized views")
    for view in MATVIEWS:
        print(f"  - {view}")
    print("\nPhase 2 — Truncate summary tables")
    for table in SUMMARY_TABLES:
        print(f"  - {table}")
    print("\nPhase 3 — Incremental replay")
    for table in SUMMARY_TABLES:
        print(f"  - {table}_refresh(0, {watermark})")
    print("\nPhase 4 — Periodic reconciliation")
    print("  - rolling_windows_refresh()")
    print("  - relay_stats_metadata_refresh()")
    print("  - nip85_follower_count_refresh()")
    print("\nPhase 5 — Checkpoints")
    print("  - Upsert refresher checkpoints for all summary tables")
    print("  - Delete all assertor checkpoint hashes")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    if args.dry_run:
        _print_dry_run(args.deployment, args.until)
        return 0

    result = asyncio.run(_run_from_args(args))

    print("=== Analytics Rebuild Complete ===\n")
    print(f"Until: {result.until}")
    print("\nMaterialized views refreshed:")
    for view in result.matviews_refreshed:
        print(f"  - {view}")
    print("\nSummary rows affected:")
    for table, rows in result.summaries_refreshed.items():
        print(f"  - {table}: {rows}")
    print("\nPeriodic tasks:")
    for task in result.periodic_tasks:
        print(f"  - {task}")
    print("\nCheckpoint state:")
    print(f"  - refresher checkpoints upserted: {result.refresher_checkpoints_upserted}")
    print(f"  - assertor checkpoints deleted:  {result.assertor_checkpoints_deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
