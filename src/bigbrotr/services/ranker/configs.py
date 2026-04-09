"""Ranker service configuration models."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from bigbrotr.core.base_service import BaseServiceConfig


_ALGORITHM_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_DEFAULT_ALGORITHM_ID = "global-pagerank-v1"


class RankerDbConfig(BaseModel):
    """DuckDB and checkpoint storage paths for the ranker."""

    path: Path = Field(
        default=Path("/app/data/ranker.duckdb"),
        description="Path to the private DuckDB database used by the ranker",
    )
    checkpoint_path: Path = Field(
        default=Path("/app/data/ranker.checkpoint.json"),
        description="Path to the incremental sync checkpoint JSON file",
    )


class RankerGraphConfig(BaseModel):
    """Graph-ranking parameters for the 30382 PageRank computation."""

    damping: float = Field(
        default=0.85,
        gt=0.0,
        lt=1.0,
        description="PageRank damping factor for the 30382 pubkey ranking",
    )
    iterations: int = Field(
        default=20,
        ge=1,
        le=10000,
        description="Maximum PageRank iterations for the 30382 pubkey ranking",
    )
    ignore_self_follows: bool = Field(
        default=True,
        description="Ignore self-follow edges when computing PageRank",
    )


class RankerSyncConfig(BaseModel):
    """Incremental PostgreSQL -> DuckDB sync settings."""

    batch_size: int = Field(
        default=1000,
        ge=1,
        le=100000,
        description="Maximum changed followers to sync per batch",
    )


class RankerExportConfig(BaseModel):
    """PostgreSQL export settings for rank snapshots and staged fact batches."""

    batch_size: int = Field(
        default=1000,
        ge=1,
        le=100000,
        description="Maximum rows to read or export per batch during ranking runs",
    )


class RankerConfig(BaseServiceConfig):
    """Configuration for the Ranker service."""

    algorithm_id: str = Field(
        default=_DEFAULT_ALGORITHM_ID,
        min_length=1,
        max_length=128,
        description="Stable identifier for the ranking algorithm namespace",
    )
    db: RankerDbConfig = Field(
        default_factory=RankerDbConfig,
        description="DuckDB file locations for the private ranker store",
    )
    graph: RankerGraphConfig = Field(
        default_factory=RankerGraphConfig,
        description="Graph-ranking settings for the 30382 PageRank pipeline",
    )
    sync: RankerSyncConfig = Field(
        default_factory=RankerSyncConfig,
        description="Incremental follow-graph sync settings",
    )
    export: RankerExportConfig = Field(
        default_factory=RankerExportConfig,
        description="Batch settings for PostgreSQL facts staging and rank export",
    )
    interval: float = Field(
        default=3600.0,
        ge=60.0,
        description="Target seconds between ranker sync cycles",
    )

    @field_validator("algorithm_id")
    @classmethod
    def algorithm_id_valid(cls, v: str) -> str:
        if not _ALGORITHM_ID_PATTERN.fullmatch(v):
            raise ValueError(
                "algorithm_id must match [a-z0-9]+(?:[._-][a-z0-9]+)* "
                "(lowercase letters, digits, '.', '_' and '-')"
            )
        return v
