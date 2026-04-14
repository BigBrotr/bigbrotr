"""Unit tests for the ranker service package."""

from __future__ import annotations

import math
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import duckdb
import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models.constants import ServiceName
from bigbrotr.services.ranker import RankCycleResult, Ranker, RankerConfig, RankRowCounts
from bigbrotr.services.ranker.queries import (
    AddressableStatFact,
    ContactListFact,
    EventStatFact,
    FollowEdgeFact,
    GraphSyncCheckpoint,
    IdentifierStatFact,
    RankExportRow,
    create_rank_stages,
    fetch_addressable_stats,
    fetch_changed_contact_lists,
    fetch_event_stats,
    fetch_follow_edges_for_followers,
    fetch_identifier_stats,
    get_contact_list_source_watermark,
    insert_rank_stage_batch,
    merge_rank_stage,
)
from bigbrotr.services.ranker.utils import RankerStore


def _reference_pagerank(
    *,
    nodes: tuple[str, ...],
    edges: tuple[tuple[str, str], ...],
    damping: float,
    iterations: int,
    ignore_self_follows: bool,
) -> dict[str, float]:
    filtered_edges = tuple(
        (follower, followed)
        for follower, followed in edges
        if not ignore_self_follows or follower != followed
    )
    out_degree = {
        node: sum(1 for follower, _ in filtered_edges if follower == node) for node in nodes
    }
    node_count = len(nodes)
    scores = dict.fromkeys(nodes, 1.0 / node_count)

    for _ in range(iterations):
        dangling_mass = sum(score for node, score in scores.items() if out_degree.get(node, 0) == 0)
        next_scores = dict.fromkeys(
            nodes,
            ((1.0 - damping) / node_count) + (damping * dangling_mass / node_count),
        )
        for follower, followed in filtered_edges:
            next_scores[followed] += damping * scores[follower] / out_degree[follower]
        scores = next_scores

    return scores


def _normalize_rank(*, raw_score: float, node_count: int) -> int:
    return round(min(25 * math.log10((raw_score / (1.0 / node_count)) + 1.0), 100.0))


def _non_user_event_raw(
    *,
    comment_count: int,
    quote_count: int,
    repost_count: int,
    reaction_count: int,
    zap_count: int,
    zap_amount: int,
) -> float:
    return (
        4.0 * math.log1p(comment_count)
        + 5.0 * math.log1p(quote_count)
        + 3.0 * math.log1p(repost_count)
        + 1.0 * math.log1p(reaction_count)
        + 3.0 * math.log1p(zap_count)
        + 2.0 * math.log1p(zap_amount / 1000.0)
    )


def _non_user_identifier_raw(*, comment_count: int, reaction_count: int) -> float:
    return 4.0 * math.log1p(comment_count) + 1.0 * math.log1p(reaction_count)


def _author_multiplier(*, author_rank: int) -> float:
    return 0.5 + (0.5 * author_rank / 100.0)


def _normalize_non_user_rank(*, raw_score: float, all_raw_scores: list[float]) -> int:
    positive_scores = [score for score in all_raw_scores if score > 0.0]
    if raw_score <= 0.0 or not positive_scores:
        return 0

    avg_positive_raw = sum(positive_scores) / len(positive_scores)
    return round(min(25 * math.log10((raw_score / avg_positive_raw) + 1.0), 100.0))


class TestRankerQueries:
    @pytest.mark.asyncio
    async def test_fetch_changed_contact_lists_maps_rows(self) -> None:
        brotr = MagicMock(spec=Brotr)
        brotr.fetch = AsyncMock(
            return_value=[
                {
                    "follower_pubkey": "a" * 64,
                    "source_event_id": "evt-a",
                    "source_created_at": 100,
                    "source_seen_at": 10,
                    "follow_count": 2,
                }
            ]
        )

        rows = await fetch_changed_contact_lists(brotr, GraphSyncCheckpoint(9, "z"), 5)

        assert rows == [ContactListFact("a" * 64, "evt-a", 100, 10, 2)]
        brotr.fetch.assert_awaited_once()
        assert brotr.fetch.await_args.args[1:] == (9, "z", 5)

    @pytest.mark.asyncio
    async def test_fetch_follow_edges_skips_empty_followers(self) -> None:
        brotr = MagicMock(spec=Brotr)
        brotr.fetch = AsyncMock()

        assert await fetch_follow_edges_for_followers(brotr, []) == []
        brotr.fetch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fetch_follow_edges_maps_rows(self) -> None:
        brotr = MagicMock(spec=Brotr)
        brotr.fetch = AsyncMock(
            return_value=[
                {
                    "follower_pubkey": "a" * 64,
                    "followed_pubkey": "b" * 64,
                    "source_event_id": "evt-a",
                    "source_created_at": 100,
                    "source_seen_at": 10,
                }
            ]
        )

        rows = await fetch_follow_edges_for_followers(brotr, ["a" * 64])

        assert rows == [FollowEdgeFact("a" * 64, "b" * 64, "evt-a", 100, 10)]
        assert brotr.fetch.await_args.args[1] == ["a" * 64]

    @pytest.mark.asyncio
    async def test_fetch_non_user_fact_rows(self) -> None:
        brotr = MagicMock(spec=Brotr)
        brotr.fetch = AsyncMock(
            side_effect=[
                [
                    {
                        "event_id": "11" * 32,
                        "author_pubkey": "a" * 64,
                        "comment_count": 1,
                        "quote_count": 2,
                        "repost_count": 3,
                        "reaction_count": 4,
                        "zap_count": 5,
                        "zap_amount": 6000,
                    }
                ],
                [
                    {
                        "event_address": "30023:aa:alpha",
                        "author_pubkey": "a" * 64,
                        "comment_count": 1,
                        "quote_count": 2,
                        "repost_count": 3,
                        "reaction_count": 4,
                        "zap_count": 5,
                        "zap_amount": 6000,
                    }
                ],
                [
                    {
                        "identifier": "isbn:9780140328721",
                        "comment_count": 3,
                        "reaction_count": 4,
                        "k_tags": ["book", "fiction"],
                    }
                ],
            ]
        )

        assert await fetch_event_stats(brotr, "", 10) == [
            EventStatFact("11" * 32, "a" * 64, 1, 2, 3, 4, 5, 6000)
        ]
        assert await fetch_addressable_stats(brotr, "", 10) == [
            AddressableStatFact("30023:aa:alpha", "a" * 64, 1, 2, 3, 4, 5, 6000)
        ]
        assert await fetch_identifier_stats(brotr, "", 10) == [
            IdentifierStatFact("isbn:9780140328721", 3, 4, ("book", "fiction"))
        ]

    @pytest.mark.asyncio
    async def test_get_contact_list_source_watermark(self) -> None:
        brotr = MagicMock(spec=Brotr)
        brotr.fetchval = AsyncMock(return_value=1234)

        assert await get_contact_list_source_watermark(brotr) == 1234
        brotr.fetchval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rank_stage_helpers_use_subject_specific_queries(self) -> None:
        conn = MagicMock()
        conn.execute = AsyncMock()

        await create_rank_stages(conn)
        assert conn.execute.await_count == 4

        conn.execute.reset_mock()
        await insert_rank_stage_batch(conn, "event", [], 1234)
        conn.execute.assert_not_awaited()

        rows = [
            RankExportRow("11" * 32, 0.75, 88),
            RankExportRow("22" * 32, 0.25, 44),
        ]
        await insert_rank_stage_batch(conn, "event", rows, 1234)
        conn.execute.assert_awaited_once()
        assert conn.execute.await_args.args[1:] == (
            ["11" * 32, "22" * 32],
            [0.75, 0.25],
            [88, 44],
            1234,
        )

        conn.execute.reset_mock()
        await merge_rank_stage(conn, "event", "global-pagerank")
        assert conn.execute.await_count == 2
        assert [await_call.args[1] for await_call in conn.execute.await_args_list] == [
            "global-pagerank",
            "global-pagerank",
        ]


class TestRankerConfig:
    def test_default_values(self) -> None:
        config = RankerConfig()

        assert config.algorithm_id == "global-pagerank"
        assert config.storage.path == Path("/app/data/ranker.duckdb")
        assert config.storage.checkpoint_path == Path("/app/data/ranker.checkpoint.json")
        assert config.processing.max_duration is None
        assert config.graph.damping == pytest.approx(0.85)
        assert config.graph.iterations == 20
        assert config.graph.ignore_self_follows is True
        assert config.sync.batch_size == 1000
        assert config.sync.max_batches is None
        assert config.sync.max_followers_per_cycle is None
        assert config.facts_stage.batch_size == 1000
        assert config.facts_stage.max_event_rows is None
        assert config.facts_stage.max_addressable_rows is None
        assert config.facts_stage.max_identifier_rows is None
        assert config.export.batch_size == 1000
        assert config.export.max_batches_per_subject is None
        assert config.cleanup.rank_runs_retention == 100
        assert config.interval == 3600.0

    def test_custom_nested_values(self, tmp_path: Path) -> None:
        config = RankerConfig.model_validate(
            {
                "algorithm_id": "custom-ranker",
                "storage": {
                    "path": tmp_path / "graph.duckdb",
                    "checkpoint_path": tmp_path / "graph.checkpoint.json",
                },
                "processing": {"max_duration": 600.0},
                "graph": {"damping": 0.9, "iterations": 40, "ignore_self_follows": False},
                "sync": {
                    "batch_size": 250,
                    "max_batches": 3,
                    "max_followers_per_cycle": 750,
                },
                "facts_stage": {
                    "batch_size": 300,
                    "max_event_rows": 1000,
                    "max_addressable_rows": 2000,
                    "max_identifier_rows": 3000,
                },
                "export": {"batch_size": 500, "max_batches_per_subject": 4},
                "cleanup": {"rank_runs_retention": 25},
                "interval": 7200.0,
            }
        )

        assert config.algorithm_id == "custom-ranker"
        assert config.storage.path == tmp_path / "graph.duckdb"
        assert config.storage.checkpoint_path == tmp_path / "graph.checkpoint.json"
        assert config.processing.max_duration == 600.0
        assert config.graph.damping == pytest.approx(0.9)
        assert config.graph.iterations == 40
        assert config.graph.ignore_self_follows is False
        assert config.sync.batch_size == 250
        assert config.sync.max_batches == 3
        assert config.sync.max_followers_per_cycle == 750
        assert config.facts_stage.batch_size == 300
        assert config.facts_stage.max_event_rows == 1000
        assert config.facts_stage.max_addressable_rows == 2000
        assert config.facts_stage.max_identifier_rows == 3000
        assert config.export.batch_size == 500
        assert config.export.max_batches_per_subject == 4
        assert config.cleanup.rank_runs_retention == 25
        assert config.interval == 7200.0

    def test_invalid_algorithm_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="algorithm_id must match"):
            RankerConfig(algorithm_id="Global PageRank")


class TestRankerStore:
    def test_ensure_initialized_creates_schema_and_checkpoint(self, tmp_path: Path) -> None:
        store = RankerStore(
            db_path=tmp_path / "ranker.duckdb",
            checkpoint_path=tmp_path / "ranker.checkpoint.json",
        )

        store.ensure_initialized()

        assert store.load_checkpoint() == GraphSyncCheckpoint()

        with duckdb.connect(str(tmp_path / "ranker.duckdb")) as conn:
            tables = {name for (name,) in conn.execute("SHOW TABLES").fetchall()}

        assert tables >= {
            "pubkey_nodes",
            "contact_lists_current",
            "follow_edges_current",
            "pagerank_curr",
            "pagerank_next",
            "rank_runs",
            "nip85_event_stats_stage",
            "nip85_addressable_stats_stage",
            "nip85_identifier_stats_stage",
            "nip85_event_ranks_curr",
            "nip85_addressable_ranks_curr",
            "nip85_identifier_ranks_curr",
        }

    def test_apply_follow_graph_delta_replaces_edges_and_preserves_nodes(
        self, tmp_path: Path
    ) -> None:
        store = RankerStore(
            db_path=tmp_path / "ranker.duckdb",
            checkpoint_path=tmp_path / "ranker.checkpoint.json",
        )
        store.ensure_initialized()

        first_checkpoint = GraphSyncCheckpoint(source_seen_at=10, follower_pubkey="a" * 64)
        store.apply_follow_graph_delta(
            changed_lists=[
                ContactListFact("a" * 64, "evt-a-1", 100, 10, 2),
                ContactListFact("d" * 64, "evt-d-1", 200, 20, 1),
            ],
            edges=[
                FollowEdgeFact("a" * 64, "b" * 64, "evt-a-1", 100, 10),
                FollowEdgeFact("a" * 64, "c" * 64, "evt-a-1", 100, 10),
                FollowEdgeFact("d" * 64, "a" * 64, "evt-d-1", 200, 20),
            ],
            checkpoint=first_checkpoint,
        )

        assert store.get_graph_stats().node_count == 4
        assert store.get_graph_stats().edge_count == 3
        assert store.load_checkpoint() == first_checkpoint

        second_checkpoint = GraphSyncCheckpoint(source_seen_at=30, follower_pubkey="a" * 64)
        store.apply_follow_graph_delta(
            changed_lists=[
                ContactListFact("a" * 64, "evt-a-2", 300, 30, 1),
            ],
            edges=[
                FollowEdgeFact("a" * 64, "d" * 64, "evt-a-2", 300, 30),
            ],
            checkpoint=second_checkpoint,
        )

        stats = store.get_graph_stats()
        assert stats.node_count == 2
        assert stats.edge_count == 2
        assert store.load_checkpoint() == second_checkpoint

        with duckdb.connect(str(tmp_path / "ranker.duckdb")) as conn:
            rows = conn.execute(
                """
                SELECT p1.pubkey, p2.pubkey
                FROM follow_edges_current AS e
                INNER JOIN pubkey_nodes AS p1 ON p1.node_id = e.follower_node_id
                INNER JOIN pubkey_nodes AS p2 ON p2.node_id = e.followed_node_id
                ORDER BY p1.pubkey, p2.pubkey
                """
            ).fetchall()
            node_rows = conn.execute("SELECT COUNT(*) FROM pubkey_nodes").fetchone()

        assert rows == [
            ("a" * 64, "d" * 64),
            ("d" * 64, "a" * 64),
        ]
        assert node_rows == (4,)

    def test_compute_pubkey_pagerank_matches_reference_and_export_order(
        self, tmp_path: Path
    ) -> None:
        store = RankerStore(
            db_path=tmp_path / "ranker.duckdb",
            checkpoint_path=tmp_path / "ranker.checkpoint.json",
        )
        store.ensure_initialized()

        pubkey_a = "a" * 64
        pubkey_b = "b" * 64
        pubkey_c = "c" * 64
        pubkey_d = "d" * 64

        store.apply_follow_graph_delta(
            changed_lists=[
                ContactListFact(pubkey_a, "evt-a-1", 100, 10, 1),
                ContactListFact(pubkey_b, "evt-b-1", 110, 11, 1),
                ContactListFact(pubkey_c, "evt-c-1", 120, 12, 1),
                ContactListFact(pubkey_d, "evt-d-1", 130, 13, 1),
            ],
            edges=[
                FollowEdgeFact(pubkey_a, pubkey_b, "evt-a-1", 100, 10),
                FollowEdgeFact(pubkey_b, pubkey_c, "evt-b-1", 110, 11),
                FollowEdgeFact(pubkey_c, pubkey_a, "evt-c-1", 120, 12),
                FollowEdgeFact(pubkey_d, pubkey_d, "evt-d-1", 130, 13),
            ],
            checkpoint=GraphSyncCheckpoint(source_seen_at=13, follower_pubkey=pubkey_d),
        )

        store.compute_pubkey_pagerank(
            damping=0.85,
            iterations=20,
            ignore_self_follows=True,
        )

        rows = store.fetch_pubkey_rank_batch(after_subject_id="", limit=10)
        assert [row.subject_id for row in rows] == [pubkey_a, pubkey_b, pubkey_c, pubkey_d]

        expected = _reference_pagerank(
            nodes=(pubkey_a, pubkey_b, pubkey_c, pubkey_d),
            edges=(
                (pubkey_a, pubkey_b),
                (pubkey_b, pubkey_c),
                (pubkey_c, pubkey_a),
                (pubkey_d, pubkey_d),
            ),
            damping=0.85,
            iterations=20,
            ignore_self_follows=True,
        )

        for row in rows:
            assert row.raw_score == pytest.approx(expected[row.subject_id], rel=1e-9, abs=1e-9)
            assert row.rank == _normalize_rank(raw_score=row.raw_score, node_count=4)

        assert sum(row.raw_score for row in rows) == pytest.approx(1.0, rel=1e-9, abs=1e-9)
        assert rows[3].subject_id == pubkey_d
        assert rows[3].raw_score < rows[0].raw_score

    def test_start_and_finish_rank_run(self, tmp_path: Path) -> None:
        store = RankerStore(
            db_path=tmp_path / "ranker.duckdb",
            checkpoint_path=tmp_path / "ranker.checkpoint.json",
        )
        run = store.start_rank_run(
            algorithm_id="global-pagerank",
            node_count=4,
            edge_count=3,
        )
        store.finish_rank_run(run.run_id, status="success")

        with duckdb.connect(str(tmp_path / "ranker.duckdb")) as conn:
            row = conn.execute(
                """
                SELECT algorithm_id, status, node_count, edge_count, finished_at
                FROM rank_runs
                WHERE run_id = ?
                """,
                [run.run_id],
            ).fetchone()

        assert row is not None
        assert row[0] == "global-pagerank"
        assert row[1] == "success"
        assert row[2] == 4
        assert row[3] == 3
        assert row[4] is not None

    def test_rank_run_retention_cleanup(self, tmp_path: Path) -> None:
        store = RankerStore(
            db_path=tmp_path / "ranker.duckdb",
            checkpoint_path=tmp_path / "ranker.checkpoint.json",
        )
        for index in range(5):
            run = store.start_rank_run(
                algorithm_id="global-pagerank",
                node_count=index,
                edge_count=index,
            )
            store.finish_rank_run(run.run_id, status="failed" if index == 0 else "success")

        assert store.count_rank_runs() == 5
        assert store.count_rank_runs(status="failed") == 1
        assert store.delete_rank_runs_older_than_retention(2) == 3
        assert store.count_rank_runs() == 2
        assert store.count_rank_runs(status="failed") == 0
        assert store.delete_rank_runs_older_than_retention(None) == 0

    def test_store_empty_edge_cases_are_noops(self, tmp_path: Path) -> None:
        store = RankerStore(
            db_path=tmp_path / "ranker.duckdb",
            checkpoint_path=tmp_path / "ranker.checkpoint.json",
        )

        assert store.load_checkpoint() == GraphSyncCheckpoint()
        assert store.duckdb_file_size_bytes() == 0

        checkpoint = GraphSyncCheckpoint(source_seen_at=42, follower_pubkey="a" * 64)
        store.apply_follow_graph_delta(changed_lists=[], edges=[], checkpoint=checkpoint)
        assert store.load_checkpoint() == checkpoint

        store.append_event_stats_stage_batch([])
        store.append_addressable_stats_stage_batch([])
        store.append_identifier_stats_stage_batch([])

        with duckdb.connect(str(tmp_path / "ranker.duckdb")) as conn:
            assert store._ensure_node_ids(conn, []) == {}
            store._delete_followers(conn, [])

    def test_compute_non_user_ranks_matches_formulas_and_normalization(
        self, tmp_path: Path
    ) -> None:
        store = RankerStore(
            db_path=tmp_path / "ranker.duckdb",
            checkpoint_path=tmp_path / "ranker.checkpoint.json",
        )
        store.ensure_initialized()

        authors = [f"{i:064x}" for i in range(1, 11)]
        pagerank_scores = [0.7, 0.1, 0.05, 0.03, 0.03, 0.03, 0.02, 0.02, 0.01, 0.01]

        with duckdb.connect(str(tmp_path / "ranker.duckdb")) as conn:
            conn.executemany(
                "INSERT INTO pubkey_nodes (node_id, pubkey) VALUES (?, ?)",
                [(index, pubkey) for index, pubkey in enumerate(authors, start=1)],
            )
            conn.executemany(
                "INSERT INTO pagerank_curr (node_id, raw_score) VALUES (?, ?)",
                [(index, raw_score) for index, raw_score in enumerate(pagerank_scores, start=1)],
            )

        store.append_event_stats_stage_batch(
            [
                EventStatFact("11" * 32, authors[0], 9, 4, 1, 16, 2, 5000),
                EventStatFact("22" * 32, authors[1], 2, 1, 0, 3, 0, 0),
            ]
        )
        store.append_addressable_stats_stage_batch(
            [
                AddressableStatFact("30023:aa:alpha", authors[0], 6, 2, 1, 4, 1, 3000),
                AddressableStatFact("30023:bb:beta", "ff" * 32, 2, 0, 0, 1, 0, 0),
            ]
        )
        store.append_identifier_stats_stage_batch(
            [
                IdentifierStatFact("isbn:9780140328721", 5, 2, ("book", "fiction")),
                IdentifierStatFact("isbn:9788806229645", 1, 9, ("book",)),
            ]
        )

        store.compute_non_user_ranks()

        node_count = len(authors)
        author_ranks = {
            authors[index]: _normalize_rank(raw_score=raw_score, node_count=node_count)
            for index, raw_score in enumerate(pagerank_scores)
        }

        expected_event_raw_scores = {
            "11" * 32: _non_user_event_raw(
                comment_count=9,
                quote_count=4,
                repost_count=1,
                reaction_count=16,
                zap_count=2,
                zap_amount=5000,
            )
            * _author_multiplier(author_rank=author_ranks[authors[0]]),
            "22" * 32: _non_user_event_raw(
                comment_count=2,
                quote_count=1,
                repost_count=0,
                reaction_count=3,
                zap_count=0,
                zap_amount=0,
            )
            * _author_multiplier(author_rank=author_ranks[authors[1]]),
        }
        expected_addressable_raw_scores = {
            "30023:aa:alpha": _non_user_event_raw(
                comment_count=6,
                quote_count=2,
                repost_count=1,
                reaction_count=4,
                zap_count=1,
                zap_amount=3000,
            )
            * _author_multiplier(author_rank=author_ranks[authors[0]]),
            "30023:bb:beta": _non_user_event_raw(
                comment_count=2,
                quote_count=0,
                repost_count=0,
                reaction_count=1,
                zap_count=0,
                zap_amount=0,
            )
            * _author_multiplier(author_rank=0),
        }
        expected_identifier_raw_scores = {
            "isbn:9780140328721": _non_user_identifier_raw(comment_count=5, reaction_count=2),
            "isbn:9788806229645": _non_user_identifier_raw(comment_count=1, reaction_count=9),
        }

        event_rows = store.fetch_event_rank_batch(after_subject_id="", limit=10)
        addressable_rows = store.fetch_addressable_rank_batch(after_subject_id="", limit=10)
        identifier_rows = store.fetch_identifier_rank_batch(after_subject_id="", limit=10)

        assert [row.subject_id for row in event_rows] == ["11" * 32, "22" * 32]
        assert [row.subject_id for row in addressable_rows] == [
            "30023:aa:alpha",
            "30023:bb:beta",
        ]
        assert [row.subject_id for row in identifier_rows] == [
            "isbn:9780140328721",
            "isbn:9788806229645",
        ]

        for row in event_rows:
            assert row.raw_score == pytest.approx(
                expected_event_raw_scores[row.subject_id], rel=1e-9, abs=1e-9
            )
            assert row.rank == _normalize_non_user_rank(
                raw_score=row.raw_score,
                all_raw_scores=list(expected_event_raw_scores.values()),
            )

        for row in addressable_rows:
            assert row.raw_score == pytest.approx(
                expected_addressable_raw_scores[row.subject_id], rel=1e-9, abs=1e-9
            )
            assert row.rank == _normalize_non_user_rank(
                raw_score=row.raw_score,
                all_raw_scores=list(expected_addressable_raw_scores.values()),
            )

        for row in identifier_rows:
            assert row.raw_score == pytest.approx(
                expected_identifier_raw_scores[row.subject_id], rel=1e-9, abs=1e-9
            )
            assert row.rank == _normalize_non_user_rank(
                raw_score=row.raw_score,
                all_raw_scores=list(expected_identifier_raw_scores.values()),
            )


@pytest.fixture
def ranker_config(tmp_path: Path) -> RankerConfig:
    return RankerConfig.model_validate(
        {
            "storage": {
                "path": tmp_path / "ranker.duckdb",
                "checkpoint_path": tmp_path / "ranker.checkpoint.json",
            },
            "metrics": {"enabled": False},
            "sync": {"batch_size": 2},
        }
    )


class TestRankerService:
    def test_init_with_defaults(self, mock_brotr: Brotr) -> None:
        ranker = Ranker(brotr=mock_brotr)

        assert ranker.SERVICE_NAME == ServiceName.RANKER
        assert ranker.CONFIG_CLASS is RankerConfig
        assert ranker.config.algorithm_id == "global-pagerank"

    @pytest.mark.asyncio
    async def test_run_delegates_to_rank(
        self,
        mock_brotr: Brotr,
        ranker_config: RankerConfig,
    ) -> None:
        ranker = Ranker(brotr=mock_brotr, config=ranker_config)
        cycle_result = RankCycleResult(
            rank_run_id=1,
            changed_followers_synced=0,
            graph_nodes=0,
            graph_edges=0,
            non_user_staged=RankRowCounts(),
            rank_counts=RankRowCounts(),
            checkpoint=GraphSyncCheckpoint(),
            duckdb_file_size_bytes=0,
        )

        with patch.object(ranker, "rank", AsyncMock(return_value=cycle_result)) as mock_rank:
            await ranker.run()

        mock_rank.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_rank_does_not_invoke_cleanup(
        self,
        mock_brotr: Brotr,
        ranker_config: RankerConfig,
    ) -> None:
        from bigbrotr.services.ranker.service import _GraphSyncResult

        ranker = Ranker(brotr=mock_brotr, config=ranker_config)
        cycle_result = RankCycleResult(
            rank_run_id=None,
            checkpoint=GraphSyncCheckpoint(),
            cutoff_reason="max_duration",
        )

        with (
            patch.object(ranker, "cleanup", AsyncMock(return_value=3)) as mock_cleanup,
            patch.object(ranker._store, "ensure_initialized"),
            patch.object(ranker, "_reset_cycle_metrics"),
            patch.object(
                ranker,
                "_sync_follow_graph",
                AsyncMock(
                    return_value=_GraphSyncResult(
                        checkpoint=GraphSyncCheckpoint(),
                        cutoff_reason="max_duration",
                    )
                ),
            ),
            patch.object(ranker, "_build_cycle_result", AsyncMock(return_value=cycle_result)),
        ):
            result = await ranker.rank()

        assert result is cycle_result
        mock_cleanup.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_run_syncs_changed_followers(
        self,
        mock_brotr: Brotr,
        ranker_config: RankerConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        batches = iter(
            [
                [
                    ContactListFact("a" * 64, "evt-a-1", 100, 10, 2),
                    ContactListFact("d" * 64, "evt-d-1", 200, 20, 1),
                ],
                [],
            ]
        )

        async def fake_changed(
            _brotr: Brotr,
            checkpoint: GraphSyncCheckpoint,
            limit: int,
        ) -> list[ContactListFact]:
            assert limit == 2
            if checkpoint == GraphSyncCheckpoint():
                return next(batches)
            return next(batches)

        async def fake_edges(
            _brotr: Brotr,
            follower_pubkeys: list[str],
        ) -> list[FollowEdgeFact]:
            assert follower_pubkeys == ["a" * 64, "d" * 64]
            return [
                FollowEdgeFact("a" * 64, "b" * 64, "evt-a-1", 100, 10),
                FollowEdgeFact("a" * 64, "c" * 64, "evt-a-1", 100, 10),
                FollowEdgeFact("d" * 64, "a" * 64, "evt-d-1", 200, 20),
            ]

        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_changed_contact_lists", fake_changed
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_follow_edges_for_followers",
            fake_edges,
        )

        async def fake_event_stats(
            _brotr: Brotr,
            after_event_id: str,
            _limit: int,
        ) -> list[EventStatFact]:
            if after_event_id:
                return []
            return [EventStatFact("11" * 32, "a" * 64, 2, 1, 0, 3, 1, 2000)]

        async def fake_addressable_stats(
            _brotr: Brotr,
            after_event_address: str,
            _limit: int,
        ) -> list[AddressableStatFact]:
            if after_event_address:
                return []
            return [AddressableStatFact("30023:aa:alpha", "a" * 64, 1, 0, 0, 2, 0, 0)]

        async def fake_identifier_stats(
            _brotr: Brotr,
            after_identifier: str,
            _limit: int,
        ) -> list[IdentifierStatFact]:
            if after_identifier:
                return []
            return [IdentifierStatFact("isbn:9780140328721", 3, 1, ("book",))]

        monkeypatch.setattr("bigbrotr.services.ranker.service.fetch_event_stats", fake_event_stats)
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_addressable_stats",
            fake_addressable_stats,
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_identifier_stats",
            fake_identifier_stats,
        )

        ranker = Ranker(brotr=mock_brotr, config=ranker_config)
        async with ranker:
            result = await ranker.rank()

        store = RankerStore(ranker_config.storage.path, ranker_config.storage.checkpoint_path)
        assert result.changed_followers_synced == 2
        assert result.graph_nodes == 4
        assert result.graph_edges == 3
        assert result.non_user_staged == RankRowCounts(event=1, addressable=1, identifier=1)
        assert result.rank_counts == RankRowCounts(
            pubkey=4,
            event=1,
            addressable=1,
            identifier=1,
        )
        assert result.checkpoint == GraphSyncCheckpoint(20, "d" * 64)
        assert result.duckdb_file_size_bytes > 0
        assert store.get_graph_stats().node_count == 4
        assert store.get_graph_stats().edge_count == 3
        assert store.load_checkpoint() == GraphSyncCheckpoint(20, "d" * 64)
        assert store.fetch_pubkey_rank_batch(after_subject_id="", limit=10)
        assert store.fetch_event_rank_batch(after_subject_id="", limit=10)
        assert store.fetch_addressable_rank_batch(after_subject_id="", limit=10)
        assert store.fetch_identifier_rank_batch(after_subject_id="", limit=10)

    @pytest.mark.asyncio
    async def test_run_with_no_changes_keeps_empty_graph(
        self,
        mock_brotr: Brotr,
        ranker_config: RankerConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake_changed(
            _brotr: Brotr,
            _checkpoint: GraphSyncCheckpoint,
            _limit: int,
        ) -> list[ContactListFact]:
            return []

        async def fake_edges(
            _brotr: Brotr,
            _follower_pubkeys: list[str],
        ) -> list[FollowEdgeFact]:
            raise AssertionError("edge query should not run when no followers changed")

        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_changed_contact_lists", fake_changed
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_follow_edges_for_followers",
            fake_edges,
        )

        ranker = Ranker(brotr=mock_brotr, config=ranker_config)
        async with ranker:
            await ranker.run()

        store = RankerStore(ranker_config.storage.path, ranker_config.storage.checkpoint_path)
        assert store.get_graph_stats().node_count == 0
        assert store.get_graph_stats().edge_count == 0
        assert store.load_checkpoint() == GraphSyncCheckpoint()

    @pytest.mark.asyncio
    async def test_sync_batch_budget_stops_before_staging(
        self,
        mock_brotr: Brotr,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config = RankerConfig.model_validate(
            {
                "storage": {
                    "path": tmp_path / "ranker.duckdb",
                    "checkpoint_path": tmp_path / "ranker.checkpoint.json",
                },
                "metrics": {"enabled": False},
                "sync": {"batch_size": 1, "max_batches": 1},
            }
        )
        changed_calls = 0

        async def fake_changed(
            _brotr: Brotr,
            checkpoint: GraphSyncCheckpoint,
            limit: int,
        ) -> list[ContactListFact]:
            nonlocal changed_calls
            changed_calls += 1
            assert checkpoint == GraphSyncCheckpoint()
            assert limit == 1
            return [ContactListFact("a" * 64, "evt-a", 100, 10, 0)]

        async def fake_edges(
            _brotr: Brotr,
            follower_pubkeys: list[str],
        ) -> list[FollowEdgeFact]:
            assert follower_pubkeys == ["a" * 64]
            return []

        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_changed_contact_lists",
            fake_changed,
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_follow_edges_for_followers",
            fake_edges,
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_event_stats",
            AsyncMock(side_effect=AssertionError("staging should not run")),
        )

        result = await Ranker(brotr=mock_brotr, config=config).rank()

        assert changed_calls == 1
        assert result.cutoff_reason == "sync_max_batches"
        assert result.rank_run_id is None
        assert result.changed_followers_synced == 1
        assert result.sync_batches_processed == 1
        assert result.checkpoint == GraphSyncCheckpoint(10, "a" * 64)
        assert result.rank_counts == RankRowCounts()

    @pytest.mark.asyncio
    async def test_fact_stage_budget_stops_before_compute(
        self,
        mock_brotr: Brotr,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config = RankerConfig.model_validate(
            {
                "storage": {
                    "path": tmp_path / "ranker.duckdb",
                    "checkpoint_path": tmp_path / "ranker.checkpoint.json",
                },
                "metrics": {"enabled": False},
                "facts_stage": {"batch_size": 1, "max_event_rows": 1},
            }
        )

        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_changed_contact_lists",
            AsyncMock(return_value=[]),
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_event_stats",
            AsyncMock(return_value=[EventStatFact("11" * 32, "a" * 64, 1, 0, 0, 0, 0, 0)]),
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_addressable_stats",
            AsyncMock(side_effect=AssertionError("addressable staging should not run")),
        )

        result = await Ranker(brotr=mock_brotr, config=config).rank()

        assert result.cutoff_reason == "facts_stage_event_rows"
        assert result.rank_run_id is None
        assert result.non_user_staged == RankRowCounts(event=1)
        assert result.rank_counts == RankRowCounts()

    @pytest.mark.asyncio
    async def test_fact_stage_exact_row_budget_completes(
        self,
        mock_brotr: Brotr,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config = RankerConfig.model_validate(
            {
                "storage": {
                    "path": tmp_path / "ranker.duckdb",
                    "checkpoint_path": tmp_path / "ranker.checkpoint.json",
                },
                "metrics": {"enabled": False},
                "facts_stage": {"batch_size": 1, "max_event_rows": 1},
            }
        )

        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_changed_contact_lists",
            AsyncMock(return_value=[]),
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_event_stats",
            AsyncMock(
                side_effect=[
                    [EventStatFact("11" * 32, "a" * 64, 1, 0, 0, 0, 0, 0)],
                    [],
                ]
            ),
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_addressable_stats",
            AsyncMock(return_value=[]),
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_identifier_stats",
            AsyncMock(return_value=[]),
        )

        result = await Ranker(brotr=mock_brotr, config=config).rank()

        assert result.cutoff_reason is None
        assert result.rank_run_id == 1
        assert result.non_user_staged == RankRowCounts(event=1)
        assert result.rank_counts.event == 1

    @pytest.mark.asyncio
    async def test_export_budget_stops_without_partial_snapshot_merge(
        self,
        mock_brotr: Brotr,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config = RankerConfig.model_validate(
            {
                "storage": {
                    "path": tmp_path / "ranker.duckdb",
                    "checkpoint_path": tmp_path / "ranker.checkpoint.json",
                },
                "metrics": {"enabled": False},
                "sync": {"batch_size": 2},
                "export": {"batch_size": 1, "max_batches_per_subject": 1},
            }
        )
        pubkey_a = "a" * 64
        pubkey_b = "b" * 64
        batches = iter(
            [
                [
                    ContactListFact(pubkey_a, "evt-a", 100, 10, 1),
                    ContactListFact(pubkey_b, "evt-b", 110, 11, 1),
                ],
                [],
            ]
        )

        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_changed_contact_lists",
            AsyncMock(side_effect=lambda *_args: next(batches)),
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_follow_edges_for_followers",
            AsyncMock(
                return_value=[
                    FollowEdgeFact(pubkey_a, pubkey_b, "evt-a", 100, 10),
                    FollowEdgeFact(pubkey_b, pubkey_a, "evt-b", 110, 11),
                ]
            ),
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_event_stats", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_addressable_stats",
            AsyncMock(return_value=[]),
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_identifier_stats",
            AsyncMock(return_value=[]),
        )

        result = await Ranker(brotr=mock_brotr, config=config).rank()

        assert result.rank_run_id == 1
        assert result.cutoff_reason == "export_pubkey_max_batches"
        assert result.rank_counts == RankRowCounts()
        assert result.graph_nodes == 2
        assert result.graph_edges == 2

    @pytest.mark.asyncio
    async def test_export_exact_batch_budget_completes(
        self,
        mock_brotr: Brotr,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config = RankerConfig.model_validate(
            {
                "storage": {
                    "path": tmp_path / "ranker.duckdb",
                    "checkpoint_path": tmp_path / "ranker.checkpoint.json",
                },
                "metrics": {"enabled": False},
                "sync": {"batch_size": 1},
                "export": {"batch_size": 1, "max_batches_per_subject": 1},
            }
        )
        pubkey_a = "a" * 64

        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_changed_contact_lists",
            AsyncMock(side_effect=[[ContactListFact(pubkey_a, "evt-a", 100, 10, 0)], []]),
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_follow_edges_for_followers",
            AsyncMock(return_value=[]),
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_event_stats",
            AsyncMock(return_value=[]),
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_addressable_stats",
            AsyncMock(return_value=[]),
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_identifier_stats",
            AsyncMock(return_value=[]),
        )

        result = await Ranker(brotr=mock_brotr, config=config).rank()

        assert result.cutoff_reason is None
        assert result.rank_run_id == 1
        assert result.rank_counts.pubkey == 1
        assert result.graph_nodes == 1

    @pytest.mark.asyncio
    async def test_max_duration_budget_stops_before_sync_fetch(
        self,
        mock_brotr: Brotr,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config = RankerConfig.model_validate(
            {
                "storage": {
                    "path": tmp_path / "ranker.duckdb",
                    "checkpoint_path": tmp_path / "ranker.checkpoint.json",
                },
                "metrics": {"enabled": False},
                "processing": {"max_duration": 1.0},
            }
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_changed_contact_lists",
            AsyncMock(side_effect=AssertionError("sync fetch should not run")),
        )
        monkeypatch.setattr(
            Ranker,
            "_cycle_cutoff_reason",
            lambda _self, _cycle_start: "max_duration",
        )

        result = await Ranker(brotr=mock_brotr, config=config).rank()

        assert result.cutoff_reason == "max_duration"
        assert result.rank_run_id is None
        assert result.changed_followers_synced == 0
        assert result.rank_counts == RankRowCounts()

    def test_budget_helper_methods_report_duration_and_sync_cutoffs(
        self,
        mock_brotr: Brotr,
        tmp_path: Path,
    ) -> None:
        ranker = Ranker(
            brotr=mock_brotr,
            config=RankerConfig.model_validate(
                {
                    "storage": {
                        "path": tmp_path / "ranker.duckdb",
                        "checkpoint_path": tmp_path / "ranker.checkpoint.json",
                    },
                    "metrics": {"enabled": False},
                    "processing": {"max_duration": 1.0},
                    "sync": {"max_followers_per_cycle": 1},
                }
            ),
        )

        assert ranker._cycle_cutoff_reason(time.monotonic() - 2.0) == "max_duration"
        assert (
            ranker._sync_cutoff_reason(
                cycle_start=time.monotonic(),
                batches_processed=0,
                followers_synced=1,
            )
            == "sync_max_followers_per_cycle"
        )
        assert Ranker._next_limited_batch_size(batch_size=10, rows_processed=5, max_rows=5) == 0

    @pytest.mark.asyncio
    async def test_stage_helpers_stop_on_duration_cutoff(
        self,
        mock_brotr: Brotr,
        ranker_config: RankerConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ranker = Ranker(brotr=mock_brotr, config=ranker_config)
        monkeypatch.setattr(ranker, "_cycle_cutoff_reason", lambda _cycle_start: "max_duration")

        assert await ranker._stage_event_stats(time.monotonic()) == (0, "max_duration")
        assert await ranker._stage_addressable_stats(time.monotonic()) == (0, "max_duration")
        assert await ranker._stage_identifier_stats(time.monotonic()) == (0, "max_duration")

    @pytest.mark.asyncio
    async def test_non_user_stage_returns_addressable_budget_cutoff(
        self,
        mock_brotr: Brotr,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ranker = Ranker(
            brotr=mock_brotr,
            config=RankerConfig.model_validate(
                {
                    "storage": {
                        "path": tmp_path / "ranker.duckdb",
                        "checkpoint_path": tmp_path / "ranker.checkpoint.json",
                    },
                    "metrics": {"enabled": False},
                    "facts_stage": {
                        "batch_size": 1,
                        "max_addressable_rows": 1,
                    },
                }
            ),
        )

        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_event_stats",
            AsyncMock(return_value=[]),
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_addressable_stats",
            AsyncMock(
                side_effect=[
                    [AddressableStatFact("30023:aa:first", "a" * 64, 1, 0, 0, 0, 0, 0)],
                    [AddressableStatFact("30023:aa:second", "a" * 64, 1, 0, 0, 0, 0, 0)],
                ]
            ),
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_identifier_stats",
            AsyncMock(side_effect=AssertionError("identifier staging should not run")),
        )

        result = await ranker._sync_non_user_stats_stage(time.monotonic())

        assert result.counts == RankRowCounts(addressable=1)
        assert result.cutoff_reason == "facts_stage_addressable_rows"

    @pytest.mark.asyncio
    async def test_addressable_and_identifier_stage_exact_budget_detects_more_rows(
        self,
        mock_brotr: Brotr,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ranker = Ranker(
            brotr=mock_brotr,
            config=RankerConfig.model_validate(
                {
                    "storage": {
                        "path": tmp_path / "ranker.duckdb",
                        "checkpoint_path": tmp_path / "ranker.checkpoint.json",
                    },
                    "metrics": {"enabled": False},
                    "facts_stage": {
                        "batch_size": 1,
                        "max_addressable_rows": 1,
                        "max_identifier_rows": 1,
                    },
                }
            ),
        )

        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_addressable_stats",
            AsyncMock(
                side_effect=[
                    [AddressableStatFact("30023:aa:first", "a" * 64, 1, 0, 0, 0, 0, 0)],
                    [AddressableStatFact("30023:aa:second", "a" * 64, 1, 0, 0, 0, 0, 0)],
                ]
            ),
        )
        monkeypatch.setattr(
            "bigbrotr.services.ranker.service.fetch_identifier_stats",
            AsyncMock(
                side_effect=[
                    [IdentifierStatFact("isbn:first", 1, 0, ("book",))],
                    [IdentifierStatFact("isbn:second", 1, 0, ("book",))],
                ]
            ),
        )

        addressable_rows, addressable_cutoff = await ranker._stage_addressable_stats(
            time.monotonic()
        )
        identifier_rows, identifier_cutoff = await ranker._stage_identifier_stats(time.monotonic())

        assert (addressable_rows, addressable_cutoff) == (1, "facts_stage_addressable_rows")
        assert (identifier_rows, identifier_cutoff) == (1, "facts_stage_identifier_rows")

    @pytest.mark.asyncio
    async def test_populate_rank_stage_stops_on_duration_cutoff(
        self,
        mock_brotr: Brotr,
        ranker_config: RankerConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ranker = Ranker(brotr=mock_brotr, config=ranker_config)
        monkeypatch.setattr(ranker, "_cycle_cutoff_reason", lambda _cycle_start: "max_duration")
        fetch_batch = MagicMock()

        result = await ranker._populate_rank_stage(
            MagicMock(),
            subject_type="pubkey",
            fetch_batch=fetch_batch,
            cycle_start=time.monotonic(),
            computed_at=123,
        )

        assert result.rows == 0
        assert result.cutoff_reason == "max_duration"
        fetch_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_duration_budget_after_staging_stops_before_compute(
        self,
        mock_brotr: Brotr,
        ranker_config: RankerConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from bigbrotr.services.ranker.service import _GraphSyncResult, _StageResult

        ranker = Ranker(brotr=mock_brotr, config=ranker_config)
        monkeypatch.setattr(
            ranker,
            "_sync_follow_graph",
            AsyncMock(return_value=_GraphSyncResult(checkpoint=GraphSyncCheckpoint())),
        )
        monkeypatch.setattr(
            ranker,
            "_sync_non_user_stats_stage",
            AsyncMock(return_value=_StageResult(counts=RankRowCounts())),
        )
        monkeypatch.setattr(ranker, "_cycle_cutoff_reason", MagicMock(return_value="max_duration"))
        monkeypatch.setattr(ranker._store, "compute_pubkey_pagerank", MagicMock())

        result = await ranker.rank()

        assert result.cutoff_reason == "max_duration"
        assert result.rank_run_id is None
        ranker._store.compute_pubkey_pagerank.assert_not_called()

    @pytest.mark.asyncio
    async def test_duration_budget_after_compute_marks_run_cutoff(
        self,
        mock_brotr: Brotr,
        ranker_config: RankerConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from bigbrotr.services.ranker.service import _GraphSyncResult, _StageResult
        from bigbrotr.services.ranker.utils import GraphStats

        ranker = Ranker(brotr=mock_brotr, config=ranker_config)
        monkeypatch.setattr(
            ranker,
            "_sync_follow_graph",
            AsyncMock(return_value=_GraphSyncResult(checkpoint=GraphSyncCheckpoint())),
        )
        monkeypatch.setattr(
            ranker,
            "_sync_non_user_stats_stage",
            AsyncMock(return_value=_StageResult(counts=RankRowCounts())),
        )
        monkeypatch.setattr(
            ranker,
            "_cycle_cutoff_reason",
            MagicMock(side_effect=[None, "max_duration"]),
        )
        monkeypatch.setattr(
            ranker._store,
            "get_graph_stats_for_ranking",
            MagicMock(return_value=GraphStats(node_count=1, edge_count=0)),
        )
        monkeypatch.setattr(
            ranker._store,
            "start_rank_run",
            MagicMock(return_value=MagicMock(run_id=7)),
        )
        monkeypatch.setattr(ranker._store, "compute_pubkey_pagerank", MagicMock())
        monkeypatch.setattr(ranker._store, "compute_non_user_ranks", MagicMock())
        monkeypatch.setattr(ranker._store, "finish_rank_run", MagicMock())

        result = await ranker.rank()

        assert result.cutoff_reason == "max_duration"
        assert result.rank_run_id == 7
        ranker._store.finish_rank_run.assert_called_once_with(7, status="cutoff")

    @pytest.mark.asyncio
    async def test_compute_failure_marks_run_failed(
        self,
        mock_brotr: Brotr,
        ranker_config: RankerConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from bigbrotr.services.ranker.service import _GraphSyncResult, _StageResult
        from bigbrotr.services.ranker.utils import GraphStats

        ranker = Ranker(brotr=mock_brotr, config=ranker_config)
        ranker.set_gauge = MagicMock()
        monkeypatch.setattr(
            ranker,
            "_sync_follow_graph",
            AsyncMock(return_value=_GraphSyncResult(checkpoint=GraphSyncCheckpoint())),
        )
        monkeypatch.setattr(
            ranker,
            "_sync_non_user_stats_stage",
            AsyncMock(return_value=_StageResult(counts=RankRowCounts())),
        )
        monkeypatch.setattr(ranker, "_cycle_cutoff_reason", MagicMock(return_value=None))
        monkeypatch.setattr(
            ranker._store,
            "get_graph_stats_for_ranking",
            MagicMock(return_value=GraphStats(node_count=1, edge_count=0)),
        )
        monkeypatch.setattr(
            ranker._store,
            "start_rank_run",
            MagicMock(return_value=MagicMock(run_id=9)),
        )
        monkeypatch.setattr(
            ranker._store,
            "compute_pubkey_pagerank",
            MagicMock(side_effect=RuntimeError("pagerank failed")),
        )
        monkeypatch.setattr(ranker._store, "finish_rank_run", MagicMock())
        monkeypatch.setattr(ranker._store, "count_rank_runs", MagicMock(return_value=1))

        with pytest.raises(RuntimeError, match="pagerank failed"):
            await ranker.rank()

        ranker._store.finish_rank_run.assert_called_once_with(9, status="failed")
        ranker.set_gauge.assert_any_call("rank_runs_failed_total", 1)

    @pytest.mark.parametrize(
        ("cutoff_subject", "expected_reason"),
        [
            ("event", "export_event_max_batches"),
            ("addressable", "export_addressable_max_batches"),
            ("identifier", "export_identifier_max_batches"),
        ],
    )
    @pytest.mark.asyncio
    async def test_export_rank_snapshots_reports_later_subject_cutoffs(
        self,
        mock_brotr: Brotr,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        cutoff_subject: str,
        expected_reason: str,
    ) -> None:
        class FakeStore:
            def __init__(self, subject: str) -> None:
                self.subject = subject

            def _rows(
                self, subject: str, *, after_subject_id: str, limit: int
            ) -> list[RankExportRow]:
                if subject != self.subject:
                    return []
                suffix = "01" if not after_subject_id else "02"
                return [RankExportRow(suffix * 32, 0.5, 50)][:limit]

            def fetch_pubkey_rank_batch(
                self, *, after_subject_id: str, limit: int
            ) -> list[RankExportRow]:
                return self._rows("pubkey", after_subject_id=after_subject_id, limit=limit)

            def fetch_event_rank_batch(
                self, *, after_subject_id: str, limit: int
            ) -> list[RankExportRow]:
                return self._rows("event", after_subject_id=after_subject_id, limit=limit)

            def fetch_addressable_rank_batch(
                self, *, after_subject_id: str, limit: int
            ) -> list[RankExportRow]:
                return self._rows("addressable", after_subject_id=after_subject_id, limit=limit)

            def fetch_identifier_rank_batch(
                self, *, after_subject_id: str, limit: int
            ) -> list[RankExportRow]:
                return self._rows("identifier", after_subject_id=after_subject_id, limit=limit)

        ranker = Ranker(
            brotr=mock_brotr,
            config=RankerConfig.model_validate(
                {
                    "storage": {
                        "path": tmp_path / "ranker.duckdb",
                        "checkpoint_path": tmp_path / "ranker.checkpoint.json",
                    },
                    "metrics": {"enabled": False},
                    "export": {"batch_size": 1, "max_batches_per_subject": 1},
                }
            ),
        )
        ranker._store = FakeStore(cutoff_subject)  # type: ignore[assignment]

        with patch(
            "bigbrotr.services.ranker.service.insert_rank_stage_batch",
            AsyncMock(),
        ) as mock_insert:
            result = await ranker._export_rank_snapshots(
                cycle_start=time.monotonic(),
                computed_at=123,
            )

        assert result.cutoff_reason == expected_reason
        assert result.counts == RankRowCounts()
        mock_insert.assert_awaited_once()
