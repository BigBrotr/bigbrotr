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


_RANK_FETCH_QUERIES = {
    "nip85_pubkey_ranks": """
        SELECT algorithm_id, subject_id, raw_score, rank, computed_at
        FROM nip85_pubkey_ranks
        WHERE algorithm_id = $1
        ORDER BY subject_id
    """,
    "nip85_event_ranks": """
        SELECT algorithm_id, subject_id, raw_score, rank, computed_at
        FROM nip85_event_ranks
        WHERE algorithm_id = $1
        ORDER BY subject_id
    """,
    "nip85_addressable_ranks": """
        SELECT algorithm_id, subject_id, raw_score, rank, computed_at
        FROM nip85_addressable_ranks
        WHERE algorithm_id = $1
        ORDER BY subject_id
    """,
    "nip85_identifier_ranks": """
        SELECT algorithm_id, subject_id, raw_score, rank, computed_at
        FROM nip85_identifier_ranks
        WHERE algorithm_id = $1
        ORDER BY subject_id
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


async def _fetch_rank_rows(
    *,
    brotr: Brotr,
    table_name: str,
    algorithm_id: str,
) -> list[dict[str, Any]]:
    assert table_name in {
        "nip85_pubkey_ranks",
        "nip85_event_ranks",
        "nip85_addressable_ranks",
        "nip85_identifier_ranks",
    }
    rows = await brotr.fetch(_RANK_FETCH_QUERIES[table_name], algorithm_id)
    return [dict(row) for row in rows]


async def test_ranker_syncs_graph_and_exports_pubkey_ranks_snapshot(  # noqa: PLR0915
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

    first_rows = await _fetch_rank_rows(
        brotr=brotr,
        table_name="nip85_pubkey_ranks",
        algorithm_id=config.algorithm_id,
    )
    first_event_rows = await _fetch_rank_rows(
        brotr=brotr,
        table_name="nip85_event_ranks",
        algorithm_id=config.algorithm_id,
    )
    first_addressable_rows = await _fetch_rank_rows(
        brotr=brotr,
        table_name="nip85_addressable_ranks",
        algorithm_id=config.algorithm_id,
    )
    first_identifier_rows = await _fetch_rank_rows(
        brotr=brotr,
        table_name="nip85_identifier_ranks",
        algorithm_id=config.algorithm_id,
    )

    assert [row["subject_id"] for row in first_rows] == [pubkey_a, pubkey_b, pubkey_c, pubkey_d]
    assert sum(float(row["raw_score"]) for row in first_rows) == pytest.approx(1.0, abs=1e-9)
    assert all(0 <= int(row["rank"]) <= 100 for row in first_rows)
    assert [row["subject_id"] for row in first_event_rows] == [event_id]
    assert [row["subject_id"] for row in first_addressable_rows] == [event_address]
    assert [row["subject_id"] for row in first_identifier_rows] == [identifier_a, identifier_b]
    assert all(float(row["raw_score"]) > 0.0 for row in first_event_rows)
    assert all(float(row["raw_score"]) > 0.0 for row in first_addressable_rows)
    assert all(float(row["raw_score"]) > 0.0 for row in first_identifier_rows)
    assert all(0 <= int(row["rank"]) <= 100 for row in first_event_rows)
    assert all(0 <= int(row["rank"]) <= 100 for row in first_addressable_rows)
    assert all(0 <= int(row["rank"]) <= 100 for row in first_identifier_rows)

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
    await brotr.execute(
        """
        INSERT INTO nip85_event_ranks (algorithm_id, subject_id, raw_score, rank, computed_at)
        VALUES ($1, $2, $3, $4, $5)
        """,
        "other-pagerank-v1",
        event_id,
        0.456,
        23,
        999,
    )
    await brotr.execute(
        """
        INSERT INTO nip85_addressable_ranks (algorithm_id, subject_id, raw_score, rank, computed_at)
        VALUES ($1, $2, $3, $4, $5)
        """,
        "other-pagerank-v1",
        event_address,
        0.789,
        31,
        999,
    )
    await brotr.execute(
        """
        INSERT INTO nip85_identifier_ranks (algorithm_id, subject_id, raw_score, rank, computed_at)
        VALUES ($1, $2, $3, $4, $5)
        """,
        "other-pagerank-v1",
        identifier_a,
        0.222,
        19,
        999,
    )

    service = Ranker(brotr=brotr, config=config)
    async with service:
        await service.run()

    second_rows = await _fetch_rank_rows(
        brotr=brotr,
        table_name="nip85_pubkey_ranks",
        algorithm_id=config.algorithm_id,
    )
    second_event_rows = await _fetch_rank_rows(
        brotr=brotr,
        table_name="nip85_event_ranks",
        algorithm_id=config.algorithm_id,
    )
    second_addressable_rows = await _fetch_rank_rows(
        brotr=brotr,
        table_name="nip85_addressable_ranks",
        algorithm_id=config.algorithm_id,
    )
    second_identifier_rows = await _fetch_rank_rows(
        brotr=brotr,
        table_name="nip85_identifier_ranks",
        algorithm_id=config.algorithm_id,
    )
    assert [row["subject_id"] for row in second_rows] == [pubkey_a, pubkey_b, pubkey_c, pubkey_d]
    for row in second_rows:
        raw_score, rank = first_rank_map[str(row["subject_id"])]
        assert float(row["raw_score"]) == pytest.approx(raw_score, abs=1e-12)
        assert int(row["rank"]) == rank
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

    final_rows = await _fetch_rank_rows(
        brotr=brotr,
        table_name="nip85_pubkey_ranks",
        algorithm_id=config.algorithm_id,
    )
    final_event_rows = await _fetch_rank_rows(
        brotr=brotr,
        table_name="nip85_event_ranks",
        algorithm_id=config.algorithm_id,
    )
    final_addressable_rows = await _fetch_rank_rows(
        brotr=brotr,
        table_name="nip85_addressable_ranks",
        algorithm_id=config.algorithm_id,
    )
    final_identifier_rows = await _fetch_rank_rows(
        brotr=brotr,
        table_name="nip85_identifier_ranks",
        algorithm_id=config.algorithm_id,
    )
    assert [row["subject_id"] for row in final_rows] == [pubkey_a, pubkey_d]
    assert sum(float(row["raw_score"]) for row in final_rows) == pytest.approx(1.0, abs=1e-9)
    assert [row["subject_id"] for row in final_event_rows] == [event_id]
    assert [row["subject_id"] for row in final_addressable_rows] == [event_address]
    assert [row["subject_id"] for row in final_identifier_rows] == [identifier_a, identifier_b]
    assert all(0 <= int(row["rank"]) <= 100 for row in final_event_rows)
    assert all(0 <= int(row["rank"]) <= 100 for row in final_addressable_rows)
    assert all(0 <= int(row["rank"]) <= 100 for row in final_identifier_rows)

    untouched_rows = await _fetch_rank_rows(
        brotr=brotr,
        table_name="nip85_pubkey_ranks",
        algorithm_id="other-pagerank-v1",
    )
    untouched_event_rows = await _fetch_rank_rows(
        brotr=brotr,
        table_name="nip85_event_ranks",
        algorithm_id="other-pagerank-v1",
    )
    untouched_addressable_rows = await _fetch_rank_rows(
        brotr=brotr,
        table_name="nip85_addressable_ranks",
        algorithm_id="other-pagerank-v1",
    )
    untouched_identifier_rows = await _fetch_rank_rows(
        brotr=brotr,
        table_name="nip85_identifier_ranks",
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
    assert untouched_event_rows == [
        {
            "algorithm_id": "other-pagerank-v1",
            "subject_id": event_id,
            "raw_score": 0.456,
            "rank": 23,
            "computed_at": 999,
        }
    ]
    assert untouched_addressable_rows == [
        {
            "algorithm_id": "other-pagerank-v1",
            "subject_id": event_address,
            "raw_score": 0.789,
            "rank": 31,
            "computed_at": 999,
        }
    ]
    assert untouched_identifier_rows == [
        {
            "algorithm_id": "other-pagerank-v1",
            "subject_id": identifier_a,
            "raw_score": 0.222,
            "rank": 19,
            "computed_at": 999,
        }
    ]
