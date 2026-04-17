"""Integration tests for the ranker service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from bigbrotr.services.ranker import Ranker, RankerConfig
from bigbrotr.services.ranker.queries import GraphSyncCheckpoint
from bigbrotr.services.ranker.utils import RankerStore


pytestmark = pytest.mark.integration


if TYPE_CHECKING:
    from pathlib import Path

    from bigbrotr.core.brotr import Brotr


_SCORE_FETCH_QUERIES = {
    "pubkey_score": """
        SELECT algorithm_id, pubkey AS subject_id, score
        FROM pubkey_score
        WHERE algorithm_id = $1
        ORDER BY pubkey
    """,
    "event_score": """
        SELECT algorithm_id, event_id AS subject_id, score
        FROM event_score
        WHERE algorithm_id = $1
        ORDER BY event_id
    """,
    "addressable_score": """
        SELECT algorithm_id, event_address AS subject_id, score
        FROM addressable_score
        WHERE algorithm_id = $1
        ORDER BY event_address
    """,
    "identifier_score": """
        SELECT algorithm_id, identifier AS subject_id, score
        FROM identifier_score
        WHERE algorithm_id = $1
        ORDER BY identifier
    """,
}


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


async def _seed_event_stats(
    *,
    brotr: Brotr,
    event_id: str,
    author_pubkey: str,
    comment_count: int,
    quote_count: int,
    repost_count: int,
    reaction_count: int,
    zap_count: int,
    zap_amount: int,
) -> None:
    await brotr.execute(
        """
        INSERT INTO nip85_event_stats (
            event_id,
            author_pubkey,
            comment_count,
            quote_count,
            repost_count,
            reaction_count,
            zap_count,
            zap_amount
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        event_id,
        author_pubkey,
        comment_count,
        quote_count,
        repost_count,
        reaction_count,
        zap_count,
        zap_amount,
    )


async def _seed_addressable_stats(
    *,
    brotr: Brotr,
    event_address: str,
    author_pubkey: str,
    comment_count: int,
    quote_count: int,
    repost_count: int,
    reaction_count: int,
    zap_count: int,
    zap_amount: int,
) -> None:
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
        event_address,
        author_pubkey,
        comment_count,
        quote_count,
        repost_count,
        reaction_count,
        zap_count,
        zap_amount,
    )


async def _seed_identifier_stats(
    *,
    brotr: Brotr,
    identifier: str,
    comment_count: int,
    reaction_count: int,
    k_tags: list[str],
) -> None:
    await brotr.execute(
        """
        INSERT INTO nip85_identifier_stats (identifier, comment_count, reaction_count, k_tags)
        VALUES ($1, $2, $3, $4::TEXT[])
        """,
        identifier,
        comment_count,
        reaction_count,
        k_tags,
    )


async def _fetch_score_rows(
    *,
    brotr: Brotr,
    table_name: str,
    algorithm_id: str,
) -> list[dict[str, Any]]:
    assert table_name in {
        "pubkey_score",
        "event_score",
        "addressable_score",
        "identifier_score",
    }
    rows = await brotr.fetch(_SCORE_FETCH_QUERIES[table_name], algorithm_id)
    return [dict(row) for row in rows]


async def test_ranker_syncs_graph_and_exports_pubkey_scores(  # noqa: PLR0915
    brotr: Brotr,
    tmp_path: Path,
) -> None:
    pubkey_a = "a" * 64
    pubkey_b = "b" * 64
    pubkey_c = "c" * 64
    pubkey_d = "d" * 64
    event_id = "11" * 32
    event_address = "30023:" + pubkey_a + ":article"
    identifier_a = "isbn:9780140328721"
    identifier_b = "geo:41.9028,12.4964"
    expected_identifier_subjects = sorted([identifier_a, identifier_b])

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
    await _seed_event_stats(
        brotr=brotr,
        event_id=event_id,
        author_pubkey=pubkey_a,
        comment_count=2,
        quote_count=1,
        repost_count=0,
        reaction_count=3,
        zap_count=1,
        zap_amount=2000,
    )
    await _seed_addressable_stats(
        brotr=brotr,
        event_address=event_address,
        author_pubkey=pubkey_a,
        comment_count=1,
        quote_count=0,
        repost_count=0,
        reaction_count=2,
        zap_count=0,
        zap_amount=0,
    )
    await _seed_identifier_stats(
        brotr=brotr,
        identifier=identifier_a,
        comment_count=3,
        reaction_count=1,
        k_tags=["book"],
    )
    await _seed_identifier_stats(
        brotr=brotr,
        identifier=identifier_b,
        comment_count=1,
        reaction_count=4,
        k_tags=["place", "city"],
    )

    config = RankerConfig.model_validate(
        {
            "storage": {
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

    store = RankerStore(config.storage.path, config.storage.checkpoint_path)
    stats = store.get_graph_stats()
    assert stats.node_count == 4
    assert stats.edge_count == 3
    assert store.load_checkpoint().source_seen_at == 20
    assert store.load_checkpoint().follower_pubkey == pubkey_d

    first_rows = await _fetch_score_rows(
        brotr=brotr,
        table_name="pubkey_score",
        algorithm_id=config.algorithm_id,
    )
    first_event_rows = await _fetch_score_rows(
        brotr=brotr,
        table_name="event_score",
        algorithm_id=config.algorithm_id,
    )
    first_addressable_rows = await _fetch_score_rows(
        brotr=brotr,
        table_name="addressable_score",
        algorithm_id=config.algorithm_id,
    )
    first_identifier_rows = await _fetch_score_rows(
        brotr=brotr,
        table_name="identifier_score",
        algorithm_id=config.algorithm_id,
    )

    assert [row["subject_id"] for row in first_rows] == [pubkey_a, pubkey_b, pubkey_c, pubkey_d]
    assert all(0.0 <= float(row["score"]) <= 100.0 for row in first_rows)
    assert [row["subject_id"] for row in first_event_rows] == [event_id]
    assert [row["subject_id"] for row in first_addressable_rows] == [event_address]
    assert [row["subject_id"] for row in first_identifier_rows] == expected_identifier_subjects
    assert all(0.0 < float(row["score"]) <= 100.0 for row in first_event_rows)
    assert all(0.0 < float(row["score"]) <= 100.0 for row in first_addressable_rows)
    assert all(0.0 < float(row["score"]) <= 100.0 for row in first_identifier_rows)

    first_score_map = {str(row["subject_id"]): float(row["score"]) for row in first_rows}

    await brotr.execute(
        """
        INSERT INTO pubkey_score (algorithm_id, pubkey, score)
        VALUES ($1, $2, $3)
        """,
        "other-pagerank",
        pubkey_b,
        0.123,
    )
    await brotr.execute(
        """
        INSERT INTO event_score (algorithm_id, event_id, score)
        VALUES ($1, $2, $3)
        """,
        "other-pagerank",
        event_id,
        0.456,
    )
    await brotr.execute(
        """
        INSERT INTO addressable_score (algorithm_id, event_address, score)
        VALUES ($1, $2, $3)
        """,
        "other-pagerank",
        event_address,
        0.789,
    )
    await brotr.execute(
        """
        INSERT INTO identifier_score (algorithm_id, identifier, score)
        VALUES ($1, $2, $3)
        """,
        "other-pagerank",
        identifier_a,
        0.222,
    )

    service = Ranker(brotr=brotr, config=config)
    async with service:
        await service.run()

    second_rows = await _fetch_score_rows(
        brotr=brotr,
        table_name="pubkey_score",
        algorithm_id=config.algorithm_id,
    )
    second_event_rows = await _fetch_score_rows(
        brotr=brotr,
        table_name="event_score",
        algorithm_id=config.algorithm_id,
    )
    second_addressable_rows = await _fetch_score_rows(
        brotr=brotr,
        table_name="addressable_score",
        algorithm_id=config.algorithm_id,
    )
    second_identifier_rows = await _fetch_score_rows(
        brotr=brotr,
        table_name="identifier_score",
        algorithm_id=config.algorithm_id,
    )
    assert [row["subject_id"] for row in second_rows] == [pubkey_a, pubkey_b, pubkey_c, pubkey_d]
    for row in second_rows:
        score = first_score_map[str(row["subject_id"])]
        assert float(row["score"]) == pytest.approx(score, abs=1e-12)
    assert second_event_rows == first_event_rows
    assert second_addressable_rows == first_addressable_rows
    assert second_identifier_rows == first_identifier_rows

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

    final_rows = await _fetch_score_rows(
        brotr=brotr,
        table_name="pubkey_score",
        algorithm_id=config.algorithm_id,
    )
    final_event_rows = await _fetch_score_rows(
        brotr=brotr,
        table_name="event_score",
        algorithm_id=config.algorithm_id,
    )
    final_addressable_rows = await _fetch_score_rows(
        brotr=brotr,
        table_name="addressable_score",
        algorithm_id=config.algorithm_id,
    )
    final_identifier_rows = await _fetch_score_rows(
        brotr=brotr,
        table_name="identifier_score",
        algorithm_id=config.algorithm_id,
    )
    assert [row["subject_id"] for row in final_rows] == [pubkey_a, pubkey_d]
    assert all(0.0 <= float(row["score"]) <= 100.0 for row in final_rows)
    assert [row["subject_id"] for row in final_event_rows] == [event_id]
    assert [row["subject_id"] for row in final_addressable_rows] == [event_address]
    assert [row["subject_id"] for row in final_identifier_rows] == expected_identifier_subjects
    assert all(0.0 <= float(row["score"]) <= 100.0 for row in final_event_rows)
    assert all(0.0 <= float(row["score"]) <= 100.0 for row in final_addressable_rows)
    assert all(0.0 <= float(row["score"]) <= 100.0 for row in final_identifier_rows)

    untouched_rows = await _fetch_score_rows(
        brotr=brotr,
        table_name="pubkey_score",
        algorithm_id="other-pagerank",
    )
    untouched_event_rows = await _fetch_score_rows(
        brotr=brotr,
        table_name="event_score",
        algorithm_id="other-pagerank",
    )
    untouched_addressable_rows = await _fetch_score_rows(
        brotr=brotr,
        table_name="addressable_score",
        algorithm_id="other-pagerank",
    )
    untouched_identifier_rows = await _fetch_score_rows(
        brotr=brotr,
        table_name="identifier_score",
        algorithm_id="other-pagerank",
    )
    assert untouched_rows == [
        {
            "algorithm_id": "other-pagerank",
            "subject_id": pubkey_b,
            "score": 0.123,
        }
    ]
    assert untouched_event_rows == [
        {
            "algorithm_id": "other-pagerank",
            "subject_id": event_id,
            "score": 0.456,
        }
    ]
    assert untouched_addressable_rows == [
        {
            "algorithm_id": "other-pagerank",
            "subject_id": event_address,
            "score": 0.789,
        }
    ]
    assert untouched_identifier_rows == [
        {
            "algorithm_id": "other-pagerank",
            "subject_id": identifier_a,
            "score": 0.222,
        }
    ]


async def test_ranker_sync_budget_resumes_from_checkpoint(
    brotr: Brotr,
    tmp_path: Path,
) -> None:
    pubkey_a = "a" * 64
    pubkey_b = "b" * 64

    await _seed_contact_list(
        brotr=brotr,
        follower_pubkey=pubkey_a,
        source_event_id="evt-a-1",
        source_created_at=100,
        source_seen_at=10,
        follow_count=1,
    )
    await _seed_contact_list(
        brotr=brotr,
        follower_pubkey=pubkey_b,
        source_event_id="evt-b-1",
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
        follower_pubkey=pubkey_b,
        followed_pubkey=pubkey_a,
        source_event_id="evt-b-1",
        source_created_at=200,
        source_seen_at=20,
    )

    config = RankerConfig.model_validate(
        {
            "algorithm_id": "bounded-pagerank",
            "storage": {
                "path": tmp_path / "ranker.duckdb",
                "checkpoint_path": tmp_path / "ranker.checkpoint.json",
            },
            "metrics": {"enabled": False},
            "sync": {"batch_size": 1, "max_batches": 1},
        }
    )

    service = Ranker(brotr=brotr, config=config)
    async with service:
        first_result = await service.rank()
    store = RankerStore(config.storage.path, config.storage.checkpoint_path)
    assert first_result.cutoff_reason == "sync_max_batches"
    assert first_result.rank_run_id is None
    assert first_result.changed_followers_synced == 1
    assert store.load_checkpoint() == GraphSyncCheckpoint(10, pubkey_a)
    assert (
        await _fetch_score_rows(
            brotr=brotr,
            table_name="pubkey_score",
            algorithm_id=config.algorithm_id,
        )
        == []
    )

    service = Ranker(brotr=brotr, config=config)
    async with service:
        second_result = await service.rank()
    assert second_result.cutoff_reason == "sync_max_batches"
    assert second_result.rank_run_id is None
    assert second_result.changed_followers_synced == 1
    assert store.load_checkpoint() == GraphSyncCheckpoint(20, pubkey_b)

    service = Ranker(brotr=brotr, config=config)
    async with service:
        final_result = await service.rank()
    final_rows = await _fetch_score_rows(
        brotr=brotr,
        table_name="pubkey_score",
        algorithm_id=config.algorithm_id,
    )
    assert final_result.cutoff_reason is None
    assert final_result.rank_run_id == 1
    assert [row["subject_id"] for row in final_rows] == [pubkey_a, pubkey_b]
    assert all(0.0 <= float(row["score"]) <= 100.0 for row in final_rows)
