"""Integration tests for the ranker service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from bigbrotr.services.ranker import Ranker, RankerConfig
from bigbrotr.services.ranker.store import RankerStore


pytestmark = pytest.mark.integration


if TYPE_CHECKING:
    from pathlib import Path

    from bigbrotr.core.brotr import Brotr


async def _seed_contact_list(
    *,
    brotr: Brotr,
    follower_pubkey: str,
    source_event_id: str,
    source_created_at: int,
    source_seen_at: int,
    follow_count: int,
) -> None:
    await brotr.execute(
        """
        INSERT INTO contact_lists_current (
            follower_pubkey,
            source_event_id,
            source_created_at,
            source_seen_at,
            follow_count
        ) VALUES ($1, $2, $3, $4, $5)
        """,
        follower_pubkey,
        source_event_id,
        source_created_at,
        source_seen_at,
        follow_count,
    )


async def _seed_follow_edge(
    *,
    brotr: Brotr,
    follower_pubkey: str,
    followed_pubkey: str,
    source_event_id: str,
    source_created_at: int,
    source_seen_at: int,
) -> None:
    await brotr.execute(
        """
        INSERT INTO contact_list_edges_current (
            follower_pubkey,
            followed_pubkey,
            source_event_id,
            source_created_at,
            source_seen_at
        ) VALUES ($1, $2, $3, $4, $5)
        """,
        follower_pubkey,
        followed_pubkey,
        source_event_id,
        source_created_at,
        source_seen_at,
    )


async def _fetch_pubkey_ranks(
    *,
    brotr: Brotr,
    algorithm_id: str,
) -> list[dict[str, Any]]:
    rows = await brotr.fetch(
        """
        SELECT algorithm_id, subject_id, raw_score, rank, computed_at
        FROM nip85_pubkey_ranks
        WHERE algorithm_id = $1
        ORDER BY subject_id
        """,
        algorithm_id,
    )
    return [dict(row) for row in rows]


async def test_ranker_syncs_graph_and_exports_pubkey_ranks_snapshot(
    brotr: Brotr,
    tmp_path: Path,
) -> None:
    pubkey_a = "a" * 64
    pubkey_b = "b" * 64
    pubkey_c = "c" * 64
    pubkey_d = "d" * 64

    await _seed_contact_list(
        brotr=brotr,
        follower_pubkey=pubkey_a,
        source_event_id="evt-a-1",
        source_created_at=100,
        source_seen_at=10,
        follow_count=2,
    )
    await _seed_contact_list(
        brotr=brotr,
        follower_pubkey=pubkey_d,
        source_event_id="evt-d-1",
        source_created_at=200,
        source_seen_at=20,
        follow_count=1,
    )
    await _seed_follow_edge(
        brotr=brotr,
        follower_pubkey=pubkey_a,
        followed_pubkey=pubkey_b,
        source_event_id="evt-a-1",
        source_created_at=100,
        source_seen_at=10,
    )
    await _seed_follow_edge(
        brotr=brotr,
        follower_pubkey=pubkey_a,
        followed_pubkey=pubkey_c,
        source_event_id="evt-a-1",
        source_created_at=100,
        source_seen_at=10,
    )
    await _seed_follow_edge(
        brotr=brotr,
        follower_pubkey=pubkey_d,
        followed_pubkey=pubkey_a,
        source_event_id="evt-d-1",
        source_created_at=200,
        source_seen_at=20,
    )

    config = RankerConfig.model_validate(
        {
            "db": {
                "path": tmp_path / "ranker.duckdb",
                "checkpoint_path": tmp_path / "ranker.checkpoint.json",
            },
            "metrics": {"enabled": False},
            "sync": {"batch_size": 10},
            "export": {"batch_size": 2},
        }
    )

    service = Ranker(brotr=brotr, config=config)
    async with service:
        await service.run()

    store = RankerStore(config.db.path, config.db.checkpoint_path)
    stats = store.get_graph_stats()
    assert stats.node_count == 4
    assert stats.edge_count == 3
    assert store.load_checkpoint().source_seen_at == 20
    assert store.load_checkpoint().follower_pubkey == pubkey_d

    first_rows = await _fetch_pubkey_ranks(
        brotr=brotr,
        algorithm_id=config.algorithm_id,
    )
    assert [row["subject_id"] for row in first_rows] == [pubkey_a, pubkey_b, pubkey_c, pubkey_d]
    assert sum(float(row["raw_score"]) for row in first_rows) == pytest.approx(1.0, abs=1e-9)
    assert all(0 <= int(row["rank"]) <= 100 for row in first_rows)

    first_rank_map = {
        str(row["subject_id"]): (float(row["raw_score"]), int(row["rank"])) for row in first_rows
    }

    await brotr.execute(
        """
        INSERT INTO nip85_pubkey_ranks (algorithm_id, subject_id, raw_score, rank, computed_at)
        VALUES ($1, $2, $3, $4, $5)
        """,
        "other-pagerank-v1",
        pubkey_b,
        0.123,
        17,
        999,
    )

    service = Ranker(brotr=brotr, config=config)
    async with service:
        await service.run()

    second_rows = await _fetch_pubkey_ranks(
        brotr=brotr,
        algorithm_id=config.algorithm_id,
    )
    assert [row["subject_id"] for row in second_rows] == [pubkey_a, pubkey_b, pubkey_c, pubkey_d]
    for row in second_rows:
        raw_score, rank = first_rank_map[str(row["subject_id"])]
        assert float(row["raw_score"]) == pytest.approx(raw_score, abs=1e-12)
        assert int(row["rank"]) == rank

    await brotr.execute(
        """
        UPDATE contact_lists_current
        SET source_event_id = $2,
            source_created_at = $3,
            source_seen_at = $4,
            follow_count = $5
        WHERE follower_pubkey = $1
        """,
        pubkey_a,
        "evt-a-2",
        300,
        30,
        1,
    )
    await brotr.execute(
        "DELETE FROM contact_list_edges_current WHERE follower_pubkey = $1",
        pubkey_a,
    )
    await _seed_follow_edge(
        brotr=brotr,
        follower_pubkey=pubkey_a,
        followed_pubkey=pubkey_d,
        source_event_id="evt-a-2",
        source_created_at=300,
        source_seen_at=30,
    )

    service = Ranker(brotr=brotr, config=config)
    async with service:
        await service.run()

    stats = store.get_graph_stats()
    assert stats.node_count == 2
    assert stats.edge_count == 2
    assert store.load_checkpoint().source_seen_at == 30
    assert store.load_checkpoint().follower_pubkey == pubkey_a

    final_rows = await _fetch_pubkey_ranks(
        brotr=brotr,
        algorithm_id=config.algorithm_id,
    )
    assert [row["subject_id"] for row in final_rows] == [pubkey_a, pubkey_d]
    assert sum(float(row["raw_score"]) for row in final_rows) == pytest.approx(1.0, abs=1e-9)

    untouched_rows = await _fetch_pubkey_ranks(
        brotr=brotr,
        algorithm_id="other-pagerank-v1",
    )
    assert untouched_rows == [
        {
            "algorithm_id": "other-pagerank-v1",
            "subject_id": pubkey_b,
            "raw_score": 0.123,
            "rank": 17,
            "computed_at": 999,
        }
    ]
