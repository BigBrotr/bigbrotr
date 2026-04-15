"""Shared typed persistence helpers for metadata-backed artifacts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .utils import batched_insert


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Metadata, RelayMetadata


class ArtifactStore:
    """Typed persistence boundary for ``metadata`` and ``relay_metadata`` access."""

    def __init__(self, brotr: Brotr) -> None:
        self._brotr = brotr

    async def insert_metadata(self, records: list[Metadata]) -> int:
        return await batched_insert(self._brotr, records, self._brotr.insert_metadata)

    async def insert_relay_metadata(
        self,
        records: list[RelayMetadata],
        *,
        cascade: bool = True,
    ) -> int:
        return await batched_insert(
            self._brotr,
            records,
            lambda chunk: self._brotr.insert_relay_metadata(chunk, cascade=cascade),
        )
