from unittest.mock import AsyncMock, MagicMock

from bigbrotr.services.common.artifact_store import ArtifactStore


class TestArtifactStoreInsertMetadata:
    async def test_empty_returns_zero(self) -> None:
        brotr = MagicMock()
        brotr.insert_metadata = AsyncMock(return_value=1)

        result = await ArtifactStore(brotr).insert_metadata([])

        assert result == 0
        brotr.insert_metadata.assert_not_awaited()

    async def test_delegates_single_batch(self) -> None:
        brotr = MagicMock()
        brotr.config.batch.max_size = 100
        brotr.insert_metadata = AsyncMock(return_value=2)

        records = [MagicMock(), MagicMock()]
        result = await ArtifactStore(brotr).insert_metadata(records)

        assert result == 2
        brotr.insert_metadata.assert_awaited_once_with(records)

    async def test_splits_large_batches(self) -> None:
        brotr = MagicMock()
        brotr.config.batch.max_size = 2
        brotr.insert_metadata = AsyncMock(return_value=2)

        records = [MagicMock() for _ in range(5)]
        result = await ArtifactStore(brotr).insert_metadata(records)

        assert result == 6
        assert brotr.insert_metadata.await_count == 3


class TestArtifactStoreInsertRelayMetadata:
    async def test_empty_returns_zero(self) -> None:
        brotr = MagicMock()
        brotr.insert_relay_metadata = AsyncMock(return_value=1)

        result = await ArtifactStore(brotr).insert_relay_metadata([])

        assert result == 0
        brotr.insert_relay_metadata.assert_not_awaited()

    async def test_delegates_single_batch(self) -> None:
        brotr = MagicMock()
        brotr.config.batch.max_size = 100
        brotr.insert_relay_metadata = AsyncMock(return_value=2)

        records = [MagicMock(), MagicMock()]
        result = await ArtifactStore(brotr).insert_relay_metadata(records)

        assert result == 2
        brotr.insert_relay_metadata.assert_awaited_once_with(records, cascade=True)

    async def test_preserves_cascade_argument(self) -> None:
        brotr = MagicMock()
        brotr.config.batch.max_size = 100
        brotr.insert_relay_metadata = AsyncMock(return_value=1)

        record = MagicMock()
        await ArtifactStore(brotr).insert_relay_metadata([record], cascade=False)

        brotr.insert_relay_metadata.assert_awaited_once_with([record], cascade=False)

    async def test_splits_large_batches(self) -> None:
        brotr = MagicMock()
        brotr.config.batch.max_size = 2
        brotr.insert_relay_metadata = AsyncMock(return_value=2)

        records = [MagicMock() for _ in range(5)]
        result = await ArtifactStore(brotr).insert_relay_metadata(records)

        assert result == 6
        assert brotr.insert_relay_metadata.await_count == 3
