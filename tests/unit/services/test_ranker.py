"""Unit tests for the ranker service package."""

from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
)
from bigbrotr.services.ranker.store import RankerStore


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


class TestRankerConfig:
    def test_default_values(self) -> None:
        config = RankerConfig()

        assert config.algorithm_id == "global-pagerank-v1"
        assert config.db.path == Path("/app/data/ranker.duckdb")
        assert config.db.checkpoint_path == Path("/app/data/ranker.checkpoint.json")
        assert config.graph.damping == pytest.approx(0.85)
        assert config.graph.iterations == 20
        assert config.graph.ignore_self_follows is True
        assert config.sync.batch_size == 1000
        assert config.export.batch_size == 1000
        assert config.interval == 3600.0

    def test_custom_nested_values(self, tmp_path: Path) -> None:
        config = RankerConfig.model_validate(
            {
                "algorithm_id": "custom-ranker-v2",
                "db": {
                    "path": tmp_path / "graph.duckdb",
                    "checkpoint_path": tmp_path / "graph.checkpoint.json",
                },
                "graph": {"damping": 0.9, "iterations": 40, "ignore_self_follows": False},
                "sync": {"batch_size": 250},
                "export": {"batch_size": 500},
                "interval": 7200.0,
            }
        )

        assert config.algorithm_id == "custom-ranker-v2"
        assert config.db.path == tmp_path / "graph.duckdb"
        assert config.db.checkpoint_path == tmp_path / "graph.checkpoint.json"
        assert config.graph.damping == pytest.approx(0.9)
        assert config.graph.iterations == 40
        assert config.graph.ignore_self_follows is False
        assert config.sync.batch_size == 250
        assert config.export.batch_size == 500
        assert config.interval == 7200.0

    def test_invalid_algorithm_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="algorithm_id must match"):
            RankerConfig(algorithm_id="Global PageRank V1")


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
            algorithm_id="global-pagerank-v1",
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
        assert row[0] == "global-pagerank-v1"
        assert row[1] == "success"
        assert row[2] == 4
        assert row[3] == 3
        assert row[4] is not None

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
            "db": {
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
        assert ranker.config.algorithm_id == "global-pagerank-v1"

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

        store = RankerStore(ranker_config.db.path, ranker_config.db.checkpoint_path)
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

        store = RankerStore(ranker_config.db.path, ranker_config.db.checkpoint_path)
        assert store.get_graph_stats().node_count == 0
        assert store.get_graph_stats().edge_count == 0
        assert store.load_checkpoint() == GraphSyncCheckpoint()
