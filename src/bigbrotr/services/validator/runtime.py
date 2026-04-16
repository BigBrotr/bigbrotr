"""Runtime helpers for validator cycle planning and chunk persistence."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models.constants import NetworkType
    from bigbrotr.services.common.types import CandidateCheckpoint

    from .configs import ValidatorConfig


class _IterConcurrent(Protocol):
    """Typed protocol for validator concurrent chunk iteration."""

    def __call__(
        self,
        items: list[CandidateCheckpoint],
        worker: Callable[
            [CandidateCheckpoint],
            AsyncGenerator[tuple[CandidateCheckpoint, bool], None],
        ],
        *,
        max_concurrency: int,
    ) -> AsyncIterator[tuple[CandidateCheckpoint, bool]]: ...


class _IncGauge(Protocol):
    """Typed protocol for incrementing validator metrics."""

    def __call__(self, name: str, value: float = 1.0) -> None: ...


@dataclass(frozen=True, slots=True)
class ValidationCyclePlan:
    """Computed inputs for one validation cycle."""

    networks: tuple[NetworkType, ...]
    attempted_before: int
    chunk_size: int
    max_candidates: int | None
    max_concurrency: int


@dataclass(frozen=True, slots=True)
class ValidationChunkOutcome:
    """Classification result for one validated candidate page."""

    valid: tuple[CandidateCheckpoint, ...] = ()
    invalid: tuple[CandidateCheckpoint, ...] = ()

    @property
    def validated_count(self) -> int:
        """Number of candidates promoted from this page."""
        return len(self.valid)

    @property
    def not_validated_count(self) -> int:
        """Number of candidates marked failed from this page."""
        return len(self.invalid)


def build_validation_cycle_plan(
    *,
    config: ValidatorConfig,
    max_concurrency: int,
    now: int | None = None,
) -> ValidationCyclePlan | None:
    """Return the computed network and budget inputs for one validation cycle."""
    networks = tuple(config.networks.get_enabled_networks())
    if not networks:
        return None

    attempted_before = int((now if now is not None else time.time()) - config.processing.interval)
    return ValidationCyclePlan(
        networks=networks,
        attempted_before=attempted_before,
        chunk_size=config.processing.chunk_size,
        max_candidates=config.processing.max_candidates,
        max_concurrency=max_concurrency,
    )


async def validate_candidate_page(
    *,
    candidates: list[CandidateCheckpoint],
    max_concurrency: int,
    iter_concurrent: _IterConcurrent,
    worker: Callable[[CandidateCheckpoint], AsyncGenerator[tuple[CandidateCheckpoint, bool], None]],
    inc_gauge: _IncGauge,
) -> ValidationChunkOutcome:
    """Validate one fetched candidate page and classify its results."""
    chunk_valid: list[CandidateCheckpoint] = []
    chunk_invalid: list[CandidateCheckpoint] = []

    async for candidate, is_valid in iter_concurrent(
        candidates,
        worker,
        max_concurrency=max_concurrency,
    ):
        if is_valid:
            chunk_valid.append(candidate)
        else:
            chunk_invalid.append(candidate)
        inc_gauge("validated" if is_valid else "not_validated")

    return ValidationChunkOutcome(
        valid=tuple(chunk_valid),
        invalid=tuple(chunk_invalid),
    )


async def persist_validation_chunk(
    *,
    brotr: Brotr,
    outcome: ValidationChunkOutcome,
    promote_candidates_fn: Callable[[Brotr, list[CandidateCheckpoint]], Awaitable[int]],
    fail_candidates_fn: Callable[[Brotr, list[CandidateCheckpoint]], Awaitable[int]],
) -> None:
    """Persist one validated page by promoting and failing candidates."""
    await promote_candidates_fn(brotr, list(outcome.valid))
    await fail_candidates_fn(brotr, list(outcome.invalid))
