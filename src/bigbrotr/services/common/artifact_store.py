"""Shared typed persistence helpers for metadata-backed artifacts."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Metadata, RelayMetadata


class ArtifactStore:
    """Typed persistence boundary for ``metadata`` and ``relay_metadata`` access."""

    def __init__(self, brotr: Brotr) -> None:
        self._brotr = brotr

    def _batch_size(self) -> int:
        batch = getattr(getattr(self._brotr, "config", None), "batch", None)
        size = getattr(batch, "max_size", None)
        if isinstance(size, int) and size > 0:
            return size
        return 1000

    async def insert_metadata(self, records: list[Metadata]) -> int:
        if not records:
            return 0

        total = 0
        batch_size = self._batch_size()
        for i in range(0, len(records), batch_size):
            total += await self._brotr.insert_metadata(records[i : i + batch_size])
        return total

    async def insert_relay_metadata(
        self,
        records: list[RelayMetadata],
        *,
        cascade: bool = True,
    ) -> int:
        if not records:
            return 0

        total = 0
        batch_size = self._batch_size()
        for i in range(0, len(records), batch_size):
            total += await self._brotr.insert_relay_metadata(
                records[i : i + batch_size],
                cascade=cascade,
            )
        return total
