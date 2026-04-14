"""Shared typed access helpers for the ``service_state`` table."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeAlias, TypeVar

from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType

from .types import CandidateCheckpoint, Checkpoint, Cursor


if TYPE_CHECKING:
    from collections.abc import Sequence

    from bigbrotr.core.brotr import Brotr


_CheckpointT = TypeVar("_CheckpointT", bound=Checkpoint)
_CursorT = TypeVar("_CursorT", bound=Cursor)
MappingLike: TypeAlias = Mapping[str, Any]


def checkpoint_from_payload(
    key: str,
    payload: MappingLike,
    checkpoint_type: type[_CheckpointT],
) -> _CheckpointT:
    """Decode a checkpoint payload into a typed checkpoint."""
    return checkpoint_type(key=key, timestamp=int(payload["timestamp"]))


def cursor_from_payload(
    key: str,
    payload: MappingLike,
    cursor_type: type[_CursorT],
) -> _CursorT:
    """Decode a cursor payload into a typed cursor."""
    return cursor_type(key=key, timestamp=int(payload["timestamp"]), id=str(payload["id"]))


def candidate_from_payload(key: str, payload: MappingLike) -> CandidateCheckpoint:
    """Decode a validator candidate payload."""
    return CandidateCheckpoint(
        key=key,
        timestamp=int(payload.get("timestamp", 0)),
        network=NetworkType(str(payload.get("network", "clearnet"))),
        failures=int(payload.get("failures", 0)),
    )


def checkpoint_state(service_name: str, checkpoint: Checkpoint) -> ServiceState:
    """Encode a typed checkpoint as a service-state row."""
    return ServiceState(
        service_name=service_name,
        state_type=ServiceStateType.CHECKPOINT,
        state_key=checkpoint.key,
        state_value={"timestamp": checkpoint.timestamp},
    )


def cursor_state(service_name: str, cursor: Cursor) -> ServiceState:
    """Encode a typed cursor as a service-state row."""
    return ServiceState(
        service_name=service_name,
        state_type=ServiceStateType.CURSOR,
        state_key=cursor.key,
        state_value={"timestamp": cursor.timestamp, "id": cursor.id},
    )


def candidate_state(
    candidate: CandidateCheckpoint,
    *,
    timestamp: int | None = None,
    failures: int | None = None,
) -> ServiceState:
    """Encode a validator candidate as a service-state row."""
    return ServiceState(
        service_name=ServiceName.VALIDATOR,
        state_type=ServiceStateType.CHECKPOINT,
        state_key=candidate.key,
        state_value={
            "network": candidate.network.value,
            "failures": candidate.failures if failures is None else failures,
            "timestamp": candidate.timestamp if timestamp is None else timestamp,
        },
    )


def hash_state(
    service_name: str,
    key: str,
    hash_value: str,
    *,
    timestamp: int,
) -> ServiceState:
    """Encode a persisted hash checkpoint."""
    return ServiceState(
        service_name=service_name,
        state_type=ServiceStateType.CHECKPOINT,
        state_key=key,
        state_value={"hash": hash_value, "timestamp": timestamp},
    )


class ServiceStateStore:
    """Typed persistence boundary for ``service_state`` access."""

    def __init__(self, brotr: Brotr) -> None:
        self._brotr = brotr

    def _batch_size(self) -> int:
        batch = getattr(getattr(self._brotr, "config", None), "batch", None)
        size = getattr(batch, "max_size", None)
        if isinstance(size, int) and size > 0:
            return size
        return 1000

    async def get(
        self,
        service_name: str,
        state_type: str,
        key: str | None = None,
    ) -> list[ServiceState]:
        return await self._brotr.get_service_state(service_name, state_type, key)

    async def upsert(self, records: list[ServiceState]) -> int:
        if not records:
            return 0
        total = 0
        batch_size = self._batch_size()
        for i in range(0, len(records), batch_size):
            total += await self._brotr.upsert_service_state(records[i : i + batch_size])
        return total

    async def delete_keys(
        self,
        service_name: str,
        state_type: str,
        keys: list[str],
    ) -> int:
        if not keys:
            return 0
        total = 0
        batch_size = self._batch_size()
        for i in range(0, len(keys), batch_size):
            chunk = keys[i : i + batch_size]
            total += await self._brotr.delete_service_state(
                [service_name] * len(chunk),
                [state_type] * len(chunk),
                chunk,
            )
        return total

    async def delete_states(self, states: list[ServiceState]) -> int:
        if not states:
            return 0
        total = 0
        batch_size = self._batch_size()
        for i in range(0, len(states), batch_size):
            chunk = states[i : i + batch_size]
            total += await self._brotr.delete_service_state(
                [state.service_name for state in chunk],
                [state.state_type for state in chunk],
                [state.state_key for state in chunk],
            )
        return total

    async def fetch_checkpoints(
        self,
        service_name: str,
        keys: list[str],
        checkpoint_type: type[_CheckpointT],
    ) -> list[_CheckpointT]:
        if not keys:
            return []
        rows = await self._brotr.fetch(
            """
            SELECT state_key, state_value
            FROM service_state
            WHERE service_name = $1
              AND state_type = $2
              AND state_key = ANY($3::text[])
            """,
            service_name,
            ServiceStateType.CHECKPOINT,
            keys,
        )
        stored: dict[str, _CheckpointT] = {}
        for row in rows:
            try:
                stored[row["state_key"]] = checkpoint_from_payload(
                    row["state_key"],
                    row["state_value"],
                    checkpoint_type,
                )
            except (KeyError, TypeError, ValueError):
                continue
        return [stored.get(key, checkpoint_type(key=key)) for key in keys]

    async def upsert_checkpoints(
        self,
        service_name: str,
        checkpoints: Sequence[Checkpoint],
    ) -> int:
        records = [checkpoint_state(service_name, checkpoint) for checkpoint in checkpoints]
        return await self.upsert(records)

    async def upsert_cursors(
        self,
        service_name: str,
        cursors: Sequence[Cursor],
        *,
        skip_zero_timestamp: bool = False,
    ) -> int:
        records = [
            cursor_state(service_name, cursor)
            for cursor in cursors
            if not skip_zero_timestamp or cursor.timestamp > 0
        ]
        return await self.upsert(records)

    async def upsert_candidates(
        self,
        candidates: Sequence[CandidateCheckpoint],
        *,
        timestamp: int | None = None,
        failures: int | None = None,
    ) -> int:
        return await self.upsert(
            [
                candidate_state(candidate, timestamp=timestamp, failures=failures)
                for candidate in candidates
            ]
        )

    async def fetch_hash(self, service_name: str, key: str) -> str | None:
        states = await self.get(service_name, ServiceStateType.CHECKPOINT, key)
        if not states:
            return None
        hash_value = states[0].state_value.get("hash")
        if isinstance(hash_value, str):
            return hash_value
        return None

    async def upsert_hash(
        self,
        service_name: str,
        key: str,
        hash_value: str,
        *,
        timestamp: int,
    ) -> int:
        return await self.upsert([hash_state(service_name, key, hash_value, timestamp=timestamp)])
