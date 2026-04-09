"""Integration tests for the ranker service."""

from __future__ import annotations

from typing import TYPE_CHECKING

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


async def test_ranker_syncs_canonical_follow_graph_incrementally(
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
    assert stats.node_count == 4
    assert stats.edge_count == 2
    assert store.load_checkpoint().source_seen_at == 30
    assert store.load_checkpoint().follower_pubkey == pubkey_a
