from pathlib import Path

from tests.integration.harness.deterministic import (
    DEFAULT_ASSOCIATED_AT,
    DEFAULT_OBSERVED_AT,
    DEFAULT_OUTPUT_EVENT_ID,
    DEFAULT_STORED_AT,
    deterministic_hex_id,
    deterministic_hex_ids,
    monotonic_unix_timestamps,
    ranker_storage_paths,
)


class TestIntegrationDeterministic:
    def test_deterministic_hex_id_is_stable_and_64_chars(self) -> None:
        first = deterministic_hex_id("partition-seed")
        second = deterministic_hex_id("partition-seed")

        assert first == second
        assert len(first) == 64

    def test_ranker_storage_paths_use_canonical_suffixes(self, tmp_path: Path) -> None:
        db_path, checkpoint_path = ranker_storage_paths(tmp_path, stem="pipeline")

        assert db_path == tmp_path / "pipeline.duckdb"
        assert checkpoint_path == tmp_path / "pipeline.checkpoint.json"

    def test_deterministic_hex_ids_returns_a_stable_sequence(self) -> None:
        ids = deterministic_hex_ids("partition-seed", count=3)

        assert ids == deterministic_hex_ids("partition-seed", count=3)
        assert len(ids) == 3
        assert len(set(ids)) == 3

    def test_monotonic_unix_timestamps_returns_a_dense_sequence(self) -> None:
        assert monotonic_unix_timestamps(start=10, count=4) == [10, 11, 12, 13]

    def test_fixed_defaults_remain_shared_constants(self) -> None:
        assert DEFAULT_STORED_AT == 1_700_000_000
        assert DEFAULT_OBSERVED_AT == 1_700_000_001
        assert DEFAULT_ASSOCIATED_AT == 1_700_000_001
        assert DEFAULT_OUTPUT_EVENT_ID == "aa" * 32
