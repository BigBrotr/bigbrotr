#!/usr/bin/env python3
"""One-shot rebuild for current-state and analytics tables.

The rebuild is intended for destructive maintenance windows or after fixing
logic bugs in derived state. It:

1. Truncates current-state and analytics tables
2. Replays incremental refresh from ``after=0`` to ``until``
3. Runs periodic reconciliation functions
4. Aligns refresher checkpoints
5. Clears assertor checkpoints so corrected assertions can be republished
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
from bigbrotr.services.refresher.configs import (
    DEFAULT_ANALYTICS_TARGETS,
    DEFAULT_CURRENT_TARGETS,
    DEFAULT_PERIODIC_TARGETS,
)
from bigbrotr.services.refresher.queries import (
    get_incremental_target_spec,
    get_periodic_target_spec,
    refresh_incremental_target,
    refresh_periodic_target,
)


if TYPE_CHECKING:
    from argparse import Namespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_DEPLOYMENTS = ("bigbrotr", "lilbrotr")
CURRENT_TARGETS = list(DEFAULT_CURRENT_TARGETS)
ANALYTICS_TARGETS = list(DEFAULT_ANALYTICS_TARGETS)
PERIODIC_TARGETS = list(DEFAULT_PERIODIC_TARGETS)
CURRENT_TABLES = [target.value for target in DEFAULT_CURRENT_TARGETS]
ANALYTICS_TABLES = [target.value for target in DEFAULT_ANALYTICS_TARGETS]
TRUNCATE_SQL = "TRUNCATE " + ", ".join([*CURRENT_TABLES, *ANALYTICS_TABLES])


@dataclass(slots=True)
class RebuildResult:
    """Execution summary for one rebuild run."""

    until: int
    current_tables_refreshed: dict[str, int] = field(default_factory=dict)
    analytics_tables_refreshed: dict[str, int] = field(default_factory=dict)
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
        description="Rebuild current-state and analytics tables, then reset dependent checkpoints.",
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
    """Rebuild current-state and analytics tables on a connected ``Brotr`` instance."""
    watermark = until if until is not None else int(time.time())
    result = RebuildResult(until=watermark)

    await brotr.execute(TRUNCATE_SQL)

    for target in CURRENT_TARGETS:
        rows = await refresh_incremental_target(brotr, target, 0, watermark)
        result.current_tables_refreshed[target.value] = rows

    for target in ANALYTICS_TARGETS:
        rows = await refresh_incremental_target(brotr, target, 0, watermark)
        result.analytics_tables_refreshed[target.value] = rows

    for target in PERIODIC_TARGETS:
        await refresh_periodic_target(brotr, target)
        result.periodic_tasks.append(target.value)

    all_tables = [*CURRENT_TABLES, *ANALYTICS_TABLES]
    result.refresher_checkpoints_upserted = await brotr.upsert_service_state(
        [
            ServiceState(
                service_name=ServiceName.REFRESHER,
                state_type=ServiceStateType.CHECKPOINT,
                state_key=table,
                state_value={"timestamp": watermark},
            )
            for table in all_tables
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
    print("\nPhase 1 — Truncate derived tables")
    for table in [*CURRENT_TABLES, *ANALYTICS_TABLES]:
        print(f"  - {table}")
    print("\nPhase 2 — Current-state replay")
    for target in CURRENT_TARGETS:
        spec = get_incremental_target_spec(target)
        print(f"  - {spec.sql_function}(0, {watermark})")
    print("\nPhase 3 — Analytics replay")
    for target in ANALYTICS_TARGETS:
        spec = get_incremental_target_spec(target)
        print(f"  - {spec.sql_function}(0, {watermark})")
    print("\nPhase 4 — Periodic reconciliation")
    for target in PERIODIC_TARGETS:
        spec = get_periodic_target_spec(target)
        print(f"  - {spec.sql_function}()")
    print("\nPhase 5 — Checkpoints")
    print("  - Upsert refresher checkpoints for all current-state and analytics tables")
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
    print("\nCurrent-state rows affected:")
    for table, rows in result.current_tables_refreshed.items():
        print(f"  - {table}: {rows}")
    print("\nAnalytics rows affected:")
    for table, rows in result.analytics_tables_refreshed.items():
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
