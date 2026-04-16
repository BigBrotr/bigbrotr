"""Unit tests for ranker runtime helpers."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from bigbrotr.core.brotr import Brotr
from bigbrotr.services.ranker import RankCycleResult, Ranker, RankPhaseDurations, RankRowCounts
from bigbrotr.services.ranker.configs import RankerConfig
from bigbrotr.services.ranker.queries import GraphSyncCheckpoint
from bigbrotr.services.ranker.runtime import (
    cycle_cutoff_reason,
    emit_cycle_metrics,
    next_limited_batch_size,
    reset_cycle_metrics,
    sync_cutoff_reason,
)


if TYPE_CHECKING:
    from pathlib import Path


def _ranker_config(tmp_path: Path) -> RankerConfig:
    return RankerConfig.model_validate(
        {
            "storage": {
                "path": tmp_path / "ranker.duckdb",
                "checkpoint_path": tmp_path / "ranker.checkpoint.json",
            },
            "metrics": {"enabled": False},
        }
    )


class TestRankerRuntimeHelpers:
    def test_cycle_cutoff_reason_returns_duration_budget(self) -> None:
        assert (
            cycle_cutoff_reason(cycle_start=time.monotonic() - 2.0, max_duration=1.0)
            == "max_duration"
        )
        assert cycle_cutoff_reason(cycle_start=time.monotonic(), max_duration=1.0) is None

    def test_sync_cutoff_reason_prioritizes_cycle_then_sync_limits(self) -> None:
        assert (
            sync_cutoff_reason(
                cycle_start=time.monotonic() - 2.0,
                batches_processed=10,
                followers_synced=10,
                max_duration=1.0,
                max_batches=1,
                max_followers_per_cycle=1,
            )
            == "max_duration"
        )
        assert (
            sync_cutoff_reason(
                cycle_start=time.monotonic(),
                batches_processed=1,
                followers_synced=0,
                max_duration=None,
                max_batches=1,
                max_followers_per_cycle=None,
            )
            == "sync_max_batches"
        )
        assert (
            sync_cutoff_reason(
                cycle_start=time.monotonic(),
                batches_processed=0,
                followers_synced=1,
                max_duration=None,
                max_batches=None,
                max_followers_per_cycle=1,
            )
            == "sync_max_followers_per_cycle"
        )

    def test_next_limited_batch_size_respects_remaining_budget(self) -> None:
        assert next_limited_batch_size(batch_size=10, rows_processed=0, max_rows=None) == 10
        assert next_limited_batch_size(batch_size=10, rows_processed=5, max_rows=12) == 7
        assert next_limited_batch_size(batch_size=10, rows_processed=5, max_rows=5) == 0

    def test_reset_cycle_metrics_clears_representative_gauges(
        self,
        mock_brotr: Brotr,
        tmp_path: Path,
    ) -> None:
        ranker = Ranker(brotr=mock_brotr, config=_ranker_config(tmp_path))
        ranker.set_gauge = MagicMock()

        reset_cycle_metrics(ranker)

        emitted = {(call.args[0], call.args[1]) for call in ranker.set_gauge.call_args_list}
        assert ("sync_batches_processed", 0) in emitted
        assert ("export_pubkey_rows", 0) in emitted
        assert ("cleanup_removed_rank_runs", 0) in emitted
        assert ("cycle_cutoff_duration_budget", 0) in emitted

    def test_emit_cycle_metrics_records_result_fields(
        self,
        mock_brotr: Brotr,
        tmp_path: Path,
    ) -> None:
        ranker = Ranker(brotr=mock_brotr, config=_ranker_config(tmp_path))
        ranker.set_gauge = MagicMock()
        result = RankCycleResult(
            rank_run_id=5,
            changed_followers_synced=3,
            sync_batches_processed=2,
            graph_nodes=11,
            graph_edges=17,
            non_user_staged=RankRowCounts(event=4, addressable=5, identifier=6),
            rank_counts=RankRowCounts(pubkey=7, event=8, addressable=9, identifier=10),
            checkpoint=GraphSyncCheckpoint(source_seen_at=123, follower_pubkey="a" * 64),
            checkpoint_lag_seconds=99,
            duckdb_file_size_bytes=1234,
            rank_runs_failed_total=2,
            cleanup_removed_rank_runs=1,
            phase_durations=RankPhaseDurations(
                cleanup_seconds=0.1,
                sync_seconds=0.2,
                facts_stage_seconds=0.3,
                compute_seconds=0.4,
                export_seconds=0.5,
            ),
            cutoff_reason="sync_max_batches",
        )

        emit_cycle_metrics(ranker, result)

        emitted = {call.args[0]: call.args[1] for call in ranker.set_gauge.call_args_list}
        assert emitted["sync_batches_processed"] == 2
        assert emitted["facts_stage_identifier_rows"] == 6
        assert emitted["export_pubkey_rows"] == 7
        assert emitted["non_user_ranks_written"] == 27
        assert emitted["phase_duration_export_seconds"] == 0.5
        assert emitted["checkpoint_lag_seconds"] == 99
        assert emitted["duckdb_file_size_bytes"] == 1234
        assert emitted["cycle_cutoff_sync_budget"] == 1
        assert emitted["cycle_cutoff_stage_budget"] == 0
        assert emitted["cycle_cutoff_export_budget"] == 0
        assert emitted["cycle_cutoff_duration_budget"] == 0
