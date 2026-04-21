"""Deterministic support utilities for integration tests."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path


DEFAULT_STORED_AT = 1_700_000_000
DEFAULT_OBSERVED_AT = DEFAULT_STORED_AT + 1
DEFAULT_ASSOCIATED_AT = DEFAULT_OBSERVED_AT
DEFAULT_OUTPUT_EVENT_ID = "aa" * 32


def deterministic_hex_id(seed: str | int) -> str:
    """Return a stable 32-byte hex identifier from any simple seed."""
    return hashlib.sha256(str(seed).encode("utf-8")).hexdigest()


def deterministic_hex_ids(
    seed_prefix: str,
    *,
    count: int,
    start: int = 0,
) -> list[str]:
    """Return a deterministic sequence of 32-byte hex identifiers."""
    return [deterministic_hex_id(f"{seed_prefix}:{index}") for index in range(start, start + count)]


def monotonic_unix_timestamps(
    *,
    start: int = DEFAULT_STORED_AT,
    count: int,
    step: int = 1,
) -> list[int]:
    """Return a deterministic monotonically increasing Unix-timestamp sequence."""
    return [start + (offset * step) for offset in range(count)]


def ranker_storage_paths(tmp_path: Path, *, stem: str = "ranker") -> tuple[Path, Path]:
    """Return canonical deterministic DuckDB/checkpoint paths for integration tests."""
    return (
        tmp_path / f"{stem}.duckdb",
        tmp_path / f"{stem}.checkpoint.json",
    )
