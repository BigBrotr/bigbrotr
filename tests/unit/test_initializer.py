"""
Unit tests for Initializer service.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.brotr import Brotr
from core.pool import Pool
from core.base_service import Outcome, Step
from services.initializer import (
    Initializer,
    InitializerConfig,
    InitializerState,
    ExpectedSchemaConfig,
    SeedConfig,
    VerificationConfig,
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

        assert config.verification.tables is True
        assert config.verification.procedures is True
        assert config.verification.extensions is True
        assert config.seed.enabled is True
        assert config.retry.max_attempts == 3

    def test_custom_verification(self) -> None:
        """Test custom verification settings."""
        config = InitializerConfig(
            verification=VerificationConfig(tables=False, procedures=False)
        )

        assert config.verification.tables is False
        assert config.verification.procedures is False
        assert config.verification.extensions is True

    def test_custom_seed(self) -> None:
        """Test custom seed settings."""
        config = InitializerConfig(
            seed=SeedConfig(enabled=False, path="custom/path.txt")
        )

        assert config.seed.enabled is False
        assert config.seed.path == "custom/path.txt"


class TestInitializerState:
    """Tests for InitializerState."""

    def test_default_state(self) -> None:
        """Test default state values."""
        state = InitializerState()

        assert state.initialized is False
        assert state.initialized_at == 0
        assert state.relays_seeded == 0
        assert state.last_error == ""

    def test_to_dict(self) -> None:
        """Test state serialization."""
        state = InitializerState(
            initialized=True,
            initialized_at=1700000000,
            relays_seeded=10,
        )

        data = state.to_dict()

        assert data["initialized"] is True
        assert data["initialized_at"] == 1700000000
        assert data["relays_seeded"] == 10

    def test_from_dict(self) -> None:
        """Test state deserialization."""
        data = {
            "initialized": True,
            "initialized_at": 1700000000,
            "relays_seeded": 5,
            "last_error": "test error",
        }

        state = InitializerState.from_dict(data)

        assert state.initialized is True
        assert state.initialized_at == 1700000000
        assert state.relays_seeded == 5
        assert state.last_error == "test error"


class TestInitializer:
    """Tests for Initializer service."""

    def test_init_with_defaults(self, mock_brotr: MagicMock) -> None:
        """Test initialization with defaults."""
        initializer = Initializer(brotr=mock_brotr)

        assert initializer._brotr is mock_brotr
        assert initializer._pool is mock_brotr.pool
        assert initializer.SERVICE_NAME == "initializer"
        assert initializer.config.verification.tables is True

    def test_init_with_custom_config(self, mock_brotr: MagicMock) -> None:
        """Test initialization with custom config."""
        config = InitializerConfig(
            verification=VerificationConfig(tables=False),
            seed=SeedConfig(enabled=False),
        )
        initializer = Initializer(brotr=mock_brotr, config=config)

        assert initializer.config.verification.tables is False
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
        step = await initializer._verify_extensions()

        assert step.success is True
        assert "extensions" in step.name

    @pytest.mark.asyncio
    async def test_verify_extensions_missing(self, mock_brotr: MagicMock) -> None:
        """Test extension verification with missing extension."""
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[{"extname": "pgcrypto"}]  # Missing btree_gin
        )

        initializer = Initializer(brotr=mock_brotr)
        step = await initializer._verify_extensions()

        assert step.success is False
        assert "Missing" in step.message

    @pytest.mark.asyncio
    async def test_verify_tables_success(self, mock_brotr: MagicMock) -> None:
        """Test successful table verification."""
        expected_tables = [
            "relays", "events", "events_relays", "nip11", "nip66",
            "relay_metadata", "service_state",
        ]
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[{"table_name": t} for t in expected_tables]
        )

        initializer = Initializer(brotr=mock_brotr)
        step = await initializer._verify_tables()

        assert step.success is True

    @pytest.mark.asyncio
    async def test_verify_procedures_success(self, mock_brotr: MagicMock) -> None:
        """Test successful procedure verification."""
        expected_procs = [
            "insert_event", "insert_relay", "insert_relay_metadata",
            "delete_orphan_events", "delete_orphan_nip11", "delete_orphan_nip66",
        ]
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[{"routine_name": p} for p in expected_procs]
        )

        initializer = Initializer(brotr=mock_brotr)
        step = await initializer._verify_procedures()

        assert step.success is True

    @pytest.mark.asyncio
    async def test_run_verification_only(self, mock_brotr: MagicMock) -> None:
        """Test run with verification only (no seed)."""
        # Mock successful verification
        mock_brotr.pool.fetch = AsyncMock(
            side_effect=[
                [{"extname": "pgcrypto"}, {"extname": "btree_gin"}],  # Extensions
                [{"table_name": t} for t in [
                    "relays", "events", "events_relays", "nip11", "nip66",
                    "relay_metadata", "service_state",
                ]],  # Tables
                [{"routine_name": p} for p in [
                    "insert_event", "insert_relay", "insert_relay_metadata",
                    "delete_orphan_events", "delete_orphan_nip11", "delete_orphan_nip66",
                ]],  # Procedures
            ]
        )

        config = InitializerConfig(seed=SeedConfig(enabled=False))
        initializer = Initializer(brotr=mock_brotr, config=config)
        result = await initializer.run()

        assert result.success is True
        assert len(result.steps) == 3  # Extensions, tables, procedures

    @pytest.mark.asyncio
    async def test_run_with_failed_verification(self, mock_brotr: MagicMock) -> None:
        """Test run with failed verification."""
        # Mock failed extension check
        mock_brotr.pool.fetch = AsyncMock(return_value=[])

        config = InitializerConfig(
            seed=SeedConfig(enabled=False),
            verification=VerificationConfig(tables=False, procedures=False),
        )
        initializer = Initializer(brotr=mock_brotr, config=config)
        result = await initializer.run()

        assert result.success is False
        assert len(result.errors) > 0

    def test_load_seed_file_not_found(self, mock_brotr: MagicMock) -> None:
        """Test loading non-existent seed file."""
        config = InitializerConfig(
            seed=SeedConfig(path="nonexistent/file.txt")
        )
        initializer = Initializer(brotr=mock_brotr, config=config)

        urls = initializer._load_seed_file()

        assert urls == []

    @pytest.mark.asyncio
    async def test_health_check(self, mock_brotr: MagicMock) -> None:
        """Test health check returns state."""
        initializer = Initializer(brotr=mock_brotr)

        # Not initialized yet
        assert await initializer.health_check() is False

        # Set as initialized
        initializer._state = InitializerState(initialized=True)
        assert await initializer.health_check() is True


class TestInitializerFactoryMethods:
    """Tests for Initializer factory methods."""

    def test_from_dict(self, mock_brotr: MagicMock) -> None:
        """Test creation from dictionary."""
        data = {
            "verification": {"tables": False},
            "seed": {"enabled": False},
        }

        initializer = Initializer.from_dict(data, brotr=mock_brotr)

        assert initializer.config.verification.tables is False
        assert initializer.config.seed.enabled is False