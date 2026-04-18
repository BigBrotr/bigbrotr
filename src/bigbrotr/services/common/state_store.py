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
    WHERE owner = $1
      AND state_type = $2
      AND state_key = ANY($3::text[])
    """


def _require_state_int(payload: MappingLike, field: str) -> int:
    """Read one persisted integer field without accepting bool or float aliases."""
    if field not in payload:
        raise TypeError(f"invalid {field}")
    value: object = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"invalid {field}")
    return value


def _require_non_negative_state_int(payload: MappingLike, field: str) -> int:
    """Read one persisted non-negative integer field."""
    value = _require_state_int(payload, field)
    if value < 0:
        raise ValueError(f"invalid {field}")
    return value


def _require_state_str(payload: MappingLike, field: str) -> str:
    """Read one persisted string field without coercing arbitrary values."""
    if field not in payload:
        raise TypeError(f"invalid {field}")
    value: object = payload[field]
    if not isinstance(value, str):
        raise TypeError(f"invalid {field}")
    return value


def _optional_state_int(payload: MappingLike, field: str, default: int) -> int:
    """Read one optional persisted integer field with a strict typed default."""
    if field not in payload:
        return default
    return _require_state_int(payload, field)


def _optional_state_str(payload: MappingLike, field: str, default: str) -> str:
    """Read one optional persisted string field with a strict typed default."""
    if field not in payload:
        return default
    return _require_state_str(payload, field)


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
        return checkpoint_type(key=key, timestamp=_require_state_int(payload, "timestamp"))

    @staticmethod
    def decode_cursor(
        key: str,
        payload: MappingLike,
        cursor_type: type[_CursorT],
    ) -> _CursorT:
        """Decode a cursor payload into a typed cursor."""
        return cursor_type(
            key=key,
            timestamp=_require_state_int(payload, "timestamp"),
            id=_require_state_str(payload, "id"),
        )

    @staticmethod
    def decode_candidate(key: str, payload: MappingLike) -> CandidateCheckpoint:
        """Decode a validator candidate payload."""
        return CandidateCheckpoint(
            key=key,
            timestamp=_require_non_negative_state_int(payload, "timestamp"),
            network=NetworkType(_require_state_str(payload, "network")),
            failures=_require_non_negative_state_int(payload, "failures"),
        )

    @staticmethod
    def encode_checkpoint(owner: str, checkpoint: Checkpoint) -> ServiceState:
        """Encode a typed checkpoint as a service-state row."""
        return ServiceState(
            owner=owner,
            state_type=ServiceStateType.CHECKPOINT,
            state_key=checkpoint.key,
            state_value={"timestamp": checkpoint.timestamp},
        )

    @staticmethod
    def encode_cursor(owner: str, cursor: Cursor) -> ServiceState:
        """Encode a typed cursor as a service-state row."""
        return ServiceState(
            owner=owner,
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
            owner=ServiceName.VALIDATOR,
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
        owner: str,
        key: str,
        hash_value: str,
        *,
        timestamp: int,
    ) -> ServiceState:
        """Encode a persisted hash checkpoint."""
        return ServiceState(
            owner=owner,
            state_type=ServiceStateType.CHECKPOINT,
            state_key=key,
            state_value={"hash": hash_value, "timestamp": timestamp},
        )

    async def get(
        self,
        owner: str,
        state_type: str,
        key: str | None = None,
    ) -> list[ServiceState]:
        return await self._brotr.get_service_state(owner, state_type, key)

    async def upsert(self, records: list[ServiceState]) -> int:
        return await batched_insert(self._brotr, records, self._brotr.upsert_service_state)

    async def delete_keys(
        self,
        owner: str,
        state_type: str,
        keys: list[str],
    ) -> int:
        if not keys:
            return 0
        return await self._delete_chunked(
            [owner] * len(keys),
            [state_type] * len(keys),
            keys,
        )

    async def delete_states(self, states: list[ServiceState]) -> int:
        if not states:
            return 0
        return await self._delete_chunked(
            [state.owner for state in states],
            [state.state_type for state in states],
            [state.state_key for state in states],
        )

    async def _delete_chunked(
        self,
        owners: list[str],
        state_types: list[str],
        state_keys: list[str],
    ) -> int:
        total = 0
        batch_size = batch_size_for(self._brotr, len(state_keys))
        for i in range(0, len(state_keys), batch_size):
            total += await self._brotr.delete_service_state(
                owners[i : i + batch_size],
                state_types[i : i + batch_size],
                state_keys[i : i + batch_size],
            )
        return total

    async def fetch_checkpoints(
        self,
        owner: str,
        keys: list[str],
        checkpoint_type: type[_CheckpointT],
    ) -> list[_CheckpointT]:
        return await self._fetch_typed_states(
            owner,
            ServiceStateType.CHECKPOINT,
            keys,
            lambda key, payload: self.decode_checkpoint(key, payload, checkpoint_type),
            lambda key: checkpoint_type(key=key),
        )

    async def upsert_checkpoints(
        self,
        owner: str,
        checkpoints: Sequence[Checkpoint],
    ) -> int:
        records = [self.encode_checkpoint(owner, checkpoint) for checkpoint in checkpoints]
        return await self.upsert(records)

    async def fetch_cursors(
        self,
        owner: str,
        keys: list[str],
        cursor_type: type[_CursorT],
    ) -> list[_CursorT]:
        if not keys:
            return []
        return await self._fetch_typed_states(
            owner,
            ServiceStateType.CURSOR,
            keys,
            lambda key, payload: self.decode_cursor(key, payload, cursor_type),
            lambda key: cursor_type(key=key),
        )

    async def _fetch_typed_states(
        self,
        owner: str,
        state_type: str,
        keys: list[str],
        decode: Callable[[str, MappingLike], _StateT],
        default_factory: Callable[[str], _StateT],
    ) -> list[_StateT]:
        if not keys:
            return []
        rows = await self._brotr.fetch(
            _FETCH_STATE_ROWS_SQL,
            owner,
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
        owner: str,
        cursors: Sequence[Cursor],
        *,
        skip_zero_timestamp: bool = False,
    ) -> int:
        records = [
            self.encode_cursor(owner, cursor)
            for cursor in cursors
            if not skip_zero_timestamp or cursor.timestamp > 0
        ]
        return await self.upsert(records)

    async def fetch_hash(self, owner: str, key: str) -> str | None:
        states = await self.get(owner, ServiceStateType.CHECKPOINT, key)
        if not states:
            return None
        hash_value = states[0].state_value.get("hash")
        if isinstance(hash_value, str):
            return hash_value
        return None

    async def upsert_hash(
        self,
        owner: str,
        key: str,
        hash_value: str,
        *,
        timestamp: int,
    ) -> int:
        return await self.upsert([self.encode_hash(owner, key, hash_value, timestamp=timestamp)])
