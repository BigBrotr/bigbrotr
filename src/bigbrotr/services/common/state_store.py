"""Shared typed access helpers for the ``service_state`` table."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, TypeAlias, TypeVar

from bigbrotr.models.constants import NetworkType, ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType

from .types import CandidateCheckpoint, Checkpoint, Cursor
from .utils import batch_size_for, batched_insert


if TYPE_CHECKING:
    from collections.abc import Sequence

    from bigbrotr.core.brotr import Brotr


_CheckpointT = TypeVar("_CheckpointT", bound=Checkpoint)
_CursorT = TypeVar("_CursorT", bound=Cursor)
_StateT = TypeVar("_StateT")
MappingLike: TypeAlias = Mapping[str, Any]

_FETCH_STATE_ROWS_SQL = """
    SELECT state_key, state_value
    FROM service_state
    WHERE service_name = $1
      AND state_type = $2
      AND state_key = ANY($3::text[])
    """


class ServiceStateStore:
    """Typed persistence boundary for ``service_state`` access."""

    def __init__(self, brotr: Brotr) -> None:
        self._brotr = brotr

    @staticmethod
    def decode_checkpoint(
        key: str,
        payload: MappingLike,
        checkpoint_type: type[_CheckpointT],
    ) -> _CheckpointT:
        """Decode a checkpoint payload into a typed checkpoint."""
        return checkpoint_type(key=key, timestamp=int(payload["timestamp"]))

    @staticmethod
    def decode_cursor(
        key: str,
        payload: MappingLike,
        cursor_type: type[_CursorT],
    ) -> _CursorT:
        """Decode a cursor payload into a typed cursor."""
        return cursor_type(key=key, timestamp=int(payload["timestamp"]), id=str(payload["id"]))

    @staticmethod
    def decode_candidate(key: str, payload: MappingLike) -> CandidateCheckpoint:
        """Decode a validator candidate payload."""
        return CandidateCheckpoint(
            key=key,
            timestamp=int(payload.get("timestamp", 0)),
            network=NetworkType(str(payload.get("network", "clearnet"))),
            failures=int(payload.get("failures", 0)),
        )

    @staticmethod
    def encode_checkpoint(service_name: str, checkpoint: Checkpoint) -> ServiceState:
        """Encode a typed checkpoint as a service-state row."""
        return ServiceState(
            service_name=service_name,
            state_type=ServiceStateType.CHECKPOINT,
            state_key=checkpoint.key,
            state_value={"timestamp": checkpoint.timestamp},
        )

    @staticmethod
    def encode_cursor(service_name: str, cursor: Cursor) -> ServiceState:
        """Encode a typed cursor as a service-state row."""
        return ServiceState(
            service_name=service_name,
            state_type=ServiceStateType.CURSOR,
            state_key=cursor.key,
            state_value={"timestamp": cursor.timestamp, "id": cursor.id},
        )

    @staticmethod
    def encode_candidate(
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

    @staticmethod
    def encode_hash(
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

    async def get(
        self,
        service_name: str,
        state_type: str,
        key: str | None = None,
    ) -> list[ServiceState]:
        return await self._brotr.get_service_state(service_name, state_type, key)

    async def upsert(self, records: list[ServiceState]) -> int:
        return await batched_insert(self._brotr, records, self._brotr.upsert_service_state)

    async def delete_keys(
        self,
        service_name: str,
        state_type: str,
        keys: list[str],
    ) -> int:
        if not keys:
            return 0
        return await self._delete_chunked(
            [service_name] * len(keys),
            [state_type] * len(keys),
            keys,
        )

    async def delete_states(self, states: list[ServiceState]) -> int:
        if not states:
            return 0
        return await self._delete_chunked(
            [state.service_name for state in states],
            [state.state_type for state in states],
            [state.state_key for state in states],
        )

    async def _delete_chunked(
        self,
        service_names: list[str],
        state_types: list[str],
        state_keys: list[str],
    ) -> int:
        total = 0
        batch_size = batch_size_for(self._brotr, len(state_keys))
        for i in range(0, len(state_keys), batch_size):
            total += await self._brotr.delete_service_state(
                service_names[i : i + batch_size],
                state_types[i : i + batch_size],
                state_keys[i : i + batch_size],
            )
        return total

    async def fetch_checkpoints(
        self,
        service_name: str,
        keys: list[str],
        checkpoint_type: type[_CheckpointT],
    ) -> list[_CheckpointT]:
        return await self._fetch_typed_states(
            service_name,
            ServiceStateType.CHECKPOINT,
            keys,
            lambda key, payload: self.decode_checkpoint(key, payload, checkpoint_type),
            lambda key: checkpoint_type(key=key),
        )

    async def upsert_checkpoints(
        self,
        service_name: str,
        checkpoints: Sequence[Checkpoint],
    ) -> int:
        records = [self.encode_checkpoint(service_name, checkpoint) for checkpoint in checkpoints]
        return await self.upsert(records)

    async def fetch_cursors(
        self,
        service_name: str,
        keys: list[str],
        cursor_type: type[_CursorT],
    ) -> list[_CursorT]:
        if not keys:
            return []
        return await self._fetch_typed_states(
            service_name,
            ServiceStateType.CURSOR,
            keys,
            lambda key, payload: self.decode_cursor(key, payload, cursor_type),
            lambda key: cursor_type(key=key),
        )

    async def _fetch_typed_states(
        self,
        service_name: str,
        state_type: str,
        keys: list[str],
        decode: Callable[[str, MappingLike], _StateT],
        default_factory: Callable[[str], _StateT],
    ) -> list[_StateT]:
        if not keys:
            return []
        rows = await self._brotr.fetch(
            _FETCH_STATE_ROWS_SQL,
            service_name,
            state_type,
            keys,
        )
        stored: dict[str, _StateT] = {}
        for row in rows:
            try:
                stored[row["state_key"]] = decode(row["state_key"], row["state_value"])
            except (KeyError, TypeError, ValueError):
                continue
        return [stored.get(key, default_factory(key)) for key in keys]

    async def upsert_cursors(
        self,
        service_name: str,
        cursors: Sequence[Cursor],
        *,
        skip_zero_timestamp: bool = False,
    ) -> int:
        records = [
            self.encode_cursor(service_name, cursor)
            for cursor in cursors
            if not skip_zero_timestamp or cursor.timestamp > 0
        ]
        return await self.upsert(records)

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
        return await self.upsert(
            [self.encode_hash(service_name, key, hash_value, timestamp=timestamp)]
        )
