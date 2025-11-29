"""
Unit tests for Initializer service.
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.initializer import (
    INITIALIZER_SERVICE_NAME,
    DatabaseVerificationConfig,
    InitializationResult,
    Initializer,
    InitializerConfig,
    InitializerState,
    LoggingConfig,
    RetryConfig,
    SeedDataConfig,
    TimeoutsConfig,
    VerificationResult,
)

# ============================================================================
# Configuration Model Tests
# ============================================================================


class TestInitializerConfig:
    """Tests for InitializerConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = InitializerConfig()

        assert config.database.verify_tables is True
        assert config.database.verify_procedures is True
        assert config.database.verify_extensions is True
        assert len(config.expected_tables) == 7
        assert len(config.expected_procedures) == 6
        assert len(config.expected_extensions) == 2
        assert config.seed_data.enabled is True
        assert config.seed_data.batch_size == 100

    def test_custom_values(self) -> None:
        """Test custom configuration."""
        config = InitializerConfig(
            database=DatabaseVerificationConfig(
                verify_tables=False,
                verify_procedures=True,
            ),
            expected_tables=["events", "relays"],
            expected_extensions=["pgcrypto"],
            seed_data=SeedDataConfig(enabled=False, batch_size=50),
            timeouts=TimeoutsConfig(schema_verification=60.0),
        )

        assert config.database.verify_tables is False
        assert len(config.expected_tables) == 2
        assert len(config.expected_extensions) == 1
        assert config.seed_data.enabled is False
        assert config.seed_data.batch_size == 50
        assert config.timeouts.schema_verification == 60.0


class TestDatabaseVerificationConfig:
    """Tests for DatabaseVerificationConfig."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = DatabaseVerificationConfig()
        assert config.verify_tables is True
        assert config.verify_procedures is True
        assert config.verify_extensions is True

    def test_all_disabled(self) -> None:
        """Test all verification disabled."""
        config = DatabaseVerificationConfig(
            verify_tables=False,
            verify_procedures=False,
            verify_extensions=False,
        )
        assert config.verify_tables is False
        assert config.verify_procedures is False
        assert config.verify_extensions is False


class TestSeedDataConfig:
    """Tests for SeedDataConfig."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = SeedDataConfig()
        assert config.enabled is True
        assert config.relay_file == "data/seed_relays.txt"
        assert config.batch_size == 100

    def test_custom_relay_file(self) -> None:
        """Test custom relay file path."""
        config = SeedDataConfig(relay_file="data/custom_relays.txt")
        assert config.relay_file == "data/custom_relays.txt"

    def test_batch_size_validation(self) -> None:
        """Test batch size boundaries."""
        # Valid boundaries
        config = SeedDataConfig(batch_size=1)
        assert config.batch_size == 1

        config = SeedDataConfig(batch_size=10000)
        assert config.batch_size == 10000

        # Invalid: too small
        with pytest.raises(ValueError):
            SeedDataConfig(batch_size=0)

        # Invalid: too large
        with pytest.raises(ValueError):
            SeedDataConfig(batch_size=10001)


class TestLoggingConfig:
    """Tests for LoggingConfig."""

    def test_valid_log_levels(self) -> None:
        """Test valid log levels."""
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            config = LoggingConfig(log_level=level)
            assert config.log_level == level

    def test_case_insensitive(self) -> None:
        """Test log level is normalized to uppercase."""
        config = LoggingConfig(log_level="debug")
        assert config.log_level == "DEBUG"

    def test_invalid_log_level(self) -> None:
        """Test invalid log level raises error."""
        with pytest.raises(ValueError):
            LoggingConfig(log_level="INVALID")


class TestRetryConfig:
    """Tests for RetryConfig."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = RetryConfig()
        assert config.max_attempts == 3
        assert config.initial_delay == 1.0
        assert config.max_delay == 10.0
        assert config.exponential_backoff is True

    def test_validation(self) -> None:
        """Test validation boundaries."""
        # Valid boundaries
        config = RetryConfig(max_attempts=1)
        assert config.max_attempts == 1

        config = RetryConfig(max_attempts=10)
        assert config.max_attempts == 10

        # Invalid: too small
        with pytest.raises(ValueError):
            RetryConfig(max_attempts=0)

        # Invalid: too large
        with pytest.raises(ValueError):
            RetryConfig(max_attempts=11)


# ============================================================================
# Result Dataclass Tests
# ============================================================================


class TestVerificationResult:
    """Tests for VerificationResult dataclass."""

    def test_creation(self) -> None:
        """Test creating verification result."""
        result = VerificationResult(
            name="test",
            success=True,
            message="All good",
            details={"verified": ["item1", "item2"]},
            duration_ms=123.45,
        )

        assert result.name == "test"
        assert result.success is True
        assert result.message == "All good"
        assert len(result.details["verified"]) == 2
        assert result.duration_ms == 123.45

    def test_default_values(self) -> None:
        """Test default values."""
        result = VerificationResult(name="test", success=True, message="OK")
        assert result.details == {}
        assert result.duration_ms == 0.0


class TestInitializationResult:
    """Tests for InitializationResult dataclass."""

    def test_creation(self) -> None:
        """Test creating initialization result."""
        result = InitializationResult(
            success=True,
            message="Initialization completed",
            verifications=[
                VerificationResult(name="ext", success=True, message="OK"),
            ],
            relays_seeded=100,
            duration_seconds=5.5,
            errors=[],
        )

        assert result.success is True
        assert len(result.verifications) == 1
        assert result.relays_seeded == 100
        assert result.duration_seconds == 5.5

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        result = InitializationResult(
            success=True,
            message="OK",
            verifications=[
                VerificationResult(
                    name="tables", success=True, message="All tables OK", duration_ms=50.0
                ),
            ],
            relays_seeded=50,
            duration_seconds=2.345,
        )

        data = result.to_dict()

        assert data["success"] is True
        assert data["relays_seeded"] == 50
        assert data["duration_seconds"] == 2.345
        assert len(data["verifications"]) == 1
        assert data["verifications"][0]["name"] == "tables"


# ============================================================================
# Initializer Service Tests
# ============================================================================


class TestInitializer:
    """Tests for Initializer service class."""

    @pytest.fixture
    def mock_brotr(self) -> MagicMock:
        """Create a mock Brotr instance with mock pool."""
        brotr = MagicMock()
        brotr.pool = MagicMock()
        brotr.pool.fetch = AsyncMock(return_value=[])
        brotr.pool.fetchrow = AsyncMock(return_value={"count": 0})
        brotr.insert_relays = AsyncMock(return_value=True)
        return brotr

    @pytest.fixture
    def initializer(self, mock_brotr: MagicMock) -> Initializer:
        """Create Initializer with mocked dependencies."""
        return Initializer(brotr=mock_brotr)

    def test_init_default_config(self, mock_brotr: MagicMock) -> None:
        """Test initialization with default config."""
        init = Initializer(brotr=mock_brotr)

        assert init._brotr is mock_brotr
        assert init._config is not None
        assert init._is_running is False
        assert init._initialized is False

    def test_init_custom_config(self, mock_brotr: MagicMock) -> None:
        """Test initialization with custom config."""
        config = InitializerConfig(
            seed_data=SeedDataConfig(enabled=False),
            expected_tables=["events"],
        )
        init = Initializer(brotr=mock_brotr, config=config)

        assert init._config.seed_data.enabled is False
        assert len(init._config.expected_tables) == 1

    def test_repr(self, initializer: Initializer) -> None:
        """Test string representation."""
        repr_str = repr(initializer)
        assert "Initializer" in repr_str
        assert "initialized=False" in repr_str

    @pytest.mark.asyncio
    async def test_start_stop(self, initializer: Initializer) -> None:
        """Test start and stop methods."""
        assert initializer.is_running is False

        await initializer.start()
        assert initializer.is_running is True

        await initializer.stop()
        assert initializer.is_running is False

    @pytest.mark.asyncio
    async def test_health_check_before_init(self, initializer: Initializer) -> None:
        """Test health check returns False before initialization."""
        result = await initializer.health_check()
        assert result is False

    def test_config_property(self, initializer: Initializer) -> None:
        """Test config property returns config."""
        config = initializer.config
        assert isinstance(config, InitializerConfig)

    def test_initialized_property(self, initializer: Initializer) -> None:
        """Test initialized property."""
        assert initializer.initialized is False


class TestInitializerVerification:
    """Tests for Initializer verification methods."""

    @pytest.fixture
    def mock_brotr(self) -> MagicMock:
        """Create a mock Brotr instance with mock pool."""
        brotr = MagicMock()
        brotr.pool = MagicMock()
        brotr.pool.fetch = AsyncMock(return_value=[])
        brotr.pool.fetchrow = AsyncMock(return_value={"count": 0})
        brotr.insert_relays = AsyncMock(return_value=True)
        return brotr

    @pytest.mark.asyncio
    async def test_verify_extensions_success(self, mock_brotr: MagicMock) -> None:
        """Test successful extension verification."""
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[
                {"extname": "pgcrypto"},
                {"extname": "btree_gin"},
                {"extname": "plpgsql"},
            ]
        )

        init = Initializer(brotr=mock_brotr)
        result = await init._verify_extensions()

        assert result.success is True
        assert result.name == "extensions"
        assert "2 extensions verified" in result.message

    @pytest.mark.asyncio
    async def test_verify_extensions_missing(self, mock_brotr: MagicMock) -> None:
        """Test extension verification with missing extension."""
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[
                {"extname": "pgcrypto"},
                # btree_gin is missing
            ]
        )

        init = Initializer(brotr=mock_brotr)
        result = await init._verify_extensions()

        assert result.success is False
        assert "Missing extensions" in result.message
        assert "btree_gin" in result.message

    @pytest.mark.asyncio
    async def test_verify_extensions_error(self, mock_brotr: MagicMock) -> None:
        """Test extension verification handles errors."""
        mock_brotr.pool.fetch = AsyncMock(side_effect=Exception("Connection failed"))

        init = Initializer(brotr=mock_brotr)
        result = await init._verify_extensions()

        assert result.success is False
        assert "error" in result.message.lower()

    @pytest.mark.asyncio
    async def test_verify_tables_success(self, mock_brotr: MagicMock) -> None:
        """Test successful table verification."""
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[
                {"table_name": "relays"},
                {"table_name": "events"},
                {"table_name": "events_relays"},
                {"table_name": "nip11"},
                {"table_name": "nip66"},
                {"table_name": "relay_metadata"},
                {"table_name": "service_state"},
            ]
        )

        init = Initializer(brotr=mock_brotr)
        result = await init._verify_tables()

        assert result.success is True
        assert result.name == "tables"
        assert "7 tables verified" in result.message

    @pytest.mark.asyncio
    async def test_verify_tables_missing(self, mock_brotr: MagicMock) -> None:
        """Test table verification with missing tables."""
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[
                {"table_name": "relays"},
                {"table_name": "events"},
                # Missing other tables
            ]
        )

        init = Initializer(brotr=mock_brotr)
        result = await init._verify_tables()

        assert result.success is False
        assert "Missing tables" in result.message

    @pytest.mark.asyncio
    async def test_verify_procedures_success(self, mock_brotr: MagicMock) -> None:
        """Test successful procedure verification."""
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[
                {"routine_name": "insert_event"},
                {"routine_name": "insert_relay"},
                {"routine_name": "insert_relay_metadata"},
                {"routine_name": "delete_orphan_events"},
                {"routine_name": "delete_orphan_nip11"},
                {"routine_name": "delete_orphan_nip66"},
            ]
        )

        init = Initializer(brotr=mock_brotr)
        result = await init._verify_procedures()

        assert result.success is True
        assert "6 procedures verified" in result.message

    @pytest.mark.asyncio
    async def test_verify_procedures_missing(self, mock_brotr: MagicMock) -> None:
        """Test procedure verification with missing procedures."""
        mock_brotr.pool.fetch = AsyncMock(
            return_value=[
                {"routine_name": "insert_event"},
                # Missing other procedures
            ]
        )

        init = Initializer(brotr=mock_brotr)
        result = await init._verify_procedures()

        assert result.success is False
        assert "Missing procedures" in result.message


class TestInitializerSeedData:
    """Tests for Initializer seed data loading."""

    @pytest.fixture
    def mock_brotr(self) -> MagicMock:
        """Create a mock Brotr instance with mock pool."""
        brotr = MagicMock()
        brotr.pool = MagicMock()
        brotr.pool.fetch = AsyncMock(return_value=[])
        brotr.pool.fetchrow = AsyncMock(return_value={"count": 0})
        brotr.insert_relays = AsyncMock(return_value=True)
        return brotr

    def test_load_relay_file(self, mock_brotr: MagicMock) -> None:
        """Test loading relay file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("wss://relay1.example.com\n")
            f.write("wss://relay2.example.com\n")
            f.write("wss://relay3.example.com\n")
            f.write("# This is a comment\n")
            f.write("\n")  # Empty line
            f.write("wss://relay4.example.com\n")
            temp_path = Path(f.name)

        config = InitializerConfig(seed_data=SeedDataConfig(relay_file=str(temp_path)))
        init = Initializer(brotr=mock_brotr, config=config, base_path=Path("/"))
        relays = init._load_relay_file()

        # Should have 4 valid wss:// URLs (comment and empty line ignored)
        assert len(relays) == 4
        assert "wss://relay1.example.com" in relays
        assert "wss://relay4.example.com" in relays

    def test_load_relay_file_not_found(self, mock_brotr: MagicMock) -> None:
        """Test loading non-existent relay file."""
        config = InitializerConfig(seed_data=SeedDataConfig(relay_file="nonexistent.txt"))
        init = Initializer(brotr=mock_brotr, config=config, base_path=Path("/tmp"))
        relays = init._load_relay_file()

        assert len(relays) == 0

    def test_load_relay_file_deduplication(self, mock_brotr: MagicMock) -> None:
        """Test relay file deduplication."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("wss://relay.example.com\n")
            f.write("wss://relay.example.com\n")  # Duplicate
            f.write("wss://other.example.com\n")
            temp_path = Path(f.name)

        config = InitializerConfig(seed_data=SeedDataConfig(relay_file=str(temp_path)))
        init = Initializer(brotr=mock_brotr, config=config, base_path=Path("/"))
        relays = init._load_relay_file()

        assert len(relays) == 2  # Duplicate removed

    @pytest.mark.asyncio
    async def test_seed_relays_empty_file(self, mock_brotr: MagicMock) -> None:
        """Test seeding with non-existent file returns success with zero relays."""
        config = InitializerConfig(seed_data=SeedDataConfig(relay_file="nonexistent.txt"))
        init = Initializer(brotr=mock_brotr, config=config, base_path=Path("/tmp"))

        result = await init._seed_relays()

        assert result.success is True
        assert "No relays to seed" in result.message
        assert result.details.get("relays_loaded") == 0

    @pytest.mark.asyncio
    async def test_insert_relays_batched(self, mock_brotr: MagicMock) -> None:
        """Test batched relay insertion with auto-detected network."""
        init = Initializer(brotr=mock_brotr)

        # Mix of clearnet and tor relays
        relay_urls = [f"wss://relay{i}.example.com" for i in range(250)]
        inserted = await init._insert_relays_batched(relay_urls)

        assert inserted == 250
        # With batch_size=100, should be 3 calls (100 + 100 + 50)
        assert mock_brotr.insert_relays.call_count == 3

    @pytest.mark.asyncio
    async def test_insert_relays_batched_network_detection(self, mock_brotr: MagicMock) -> None:
        """Test that network is auto-detected from URL."""
        init = Initializer(brotr=mock_brotr)

        # Mix of clearnet and tor relays
        relay_urls = [
            "wss://relay.damus.io",
            "wss://2jsnlhfnelig5acq6iacydmzdbdmg7xwunm4xl6qwbvzacw4lwrjmlyd.onion",
        ]
        await init._insert_relays_batched(relay_urls)

        # Check the relay records passed to insert_relays
        call_args = mock_brotr.insert_relays.call_args[0][0]
        assert call_args[0]["network"] == "clearnet"
        assert call_args[1]["network"] == "tor"

    def test_calculate_retry_delay_exponential(self, mock_brotr: MagicMock) -> None:
        """Test exponential backoff delay calculation."""
        config = InitializerConfig(
            retry=RetryConfig(
                initial_delay=1.0,
                max_delay=10.0,
                exponential_backoff=True,
            )
        )
        init = Initializer(brotr=mock_brotr, config=config)

        assert init._calculate_retry_delay(0) == 1.0
        assert init._calculate_retry_delay(1) == 2.0
        assert init._calculate_retry_delay(2) == 4.0
        assert init._calculate_retry_delay(3) == 8.0
        assert init._calculate_retry_delay(4) == 10.0  # Capped at max_delay

    def test_calculate_retry_delay_linear(self, mock_brotr: MagicMock) -> None:
        """Test linear delay calculation (no backoff)."""
        config = InitializerConfig(
            retry=RetryConfig(
                initial_delay=2.0,
                exponential_backoff=False,
            )
        )
        init = Initializer(brotr=mock_brotr, config=config)

        assert init._calculate_retry_delay(0) == 2.0
        assert init._calculate_retry_delay(1) == 2.0
        assert init._calculate_retry_delay(5) == 2.0


class TestInitializerFullFlow:
    """Tests for complete initialization flow."""

    @pytest.fixture
    def mock_brotr_success(self) -> MagicMock:
        """Create a mock Brotr configured for successful initialization."""
        brotr = MagicMock()
        brotr.pool = MagicMock()
        brotr.insert_relays = AsyncMock(return_value=True)

        # Extension check
        brotr.pool.fetch = AsyncMock(
            side_effect=[
                # Extensions
                [{"extname": "pgcrypto"}, {"extname": "btree_gin"}],
                # Tables
                [
                    {"table_name": "relays"},
                    {"table_name": "events"},
                    {"table_name": "events_relays"},
                    {"table_name": "nip11"},
                    {"table_name": "nip66"},
                    {"table_name": "relay_metadata"},
                    {"table_name": "service_state"},
                ],
                # Procedures
                [
                    {"routine_name": "insert_event"},
                    {"routine_name": "insert_relay"},
                    {"routine_name": "insert_relay_metadata"},
                    {"routine_name": "delete_orphan_events"},
                    {"routine_name": "delete_orphan_nip11"},
                    {"routine_name": "delete_orphan_nip66"},
                ],
            ]
        )
        # Relay count check
        brotr.pool.fetchrow = AsyncMock(return_value={"count": 100})

        return brotr

    @pytest.mark.asyncio
    async def test_initialize_success(self, mock_brotr_success: MagicMock) -> None:
        """Test successful full initialization."""
        # Disable seed data for this test (no file exists)
        config = InitializerConfig(seed_data=SeedDataConfig(enabled=False))
        init = Initializer(brotr=mock_brotr_success, config=config)

        result = await init.initialize()

        assert result.success is True
        assert len(result.errors) == 0
        assert len(result.verifications) == 3  # extensions, tables, procedures (no seed_data)
        assert init.initialized is True

    @pytest.mark.asyncio
    async def test_initialize_with_verification_disabled(
        self, mock_brotr_success: MagicMock
    ) -> None:
        """Test initialization with some verifications disabled."""
        config = InitializerConfig(
            database=DatabaseVerificationConfig(
                verify_extensions=False,
                verify_tables=False,
                verify_procedures=False,
            ),
            seed_data=SeedDataConfig(enabled=False),
        )
        init = Initializer(brotr=mock_brotr_success, config=config)

        result = await init.initialize()

        assert result.success is True
        assert len(result.verifications) == 0

    @pytest.mark.asyncio
    async def test_initialize_with_errors(self) -> None:
        """Test initialization with verification failures."""
        mock_brotr = MagicMock()
        mock_brotr.pool = MagicMock()
        # Extensions check will fail
        mock_brotr.pool.fetch = AsyncMock(return_value=[])  # No extensions
        mock_brotr.pool.fetchrow = AsyncMock(return_value={"count": 0})

        init = Initializer(brotr=mock_brotr)
        result = await init.initialize()

        assert result.success is False
        assert len(result.errors) > 0
        assert init.initialized is False

    @pytest.mark.asyncio
    async def test_initialize_handles_exception(self) -> None:
        """Test initialization handles verification errors gracefully."""
        mock_brotr = MagicMock()
        mock_brotr.pool = MagicMock()
        mock_brotr.pool.fetch = AsyncMock(side_effect=Exception("Connection error"))
        mock_brotr.pool.fetchrow = AsyncMock(return_value={"count": 0})

        init = Initializer(brotr=mock_brotr)
        result = await init.initialize()

        assert result.success is False
        # Errors are collected from failed verifications
        assert len(result.errors) > 0
        assert "error" in result.errors[0].lower()

    @pytest.mark.asyncio
    async def test_health_check_after_init(self, mock_brotr_success: MagicMock) -> None:
        """Test health check returns True after successful initialization."""
        config = InitializerConfig(seed_data=SeedDataConfig(enabled=False))
        init = Initializer(brotr=mock_brotr_success, config=config)

        await init.initialize()
        result = await init.health_check()

        assert result is True


class TestInitializerFactory:
    """Tests for Initializer factory methods."""

    def test_from_dict(self) -> None:
        """Test creating Initializer from dictionary."""
        data = {
            "database": {"verify_tables": False},
            "expected_tables": ["events", "relays"],
            "seed_data": {"enabled": False},
        }

        mock_brotr = MagicMock()
        mock_brotr.pool = MagicMock()
        init = Initializer.from_dict(data, brotr=mock_brotr)

        assert init._config.database.verify_tables is False
        assert len(init._config.expected_tables) == 2
        assert init._config.seed_data.enabled is False

    def test_from_yaml(self) -> None:
        """Test creating Initializer from YAML file."""
        yaml_content = """
database:
  verify_tables: true
  verify_procedures: true

expected_tables:
  - events
  - relays

seed_data:
  enabled: false
  batch_size: 50
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            temp_path = f.name

        mock_brotr = MagicMock()
        mock_brotr.pool = MagicMock()
        init = Initializer.from_yaml(temp_path, brotr=mock_brotr)

        assert init._config.database.verify_tables is True
        assert len(init._config.expected_tables) == 2
        assert init._config.seed_data.enabled is False
        assert init._config.seed_data.batch_size == 50


# ============================================================================
# InitializerState Tests
# ============================================================================


class TestInitializerState:
    """Tests for InitializerState dataclass."""

    def test_default_values(self) -> None:
        """Test default state values."""
        state = InitializerState()

        assert state.initialized is False
        assert state.initialized_at == 0
        assert state.relays_seeded == 0
        assert state.errors == []

    def test_custom_values(self) -> None:
        """Test custom state values."""
        state = InitializerState(
            initialized=True,
            initialized_at=1700000000,
            relays_seeded=100,
            errors=["error1"],
        )

        assert state.initialized is True
        assert state.initialized_at == 1700000000
        assert state.relays_seeded == 100
        assert state.errors == ["error1"]

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        state = InitializerState(
            initialized=True,
            initialized_at=1700000000,
            relays_seeded=50,
            errors=[],
        )

        data = state.to_dict()

        assert data["initialized"] is True
        assert data["initialized_at"] == 1700000000
        assert data["relays_seeded"] == 50
        assert data["errors"] == []

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {
            "initialized": True,
            "initialized_at": 1700000000,
            "relays_seeded": 75,
            "errors": ["warning1"],
        }

        state = InitializerState.from_dict(data)

        assert state.initialized is True
        assert state.initialized_at == 1700000000
        assert state.relays_seeded == 75
        assert state.errors == ["warning1"]

    def test_from_dict_with_missing_fields(self) -> None:
        """Test from_dict handles missing fields."""
        data = {"initialized": True}

        state = InitializerState.from_dict(data)

        assert state.initialized is True
        assert state.initialized_at == 0
        assert state.relays_seeded == 0
        assert state.errors == []


class TestInitializerServiceName:
    """Tests for INITIALIZER_SERVICE_NAME constant."""

    def test_service_name_value(self) -> None:
        """Test the service name is correctly defined."""
        assert INITIALIZER_SERVICE_NAME == "initializer"


class TestInitializerStateManagement:
    """Tests for Initializer state persistence."""

    @pytest.fixture
    def mock_brotr_with_state(self) -> MagicMock:
        """Create a mock Brotr with state support."""
        brotr = MagicMock()
        brotr.pool = MagicMock()
        brotr.pool.fetch = AsyncMock(return_value=[])
        brotr.pool.fetchrow = AsyncMock(return_value=None)
        brotr.pool.execute = AsyncMock()
        brotr.insert_relays = AsyncMock(return_value=True)
        return brotr

    @pytest.mark.asyncio
    async def test_save_state_on_success(self, mock_brotr_with_state: MagicMock) -> None:
        """Test state is saved after successful initialization."""
        # Mock successful verification responses
        mock_brotr_with_state.pool.fetch = AsyncMock(
            side_effect=[
                # Extensions
                [{"extname": "pgcrypto"}, {"extname": "btree_gin"}],
                # Tables
                [
                    {"table_name": "relays"},
                    {"table_name": "events"},
                    {"table_name": "events_relays"},
                    {"table_name": "nip11"},
                    {"table_name": "nip66"},
                    {"table_name": "relay_metadata"},
                    {"table_name": "service_state"},
                ],
                # Procedures
                [
                    {"routine_name": "insert_event"},
                    {"routine_name": "insert_relay"},
                    {"routine_name": "insert_relay_metadata"},
                    {"routine_name": "delete_orphan_events"},
                    {"routine_name": "delete_orphan_nip11"},
                    {"routine_name": "delete_orphan_nip66"},
                ],
            ]
        )

        config = InitializerConfig(seed_data=SeedDataConfig(enabled=False))
        init = Initializer(brotr=mock_brotr_with_state, config=config)

        result = await init.initialize()

        assert result.success is True
        # Verify execute was called to save state
        mock_brotr_with_state.pool.execute.assert_called()
        # Verify state was updated
        assert init.state.initialized is True
        assert init.state.initialized_at > 0

    @pytest.mark.asyncio
    async def test_save_state_on_failure(self, mock_brotr_with_state: MagicMock) -> None:
        """Test state is saved after failed initialization."""
        # Mock failed verification (empty extensions)
        mock_brotr_with_state.pool.fetch = AsyncMock(return_value=[])

        init = Initializer(brotr=mock_brotr_with_state)

        result = await init.initialize()

        assert result.success is False
        # Verify execute was called to save state
        mock_brotr_with_state.pool.execute.assert_called()
        # Verify state reflects failure
        assert init.state.initialized is False
        assert len(init.state.errors) > 0

    @pytest.mark.asyncio
    async def test_state_property(self, mock_brotr_with_state: MagicMock) -> None:
        """Test state property returns current state."""
        init = Initializer(brotr=mock_brotr_with_state)

        state = init.state

        assert isinstance(state, InitializerState)
        assert state.initialized is False


class TestInitializerStateLoadFromDb:
    """Tests for InitializerState.load_from_db static method."""

    @pytest.mark.asyncio
    async def test_load_from_db_with_valid_state(self) -> None:
        """Test loading state when valid state exists in database."""
        mock_pool = MagicMock()
        mock_pool.fetchrow = AsyncMock(
            return_value={
                "state": {
                    "initialized": True,
                    "initialized_at": 1700000000,
                    "relays_seeded": 50,
                    "errors": [],
                }
            }
        )

        state = await InitializerState.load_from_db(mock_pool)

        assert state.initialized is True
        assert state.initialized_at == 1700000000
        assert state.relays_seeded == 50
        assert state.errors == []

    @pytest.mark.asyncio
    async def test_load_from_db_with_string_json(self) -> None:
        """Test loading state when state is stored as JSON string."""
        import json

        mock_pool = MagicMock()
        mock_pool.fetchrow = AsyncMock(
            return_value={
                "state": json.dumps({
                    "initialized": True,
                    "initialized_at": 1700000000,
                    "relays_seeded": 25,
                    "errors": ["warning1"],
                })
            }
        )

        state = await InitializerState.load_from_db(mock_pool)

        assert state.initialized is True
        assert state.initialized_at == 1700000000
        assert state.relays_seeded == 25
        assert state.errors == ["warning1"]

    @pytest.mark.asyncio
    async def test_load_from_db_no_state_found(self) -> None:
        """Test loading state when no state exists in database."""
        mock_pool = MagicMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)

        state = await InitializerState.load_from_db(mock_pool)

        assert state.initialized is False
        assert state.initialized_at == 0
        assert state.relays_seeded == 0
        assert state.errors == []

    @pytest.mark.asyncio
    async def test_load_from_db_empty_state(self) -> None:
        """Test loading state when state column is empty."""
        mock_pool = MagicMock()
        mock_pool.fetchrow = AsyncMock(return_value={"state": None})

        state = await InitializerState.load_from_db(mock_pool)

        assert state.initialized is False
        assert state.initialized_at == 0

    @pytest.mark.asyncio
    async def test_load_from_db_on_exception(self) -> None:
        """Test loading state returns default on database error."""
        mock_pool = MagicMock()
        mock_pool.fetchrow = AsyncMock(side_effect=Exception("Database error"))

        state = await InitializerState.load_from_db(mock_pool)

        assert state.initialized is False
        assert state.initialized_at == 0
        assert state.relays_seeded == 0
        assert state.errors == []

    @pytest.mark.asyncio
    async def test_load_from_db_uses_correct_query(self) -> None:
        """Test that load_from_db queries for initializer service name."""
        mock_pool = MagicMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)

        await InitializerState.load_from_db(mock_pool, timeout=15.0)

        mock_pool.fetchrow.assert_called_once()
        call_args = mock_pool.fetchrow.call_args
        assert "service_state" in call_args[0][0]
        assert call_args[0][1] == "initializer"
        assert call_args[1]["timeout"] == 15.0
