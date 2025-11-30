"""
Unit tests for Initializer service.
"""

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.brotr import Brotr
from core.pool import Pool
from services.initializer import (
    Initializer,
    InitializerConfig,
    InitializerError,
    SeedConfig,
    VerifyConfig,
)


@pytest.fixture
def mock_pool() -> MagicMock:
    """Create a mock pool."""
    os.environ.setdefault("DB_PASSWORD", "test_password")
    pool = MagicMock(spec=Pool)
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)
    pool.fetchval = AsyncMock(return_value=1)
    pool.execute = AsyncMock(return_value="OK")
    pool.is_connected = True

    # Mock transaction
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(return_value="OK")

    mock_transaction = MagicMock()
    mock_transaction.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_transaction.__aexit__ = AsyncMock(return_value=None)
    pool.transaction = MagicMock(return_value=mock_transaction)

    return pool


@pytest.fixture
def mock_brotr(mock_pool: MagicMock) -> MagicMock:
    """Create a mock Brotr."""
    brotr = MagicMock(spec=Brotr)
    brotr.pool = mock_pool
    brotr.insert_relays = AsyncMock(return_value=True)
    return brotr


class TestInitializerConfig:
    """Tests for InitializerConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = InitializerConfig()

        assert config.verify.tables is True
        assert config.verify.procedures is True
        assert config.verify.extensions is True
        assert config.verify.views is True
        assert config.seed.enabled is True

    def test_custom_verify(self) -> None:
        """Test custom verify settings."""
        config = InitializerConfig(verify=VerifyConfig(tables=False, procedures=False))

        assert config.verify.tables is False
        assert config.verify.procedures is False
        assert config.verify.extensions is True

    def test_custom_seed(self) -> None:
        """Test custom seed settings."""
        config = InitializerConfig(seed=SeedConfig(enabled=False, file_path="custom/path.txt"))

        assert config.seed.enabled is False
        assert config.seed.file_path == "custom/path.txt"


class TestInitializer:
    """Tests for Initializer service."""

    def test_init_with_defaults(self, mock_brotr: MagicMock) -> None:
        """Test initialization with defaults."""
        initializer = Initializer(brotr=mock_brotr)

        assert initializer._brotr is mock_brotr
        assert initializer._brotr.pool is mock_brotr.pool
        assert initializer.SERVICE_NAME == "initializer"
        assert initializer.config.verify.tables is True

    def test_init_with_custom_config(self, mock_brotr: MagicMock) -> None:
        """Test initialization with custom config."""
        config = InitializerConfig(
            verify=VerifyConfig(tables=False),
            seed=SeedConfig(enabled=False),
        )
        initializer = Initializer(brotr=mock_brotr, config=config)

        assert initializer.config.verify.tables is False
        assert initializer.config.seed.enabled is False

    @pytest.mark.asyncio
    async def test_verify_extensions_success(self, mock_brotr: MagicMock) -> None:
        """Test successful extension verification."""
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[
                {"extname": "pgcrypto"},
                {"extname": "btree_gin"},
            ]
        )

        initializer = Initializer(brotr=mock_brotr)
        # Should not raise
        await initializer._verify_extensions()

    @pytest.mark.asyncio
    async def test_verify_extensions_missing(self, mock_brotr: MagicMock) -> None:
        """Test extension verification with missing extension."""
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[{"extname": "pgcrypto"}]  # Missing btree_gin
        )

        initializer = Initializer(brotr=mock_brotr)
        with pytest.raises(InitializerError, match="Missing extensions"):
            await initializer._verify_extensions()

    @pytest.mark.asyncio
    async def test_verify_tables_success(self, mock_brotr: MagicMock) -> None:
        """Test successful table verification."""
        expected_tables = [
            "relays",
            "events",
            "events_relays",
            "nip11",
            "nip66",
            "relay_metadata",
            "service_state",
        ]
        mock_brotr.pool.fetch = AsyncMock(return_value=[{"table_name": t} for t in expected_tables])

        initializer = Initializer(brotr=mock_brotr)
        # Should not raise
        await initializer._verify_tables()

    @pytest.mark.asyncio
    async def test_verify_tables_missing(self, mock_brotr: MagicMock) -> None:
        """Test table verification with missing tables."""
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[{"table_name": "relays"}]  # Missing other tables
        )

        initializer = Initializer(brotr=mock_brotr)
        with pytest.raises(InitializerError, match="Missing tables"):
            await initializer._verify_tables()

    @pytest.mark.asyncio
    async def test_verify_procedures_success(self, mock_brotr: MagicMock) -> None:
        """Test successful procedure verification."""
        expected_procs = [
            "insert_event",
            "insert_relay",
            "insert_relay_metadata",
            "delete_orphan_events",
            "delete_orphan_nip11",
            "delete_orphan_nip66",
        ]
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[{"routine_name": p} for p in expected_procs]
        )

        initializer = Initializer(brotr=mock_brotr)
        # Should not raise
        await initializer._verify_procedures()

    @pytest.mark.asyncio
    async def test_verify_procedures_missing(self, mock_brotr: MagicMock) -> None:
        """Test procedure verification with missing procedures."""
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[{"routine_name": "insert_event"}]  # Missing other procs
        )

        initializer = Initializer(brotr=mock_brotr)
        with pytest.raises(InitializerError, match="Missing procedures"):
            await initializer._verify_procedures()

    @pytest.mark.asyncio
    async def test_verify_views_success(self, mock_brotr: MagicMock) -> None:
        """Test successful view verification."""
        expected_views = ["relay_metadata_latest"]
        mock_brotr.pool.fetch = AsyncMock(return_value=[{"table_name": v} for v in expected_views])

        initializer = Initializer(brotr=mock_brotr)
        # Should not raise
        await initializer._verify_views()

    @pytest.mark.asyncio
    async def test_verify_views_missing(self, mock_brotr: MagicMock) -> None:
        """Test view verification with missing views."""
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[]  # Missing relay_metadata_latest
        )

        initializer = Initializer(brotr=mock_brotr)
        with pytest.raises(InitializerError, match="Missing views"):
            await initializer._verify_views()

    @pytest.mark.asyncio
    async def test_run_verification_only(self, mock_brotr: MagicMock) -> None:
        """Test run with verification only (no seed)."""
        # Mock successful verification
        mock_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [{"extname": "pgcrypto"}, {"extname": "btree_gin"}],  # Extensions
                [
                    {"table_name": t}
                    for t in [
                        "relays",
                        "events",
                        "events_relays",
                        "nip11",
                        "nip66",
                        "relay_metadata",
                        "service_state",
                    ]
                ],  # Tables
                [
                    {"routine_name": p}
                    for p in [
                        "insert_event",
                        "insert_relay",
                        "insert_relay_metadata",
                        "delete_orphan_events",
                        "delete_orphan_nip11",
                        "delete_orphan_nip66",
                    ]
                ],  # Procedures
                [{"table_name": "relay_metadata_latest"}],  # Views
            ]
        )

        config = InitializerConfig(seed=SeedConfig(enabled=False))
        initializer = Initializer(brotr=mock_brotr, config=config)
        # Should not raise
        await initializer.run()

    @pytest.mark.asyncio
    async def test_run_with_failed_verification(self, mock_brotr: MagicMock) -> None:
        """Test run with failed verification."""
        # Mock failed extension check
        mock_brotr.pool.fetch = AsyncMock(return_value=[])

        config = InitializerConfig(
            seed=SeedConfig(enabled=False),
            verify=VerifyConfig(tables=False, procedures=False, views=False),
        )
        initializer = Initializer(brotr=mock_brotr, config=config)

        with pytest.raises(InitializerError, match="Missing extensions"):
            await initializer.run()

    @pytest.mark.asyncio
    async def test_seed_relays_file_not_found(self, mock_brotr: MagicMock) -> None:
        """Test seeding with non-existent seed file."""
        config = InitializerConfig(seed=SeedConfig(file_path="nonexistent/file.txt"))
        initializer = Initializer(brotr=mock_brotr, config=config)

        # Should not raise, just return early
        await initializer._seed_relays()

        # insert_relays should not be called
        mock_brotr.insert_relays.assert_not_called()

    @pytest.mark.asyncio
    async def test_health_check_connected(self, mock_brotr: MagicMock) -> None:
        """Test health check when connected and table exists."""
        mock_brotr.pool.fetchval = AsyncMock(return_value=True)

        initializer = Initializer(brotr=mock_brotr)
        result = await initializer.health_check()

        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_disconnected(self, mock_brotr: MagicMock) -> None:
        """Test health check when disconnected."""
        mock_brotr.pool.fetchval = AsyncMock(side_effect=Exception("Connection error"))

        initializer = Initializer(brotr=mock_brotr)
        result = await initializer.health_check()

        assert result is False


class TestInitializerFactoryMethods:
    """Tests for Initializer factory methods."""

    def test_from_dict(self, mock_brotr: MagicMock) -> None:
        """Test creation from dictionary."""
        data = {
            "verify": {"tables": False},
            "seed": {"enabled": False},
        }

        initializer = Initializer.from_dict(data, brotr=mock_brotr)

        assert initializer.config.verify.tables is False
        assert initializer.config.seed.enabled is False
