"""
Unit tests for services.initializer module.

Tests:
- Configuration models (VerifyConfig, SeedConfig, SchemaConfig, InitializerConfig)
- Initializer service initialization
- Schema verification (extensions, tables, procedures, views)
- Relay seeding from file
- Error handling
"""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.brotr import Brotr
from services.initializer import (
    Initializer,
    InitializerConfig,
    InitializerError,
    SchemaConfig,
    SeedConfig,
    VerifyConfig,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_initializer_brotr(mock_brotr: Brotr) -> Brotr:
    """Create a Brotr mock configured for initializer tests."""
    # Default successful responses
    mock_brotr.pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]
    mock_brotr.pool._mock_connection.execute = AsyncMock()  # type: ignore[attr-defined]
    return mock_brotr


# ============================================================================
# VerifyConfig Tests
# ============================================================================


class TestVerifyConfig:
    """Tests for VerifyConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test all verification enabled by default."""
        config = VerifyConfig()

        assert config.extensions is True
        assert config.tables is True
        assert config.procedures is True
        assert config.views is True

    def test_disable_all(self) -> None:
        """Test can disable all verification."""
        config = VerifyConfig(
            extensions=False,
            tables=False,
            procedures=False,
            views=False,
        )

        assert config.extensions is False
        assert config.tables is False
        assert config.procedures is False
        assert config.views is False


# ============================================================================
# SeedConfig Tests
# ============================================================================


class TestSeedConfig:
    """Tests for SeedConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default seed configuration."""
        config = SeedConfig()

        assert config.enabled is True
        assert config.file_path == "data/seed_relays.txt"
        assert config.max_retries == 3

    def test_custom_values(self) -> None:
        """Test custom seed configuration."""
        config = SeedConfig(enabled=False, file_path="custom/path.txt", max_retries=5)

        assert config.enabled is False
        assert config.file_path == "custom/path.txt"
        assert config.max_retries == 5

    def test_max_retries_bounds(self) -> None:
        """Test max_retries validation bounds."""
        with pytest.raises(ValueError):
            SeedConfig(max_retries=0)

        with pytest.raises(ValueError):
            SeedConfig(max_retries=11)

        # Valid edge cases
        config_min = SeedConfig(max_retries=1)
        assert config_min.max_retries == 1

        config_max = SeedConfig(max_retries=10)
        assert config_max.max_retries == 10


# ============================================================================
# SchemaConfig Tests
# ============================================================================


class TestSchemaConfig:
    """Tests for SchemaConfig Pydantic model."""

    def test_default_extensions(self) -> None:
        """Test default extensions list."""
        config = SchemaConfig()

        assert "pgcrypto" in config.extensions
        assert "btree_gin" in config.extensions

    def test_default_tables(self) -> None:
        """Test default tables list."""
        config = SchemaConfig()

        expected_tables = ["relays", "events", "events_relays", "metadata", "relay_metadata", "service_data"]
        for table in expected_tables:
            assert table in config.tables

    def test_default_procedures(self) -> None:
        """Test default procedures list."""
        config = SchemaConfig()

        expected_procs = [
            "insert_event",
            "insert_relay",
            "insert_relay_metadata",
            "upsert_service_data",
            "delete_service_data",
        ]
        for proc in expected_procs:
            assert proc in config.procedures

    def test_default_views(self) -> None:
        """Test default views list."""
        config = SchemaConfig()

        assert "relay_metadata_latest" in config.views

    def test_custom_schema(self) -> None:
        """Test custom schema configuration."""
        config = SchemaConfig(
            extensions=["custom_ext"],
            tables=["custom_table"],
            procedures=["custom_proc"],
            views=["custom_view"],
        )

        assert config.extensions == ["custom_ext"]
        assert config.tables == ["custom_table"]
        assert config.procedures == ["custom_proc"]
        assert config.views == ["custom_view"]


# ============================================================================
# InitializerConfig Tests
# ============================================================================


class TestInitializerConfig:
    """Tests for InitializerConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default configuration."""
        config = InitializerConfig()

        assert config.verify.extensions is True
        assert config.verify.tables is True
        assert config.seed.enabled is True

    def test_custom_nested_config(self) -> None:
        """Test custom nested configuration."""
        config = InitializerConfig(
            verify=VerifyConfig(tables=False),
            seed=SeedConfig(enabled=False),
        )

        assert config.verify.tables is False
        assert config.seed.enabled is False

    def test_schema_alias(self) -> None:
        """Test schema field uses 'schema' alias."""
        config_dict = {
            "schema": {"extensions": ["test_ext"]},
        }
        config = InitializerConfig(**config_dict)

        assert config.schema_.extensions == ["test_ext"]


# ============================================================================
# Initializer Initialization Tests
# ============================================================================


class TestInitializerInit:
    """Tests for Initializer initialization."""

    def test_init_with_defaults(self, mock_initializer_brotr: Brotr) -> None:
        """Test initialization with default config."""
        initializer = Initializer(brotr=mock_initializer_brotr)

        assert initializer._brotr is mock_initializer_brotr
        assert initializer.SERVICE_NAME == "initializer"
        assert initializer.config.verify.tables is True
        assert initializer.config.seed.enabled is True

    def test_init_with_custom_config(self, mock_initializer_brotr: Brotr) -> None:
        """Test initialization with custom config."""
        config = InitializerConfig(
            verify=VerifyConfig(tables=False),
            seed=SeedConfig(enabled=False),
        )
        initializer = Initializer(brotr=mock_initializer_brotr, config=config)

        assert initializer.config.verify.tables is False
        assert initializer.config.seed.enabled is False

    def test_from_dict(self, mock_initializer_brotr: Brotr) -> None:
        """Test factory method from_dict."""
        data = {
            "verify": {"tables": False, "procedures": False},
            "seed": {"enabled": False},
        }
        initializer = Initializer.from_dict(data, brotr=mock_initializer_brotr)

        assert initializer.config.verify.tables is False
        assert initializer.config.verify.procedures is False
        assert initializer.config.seed.enabled is False


# ============================================================================
# Extension Verification Tests
# ============================================================================


class TestVerifyExtensions:
    """Tests for extension verification."""

    @pytest.mark.asyncio
    async def test_verify_extensions_success(self, mock_initializer_brotr: Brotr) -> None:
        """Test successful extension verification."""
        mock_initializer_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"extname": "pgcrypto"}, {"extname": "btree_gin"}]
        )

        initializer = Initializer(brotr=mock_initializer_brotr)
        await initializer._verify_extensions()  # Should not raise

    @pytest.mark.asyncio
    async def test_verify_extensions_missing(self, mock_initializer_brotr: Brotr) -> None:
        """Test extension verification with missing extension."""
        mock_initializer_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"extname": "pgcrypto"}]  # Missing btree_gin
        )

        initializer = Initializer(brotr=mock_initializer_brotr)

        with pytest.raises(InitializerError, match="Missing extensions"):
            await initializer._verify_extensions()

    @pytest.mark.asyncio
    async def test_verify_extensions_none_installed(self, mock_initializer_brotr: Brotr) -> None:
        """Test extension verification with no extensions installed."""
        mock_initializer_brotr.pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]

        initializer = Initializer(brotr=mock_initializer_brotr)

        with pytest.raises(InitializerError, match="Missing extensions"):
            await initializer._verify_extensions()


# ============================================================================
# Table Verification Tests
# ============================================================================


class TestVerifyTables:
    """Tests for table verification."""

    @pytest.mark.asyncio
    async def test_verify_tables_success(self, mock_initializer_brotr: Brotr) -> None:
        """Test successful table verification."""
        expected_tables = ["relays", "events", "events_relays", "metadata", "relay_metadata", "service_data"]
        mock_initializer_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"table_name": t} for t in expected_tables]
        )

        initializer = Initializer(brotr=mock_initializer_brotr)
        await initializer._verify_tables()  # Should not raise

    @pytest.mark.asyncio
    async def test_verify_tables_missing(self, mock_initializer_brotr: Brotr) -> None:
        """Test table verification with missing tables."""
        mock_initializer_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"table_name": "relays"}]
        )

        initializer = Initializer(brotr=mock_initializer_brotr)

        with pytest.raises(InitializerError, match="Missing tables"):
            await initializer._verify_tables()


# ============================================================================
# Procedure Verification Tests
# ============================================================================


class TestVerifyProcedures:
    """Tests for procedure verification."""

    @pytest.mark.asyncio
    async def test_verify_procedures_success(self, mock_initializer_brotr: Brotr) -> None:
        """Test successful procedure verification."""
        expected_procs = [
            "insert_event",
            "insert_relay",
            "insert_relay_metadata",
            "delete_orphan_events",
            "delete_orphan_nip11",
            "delete_orphan_nip66",
            "upsert_service_data",
            "delete_service_data",
        ]
        mock_initializer_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"routine_name": p} for p in expected_procs]
        )

        initializer = Initializer(brotr=mock_initializer_brotr)
        await initializer._verify_procedures()  # Should not raise

    @pytest.mark.asyncio
    async def test_verify_procedures_missing(self, mock_initializer_brotr: Brotr) -> None:
        """Test procedure verification with missing procedures."""
        mock_initializer_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"routine_name": "insert_event"}]
        )

        initializer = Initializer(brotr=mock_initializer_brotr)

        with pytest.raises(InitializerError, match="Missing procedures"):
            await initializer._verify_procedures()


# ============================================================================
# View Verification Tests
# ============================================================================


class TestVerifyViews:
    """Tests for view verification."""

    @pytest.mark.asyncio
    async def test_verify_views_success(self, mock_initializer_brotr: Brotr) -> None:
        """Test successful view verification."""
        mock_initializer_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"table_name": "relay_metadata_latest"}]
        )

        initializer = Initializer(brotr=mock_initializer_brotr)
        await initializer._verify_views()  # Should not raise

    @pytest.mark.asyncio
    async def test_verify_views_missing(self, mock_initializer_brotr: Brotr) -> None:
        """Test view verification with missing views."""
        mock_initializer_brotr.pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]

        initializer = Initializer(brotr=mock_initializer_brotr)

        with pytest.raises(InitializerError, match="Missing views"):
            await initializer._verify_views()


# ============================================================================
# Seed Relays Tests
# ============================================================================


class TestSeedRelays:
    """Tests for relay seeding."""

    @pytest.mark.asyncio
    async def test_seed_relays_file_not_found(self, mock_initializer_brotr: Brotr) -> None:
        """Test seeding with non-existent file."""
        config = InitializerConfig(seed=SeedConfig(file_path="nonexistent/file.txt"))
        initializer = Initializer(brotr=mock_initializer_brotr, config=config)

        await initializer._seed_relays()  # Should not raise, logs warning

        # Transaction should not be started
        mock_initializer_brotr.pool._mock_connection.execute.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_seed_relays_success(self, mock_initializer_brotr: Brotr, tmp_path: Path) -> None:
        """Test successful relay seeding as candidates."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay1.example.com\nwss://relay2.example.com\n")

        config = InitializerConfig(seed=SeedConfig(file_path=str(seed_file)))
        initializer = Initializer(brotr=mock_initializer_brotr, config=config)

        await initializer._seed_relays()

        # Should call execute for each relay (via upsert_service_data)
        execute_mock = mock_initializer_brotr.pool._mock_connection.execute  # type: ignore[attr-defined]
        assert execute_mock.call_count == 2

        # Verify calls insert into services table as validator candidates
        for call in execute_mock.call_args_list:
            args = call[0]
            assert "upsert_service_data" in args[0]
            assert args[1] == "validator"
            assert args[2] == "candidate"

    @pytest.mark.asyncio
    async def test_seed_relays_skips_comments_and_empty(
        self, mock_initializer_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test seeding skips comments and empty lines."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("# Comment\n\nwss://relay.example.com\n# Another comment\n")

        config = InitializerConfig(seed=SeedConfig(file_path=str(seed_file)))
        initializer = Initializer(brotr=mock_initializer_brotr, config=config)

        await initializer._seed_relays()

        # Only one valid relay should be inserted
        execute_mock = mock_initializer_brotr.pool._mock_connection.execute  # type: ignore[attr-defined]
        assert execute_mock.call_count == 1

    @pytest.mark.asyncio
    async def test_seed_relays_skips_invalid_urls(
        self, mock_initializer_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test seeding skips invalid relay URLs."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("invalid-url\nwss://valid.relay.com\nnot-a-relay\n")

        config = InitializerConfig(seed=SeedConfig(file_path=str(seed_file)))
        initializer = Initializer(brotr=mock_initializer_brotr, config=config)

        await initializer._seed_relays()

        # Only one valid relay should be inserted
        execute_mock = mock_initializer_brotr.pool._mock_connection.execute  # type: ignore[attr-defined]
        assert execute_mock.call_count == 1

    @pytest.mark.asyncio
    async def test_seed_relays_empty_file(self, mock_initializer_brotr: Brotr, tmp_path: Path) -> None:
        """Test seeding with empty file."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("")

        config = InitializerConfig(seed=SeedConfig(file_path=str(seed_file)))
        initializer = Initializer(brotr=mock_initializer_brotr, config=config)

        await initializer._seed_relays()  # Should not raise

        mock_initializer_brotr.pool._mock_connection.execute.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_seed_relays_atomic_rollback_on_failure(
        self, mock_initializer_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test that transaction rolls back on failure (atomic operation)."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay1.example.com\nwss://relay2.example.com\n")

        # Make execute fail on second call
        execute_mock = mock_initializer_brotr.pool._mock_connection.execute  # type: ignore[attr-defined]
        execute_mock.side_effect = [None, Exception("Database error")]

        config = InitializerConfig(seed=SeedConfig(file_path=str(seed_file), max_retries=1))
        initializer = Initializer(brotr=mock_initializer_brotr, config=config)

        with pytest.raises(InitializerError, match="Failed to seed relays after 1 attempts"):
            await initializer._seed_relays()

    @pytest.mark.asyncio
    async def test_seed_relays_retries_on_failure(
        self, mock_initializer_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test that seeding retries and succeeds after initial failure."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay.example.com\n")

        # First attempt fails, second succeeds
        execute_mock = mock_initializer_brotr.pool._mock_connection.execute  # type: ignore[attr-defined]
        execute_mock.side_effect = [Exception("Temporary error"), None]

        config = InitializerConfig(seed=SeedConfig(file_path=str(seed_file), max_retries=2))
        initializer = Initializer(brotr=mock_initializer_brotr, config=config)

        await initializer._seed_relays()  # Should succeed on second attempt

        assert execute_mock.call_count == 2


# ============================================================================
# Run Tests
# ============================================================================


class TestInitializerRun:
    """Tests for Initializer.run() method."""

    @pytest.mark.asyncio
    async def test_run_verification_only(self, mock_initializer_brotr: Brotr) -> None:
        """Test run with verification only (seed disabled)."""
        # Setup mock responses for all verifications
        expected_tables = ["relays", "events", "events_relays", "metadata", "relay_metadata", "service_data"]
        expected_procs = [
            "insert_event",
            "insert_relay",
            "insert_relay_metadata",
            "upsert_service_data",
            "delete_service_data",
        ]

        mock_initializer_brotr.pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            side_effect=[
                [{"extname": "pgcrypto"}, {"extname": "btree_gin"}],  # Extensions
                [{"table_name": t} for t in expected_tables],  # Tables
                [{"routine_name": p} for p in expected_procs],  # Procedures
                [{"table_name": "relay_metadata_latest"}],  # Views
            ]
        )

        config = InitializerConfig(seed=SeedConfig(enabled=False))
        initializer = Initializer(brotr=mock_initializer_brotr, config=config)

        await initializer.run()  # Should not raise

    @pytest.mark.asyncio
    async def test_run_skips_disabled_verification(self, mock_initializer_brotr: Brotr) -> None:
        """Test run skips disabled verifications."""
        config = InitializerConfig(
            verify=VerifyConfig(
                extensions=False,
                tables=False,
                procedures=False,
                views=False,
            ),
            seed=SeedConfig(enabled=False),
        )
        initializer = Initializer(brotr=mock_initializer_brotr, config=config)

        await initializer.run()  # Should not raise even with no mock setup

        # fetch should not be called since all verification is disabled
        mock_initializer_brotr.pool._mock_connection.fetch.assert_not_called()  # type: ignore[attr-defined]


# ============================================================================
# InitializerError Tests
# ============================================================================


class TestInitializerError:
    """Tests for InitializerError exception."""

    def test_error_with_message(self) -> None:
        """Test InitializerError carries message."""
        error = InitializerError("Test error message")
        assert str(error) == "Test error message"

    def test_error_is_exception(self) -> None:
        """Test InitializerError is an Exception."""
        assert issubclass(InitializerError, Exception)
