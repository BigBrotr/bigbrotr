"""
Initializer Service for BigBrotr Database Bootstrap.

This service handles database initialization tasks:
- Verify PostgreSQL extensions are installed
- Verify database schema (tables, indexes, procedures)
- Seed initial relay data from text files
- Provide health check and status reporting

Implements BackgroundService protocol for use with Service wrapper.

Example usage:
    from services.initializer import Initializer
    from core.brotr import Brotr
    from core.pool import Pool
    from core.service import Service

    pool = Pool(host="localhost", database="brotr")
    brotr = Brotr(pool=pool)
    initializer = Initializer(brotr=brotr)

    # Run initialization
    async with pool:
        result = await initializer.initialize()
        print(f"Initialization {'succeeded' if result.success else 'failed'}")

    # Or use with Service wrapper for logging/monitoring
    service = Service(initializer, name="initializer")
    async with service:
        result = await service.instance.initialize()
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml
from nostr_tools import Relay
from pydantic import BaseModel, Field, field_validator

from core.brotr import Brotr
from core.logger import get_service_logger, validate_log_level

_logger = logging.getLogger(__name__)

# ============================================================================
# Pydantic Models for Configuration Validation
# ============================================================================


class DatabaseVerificationConfig(BaseModel):
    """Database verification options."""

    verify_tables: bool = Field(default=True, description="Verify database tables exist")
    verify_procedures: bool = Field(default=True, description="Verify stored procedures exist")
    verify_extensions: bool = Field(default=True, description="Verify PostgreSQL extensions")


class SchemaFilesConfig(BaseModel):
    """Schema file paths configuration."""

    extensions: str = Field(
        default="postgres/init/00_extensions.sql", description="Path to extensions SQL file"
    )
    utility_functions: str = Field(
        default="postgres/init/01_utility_functions.sql",
        description="Path to utility functions SQL file",
    )
    tables: str = Field(
        default="postgres/init/02_tables.sql", description="Path to tables SQL file"
    )
    indexes: str = Field(
        default="postgres/init/03_indexes.sql", description="Path to indexes SQL file"
    )
    integrity_functions: str = Field(
        default="postgres/init/04_integrity_functions.sql",
        description="Path to integrity functions SQL file",
    )
    procedures: str = Field(
        default="postgres/init/05_procedures.sql", description="Path to procedures SQL file"
    )
    views: str = Field(default="postgres/init/06_views.sql", description="Path to views SQL file")
    verify: str = Field(
        default="postgres/init/99_verify.sql", description="Path to verification SQL file"
    )


class SeedDataConfig(BaseModel):
    """Seed data loading configuration."""

    enabled: bool = Field(default=True, description="Enable seed data loading")
    relay_file: str = Field(
        default="data/seed_relays.txt",
        min_length=1,
        description="Path to relay file (relative to base_path)",
    )
    batch_size: int = Field(default=100, ge=1, le=10000, description="Batch size for inserts")


class LoggingConfig(BaseModel):
    """Logging configuration."""

    log_verification_details: bool = Field(default=True, description="Log each verification step")
    log_seed_progress: bool = Field(default=True, description="Log seed data loading progress")
    log_level: str = Field(
        default="INFO", description="Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level_field(cls, v: str) -> str:
        """Validate log level using shared validator."""
        return validate_log_level(v)


class TimeoutsConfig(BaseModel):
    """Timeout configuration."""

    schema_verification: float = Field(
        default=30.0, ge=1.0, description="Schema check timeout (seconds)"
    )
    seed_data_load: float = Field(
        default=300.0, ge=1.0, description="Seed data loading timeout (seconds)"
    )


class RetryConfig(BaseModel):
    """Retry configuration for database operations."""

    max_attempts: int = Field(
        default=3, ge=1, le=10, description="Maximum retry attempts for DB operations"
    )
    initial_delay: float = Field(
        default=1.0, ge=0.1, description="Initial delay between retries (seconds)"
    )
    max_delay: float = Field(
        default=10.0, ge=0.1, description="Maximum delay between retries (seconds)"
    )
    exponential_backoff: bool = Field(
        default=True, description="Use exponential backoff for retries"
    )


# Fixed service name for initializer - other services depend on this exact name
INITIALIZER_SERVICE_NAME = "initializer"


class InitializerConfig(BaseModel):
    """Complete Initializer service configuration."""

    database: DatabaseVerificationConfig = Field(
        default_factory=DatabaseVerificationConfig, description="Database verification options"
    )
    schema_files: SchemaFilesConfig = Field(
        default_factory=SchemaFilesConfig, description="Schema file paths configuration"
    )
    expected_procedures: list[str] = Field(
        default_factory=lambda: [
            "insert_event",
            "insert_relay",
            "insert_relay_metadata",
            "delete_orphan_events",
            "delete_orphan_nip11",
            "delete_orphan_nip66",
        ],
        description="List of expected stored procedures to verify",
    )
    expected_tables: list[str] = Field(
        default_factory=lambda: [
            "relays",
            "events",
            "events_relays",
            "nip11",
            "nip66",
            "relay_metadata",
            "service_state",
        ],
        description="List of expected tables to verify",
    )
    expected_extensions: list[str] = Field(
        default_factory=lambda: ["pgcrypto", "btree_gin"],
        description="List of expected PostgreSQL extensions to verify",
    )
    seed_data: SeedDataConfig = Field(
        default_factory=SeedDataConfig, description="Seed data loading configuration"
    )
    logging: LoggingConfig = Field(
        default_factory=LoggingConfig, description="Logging configuration"
    )
    timeouts: TimeoutsConfig = Field(
        default_factory=TimeoutsConfig, description="Timeout configuration"
    )
    retry: RetryConfig = Field(
        default_factory=RetryConfig, description="Retry configuration for database operations"
    )


# ============================================================================
# Result Data Classes
# ============================================================================


@dataclass
class VerificationResult:
    """Result of a verification check."""

    name: str
    success: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0


@dataclass
class InitializationResult:
    """Complete initialization result."""

    success: bool
    message: str
    verifications: list[VerificationResult] = field(default_factory=list)
    relays_seeded: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "success": self.success,
            "message": self.message,
            "verifications": [
                {
                    "name": v.name,
                    "success": v.success,
                    "message": v.message,
                    "duration_ms": v.duration_ms,
                }
                for v in self.verifications
            ],
            "relays_seeded": self.relays_seeded,
            "duration_seconds": round(self.duration_seconds, 3),
            "errors": self.errors,
        }


@dataclass
class InitializerState:
    """Persistent state for the Initializer service."""

    initialized: bool = False
    initialized_at: int = 0  # Unix timestamp
    relays_seeded: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "initialized": self.initialized,
            "initialized_at": self.initialized_at,
            "relays_seeded": self.relays_seeded,
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InitializerState":
        """Create from dictionary."""
        return cls(
            initialized=data.get("initialized", False),
            initialized_at=data.get("initialized_at", 0),
            relays_seeded=data.get("relays_seeded", 0),
            errors=data.get("errors", []),
        )

    @staticmethod
    async def load_from_db(pool: Any, timeout: float = 30.0) -> "InitializerState":
        """
        Load initializer state from database.

        This static method allows dependent services to check the initializer's
        state without needing an Initializer instance. The state loading logic
        is centralized here to avoid duplication.

        Args:
            pool: Database pool (Pool or any object with fetchrow method)
            timeout: Query timeout in seconds

        Returns:
            InitializerState with current state, or default state if not found
        """
        try:
            query = "SELECT state FROM service_state WHERE service_name = $1"
            row = await pool.fetchrow(query, INITIALIZER_SERVICE_NAME, timeout=timeout)

            if row and row["state"]:
                state_data = row["state"]
                if isinstance(state_data, str):
                    state_data = json.loads(state_data)
                return InitializerState.from_dict(state_data)

            return InitializerState()

        except Exception as e:
            _logger.warning("Failed to load initializer state: %s", e)
            return InitializerState()


# ============================================================================
# Initializer Service
# ============================================================================


class Initializer:
    """
    Database initialization service for BigBrotr.

    Verifies database schema and seeds initial relay data.
    Implements BackgroundService protocol for Service wrapper compatibility.

    Features:
    - Verify PostgreSQL extensions (pgcrypto, btree_gin)
    - Verify tables, indexes, and stored procedures exist
    - Load seed relays from text files
    - Retry logic for transient database errors
    - Detailed logging and progress reporting

    Example:
        brotr = Brotr(pool=pool)
        initializer = Initializer(brotr=brotr)

        async with pool:
            result = await initializer.initialize()
            if result.success:
                print(f"Seeded {result.relays_seeded} relays")
    """

    def __init__(
        self,
        brotr: Brotr,
        config: Optional[InitializerConfig] = None,
        base_path: Optional[Path] = None,
    ) -> None:
        """
        Initialize the Initializer service.

        Args:
            brotr: Brotr instance (provides both database operations and pool access)
            config: Service configuration (uses defaults if not provided)
            base_path: Base path for relative file paths (e.g., implementations/bigbrotr/)
        """
        self._brotr = brotr
        self._config = config or InitializerConfig()
        self._base_path = base_path or Path("implementations/bigbrotr")
        self._is_running = False
        self._initialized = False
        self._state = InitializerState()
        self._logger = get_service_logger("initializer", "Initializer")

    # -------------------------------------------------------------------------
    # BackgroundService Protocol Implementation
    # -------------------------------------------------------------------------

    async def start(self) -> None:
        """Start the initializer service (runs initialization)."""
        self._is_running = True
        self._logger.info("initializer_starting")

    async def stop(self) -> None:
        """Stop the initializer service."""
        self._is_running = False
        self._logger.info("initializer_stopped")

    @property
    def is_running(self) -> bool:
        """Check if service is running."""
        return self._is_running

    # -------------------------------------------------------------------------
    # Factory Methods
    # -------------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, config_path: str, brotr: Brotr) -> "Initializer":
        """
        Create Initializer from YAML configuration file.

        Args:
            config_path: Path to YAML configuration file
            brotr: Brotr instance for database operations

        Returns:
            Configured Initializer instance
        """
        path = Path(config_path)
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls.from_dict(data, brotr=brotr, base_path=path.parent.parent)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        brotr: Brotr,
        base_path: Optional[Path] = None,
    ) -> "Initializer":
        """
        Create Initializer from dictionary configuration.

        Args:
            data: Configuration dictionary
            brotr: Brotr instance for database operations
            base_path: Base path for relative file paths

        Returns:
            Configured Initializer instance
        """
        config = InitializerConfig(**data)
        return cls(brotr=brotr, config=config, base_path=base_path)

    # -------------------------------------------------------------------------
    # Main Initialization
    # -------------------------------------------------------------------------

    async def initialize(self) -> InitializationResult:
        """
        Run complete database initialization.

        This method:
        1. Verifies PostgreSQL extensions
        2. Verifies tables exist
        3. Verifies stored procedures exist
        4. Seeds relay data (if enabled and needed)

        Returns:
            InitializationResult with success status and details
        """
        start_time = time.time()
        verifications: list[VerificationResult] = []
        errors: list[str] = []
        relays_seeded = 0

        self._logger.info("initialization_started", config=self._config.model_dump())

        try:
            # 1. Verify extensions
            if self._config.database.verify_extensions:
                result = await self._verify_extensions()
                verifications.append(result)
                if not result.success:
                    errors.append(f"Extension verification failed: {result.message}")

            # 2. Verify tables
            if self._config.database.verify_tables:
                result = await self._verify_tables()
                verifications.append(result)
                if not result.success:
                    errors.append(f"Table verification failed: {result.message}")

            # 3. Verify procedures
            if self._config.database.verify_procedures:
                result = await self._verify_procedures()
                verifications.append(result)
                if not result.success:
                    errors.append(f"Procedure verification failed: {result.message}")

            # 4. Seed relay data
            if self._config.seed_data.enabled:
                seed_result = await self._seed_relays()
                verifications.append(seed_result)
                if seed_result.success:
                    relays_seeded = seed_result.details.get("relays_inserted", 0)
                else:
                    errors.append(f"Seed data loading failed: {seed_result.message}")

            # Determine overall success
            success = len(errors) == 0
            duration = time.time() - start_time

            result = InitializationResult(
                success=success,
                message="Initialization completed successfully"
                if success
                else "Initialization completed with errors",
                verifications=verifications,
                relays_seeded=relays_seeded,
                duration_seconds=duration,
                errors=errors,
            )

            self._initialized = success

            # 5. Save state to service_state table
            self._state = InitializerState(
                initialized=success,
                initialized_at=int(time.time()),
                relays_seeded=relays_seeded,
                errors=errors,
            )
            await self._save_state()

            self._logger.info(
                "initialization_completed",
                success=success,
                duration_seconds=round(duration, 3),
                relays_seeded=relays_seeded,
                errors=errors,
            )

            return result

        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"Initialization failed with exception: {e}"
            self._logger.error(
                "initialization_failed", error=str(e), duration_seconds=round(duration, 3)
            )

            # Save failure state
            self._state = InitializerState(
                initialized=False,
                initialized_at=int(time.time()),
                relays_seeded=0,
                errors=[error_msg],
            )
            await self._save_state()

            return InitializationResult(
                success=False,
                message=error_msg,
                verifications=verifications,
                duration_seconds=duration,
                errors=[error_msg],
            )

    # -------------------------------------------------------------------------
    # Verification Methods
    # -------------------------------------------------------------------------

    async def _verify_extensions(self) -> VerificationResult:
        """Verify required PostgreSQL extensions are installed."""
        start_time = time.time()
        expected = set(self._config.expected_extensions)

        try:
            query = "SELECT extname FROM pg_extension"
            rows = await self._brotr.pool.fetch(
                query, timeout=self._config.timeouts.schema_verification
            )
            installed = {row["extname"] for row in rows}

            missing = expected - installed
            duration_ms = (time.time() - start_time) * 1000

            if missing:
                return VerificationResult(
                    name="extensions",
                    success=False,
                    message=f"Missing extensions: {', '.join(missing)}",
                    details={
                        "expected": list(expected),
                        "installed": list(installed),
                        "missing": list(missing),
                    },
                    duration_ms=duration_ms,
                )

            if self._config.logging.log_verification_details:
                self._logger.debug("extensions_verified", installed=list(installed & expected))

            return VerificationResult(
                name="extensions",
                success=True,
                message=f"All {len(expected)} extensions verified",
                details={"verified": list(expected)},
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return VerificationResult(
                name="extensions",
                success=False,
                message=f"Extension verification error: {e}",
                duration_ms=duration_ms,
            )

    async def _verify_tables(self) -> VerificationResult:
        """Verify required tables exist in the database."""
        start_time = time.time()
        expected = set(self._config.expected_tables)

        try:
            query = """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            """
            rows = await self._brotr.pool.fetch(
                query, timeout=self._config.timeouts.schema_verification
            )
            existing = {row["table_name"] for row in rows}

            missing = expected - existing
            duration_ms = (time.time() - start_time) * 1000

            if missing:
                return VerificationResult(
                    name="tables",
                    success=False,
                    message=f"Missing tables: {', '.join(missing)}",
                    details={
                        "expected": list(expected),
                        "existing": list(existing),
                        "missing": list(missing),
                    },
                    duration_ms=duration_ms,
                )

            if self._config.logging.log_verification_details:
                self._logger.debug("tables_verified", verified=list(expected))

            return VerificationResult(
                name="tables",
                success=True,
                message=f"All {len(expected)} tables verified",
                details={"verified": list(expected)},
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return VerificationResult(
                name="tables",
                success=False,
                message=f"Table verification error: {e}",
                duration_ms=duration_ms,
            )

    async def _verify_procedures(self) -> VerificationResult:
        """Verify required stored procedures/functions exist."""
        start_time = time.time()
        expected = set(self._config.expected_procedures)

        try:
            query = """
                SELECT routine_name
                FROM information_schema.routines
                WHERE routine_schema = 'public'
                  AND routine_type IN ('FUNCTION', 'PROCEDURE')
            """
            rows = await self._brotr.pool.fetch(
                query, timeout=self._config.timeouts.schema_verification
            )
            existing = {row["routine_name"] for row in rows}

            missing = expected - existing
            duration_ms = (time.time() - start_time) * 1000

            if missing:
                return VerificationResult(
                    name="procedures",
                    success=False,
                    message=f"Missing procedures: {', '.join(missing)}",
                    details={
                        "expected": list(expected),
                        "existing": list(existing),
                        "missing": list(missing),
                    },
                    duration_ms=duration_ms,
                )

            if self._config.logging.log_verification_details:
                self._logger.debug("procedures_verified", verified=list(expected))

            return VerificationResult(
                name="procedures",
                success=True,
                message=f"All {len(expected)} procedures verified",
                details={"verified": list(expected)},
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return VerificationResult(
                name="procedures",
                success=False,
                message=f"Procedure verification error: {e}",
                duration_ms=duration_ms,
            )

    # -------------------------------------------------------------------------
    # Seed Data Loading
    # -------------------------------------------------------------------------

    async def _seed_relays(self) -> VerificationResult:
        """Load and insert seed relay data from configured file."""
        start_time = time.time()

        try:
            # Load relays from file
            relay_urls = self._load_relay_file()

            if not relay_urls:
                duration_ms = (time.time() - start_time) * 1000
                return VerificationResult(
                    name="seed_data",
                    success=True,
                    message="No relays to seed (file empty or not found)",
                    details={"relays_loaded": 0, "relays_inserted": 0},
                    duration_ms=duration_ms,
                )

            # Insert in batches (network auto-detected, duplicates ignored by DB)
            inserted = await self._insert_relays_batched(relay_urls)

            if self._config.logging.log_seed_progress:
                self._logger.info(
                    "seed_relays_completed",
                    file=self._config.seed_data.relay_file,
                    loaded=len(relay_urls),
                    inserted=inserted,
                )

            duration_ms = (time.time() - start_time) * 1000

            return VerificationResult(
                name="seed_data",
                success=True,
                message=f"Seeded {inserted} relays from {self._config.seed_data.relay_file}",
                details={
                    "relays_loaded": len(relay_urls),
                    "relays_inserted": inserted,
                },
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return VerificationResult(
                name="seed_data",
                success=False,
                message=f"Seed data loading error: {e}",
                duration_ms=duration_ms,
            )

    def _load_relay_file(self) -> list[str]:
        """
        Load relay URLs from the configured seed file.

        Returns:
            List of relay URLs (cleaned and deduplicated)
        """
        file_path = self._base_path / self._config.seed_data.relay_file
        relays: list[str] = []

        if not file_path.exists():
            self._logger.warning("relay_file_not_found", path=str(file_path))
            return relays

        try:
            with file_path.open(encoding="utf-8") as f:
                for line in f:
                    # Clean and validate line
                    url = line.strip()
                    if url and url.startswith("wss://"):
                        relays.append(url)

            # Deduplicate while preserving order
            seen: set[str] = set()
            unique_relays: list[str] = []
            for url in relays:
                if url not in seen:
                    seen.add(url)
                    unique_relays.append(url)

            return unique_relays

        except Exception as e:
            self._logger.error("relay_file_load_error", path=str(file_path), error=str(e))
            return []

    async def _insert_relays_batched(self, relay_urls: list[str]) -> int:
        """
        Insert relays in batches using self._brotr.

        Network type is auto-detected from URL using nostr_tools.Relay.

        Args:
            relay_urls: List of relay URLs to insert

        Returns:
            Number of relays successfully inserted
        """
        batch_size = self._config.seed_data.batch_size
        inserted = 0
        current_time = int(time.time())

        for i in range(0, len(relay_urls), batch_size):
            batch = relay_urls[i : i + batch_size]

            # Prepare relay records using nostr_tools.Relay for network detection
            relay_records = []
            for url in batch:
                relay = Relay(url)
                relay_records.append(
                    {
                        "url": relay.url,
                        "network": relay.network,
                        "inserted_at": current_time,
                    }
                )

            # Insert with retry
            batch_inserted = False
            for attempt in range(self._config.retry.max_attempts):
                try:
                    success = await self._brotr.insert_relays(relay_records)
                    if success:
                        inserted += len(batch)
                        batch_inserted = True
                        break
                    # insert_relays returned False - treat as failure
                    elif attempt < self._config.retry.max_attempts - 1:
                        delay = self._calculate_retry_delay(attempt)
                        self._logger.warning(
                            "relay_insert_retry",
                            attempt=attempt + 1,
                            delay=delay,
                            reason="insert_relays returned False",
                        )
                        await asyncio.sleep(delay)
                except Exception as e:
                    if attempt < self._config.retry.max_attempts - 1:
                        delay = self._calculate_retry_delay(attempt)
                        self._logger.warning(
                            "relay_insert_retry",
                            attempt=attempt + 1,
                            delay=delay,
                            error=str(e),
                        )
                        await asyncio.sleep(delay)
                    else:
                        self._logger.error(
                            "relay_insert_failed",
                            batch_start=i,
                            batch_size=len(batch),
                            error=str(e),
                        )

            if not batch_inserted:
                self._logger.warning(
                    "relay_batch_not_inserted",
                    batch_start=i,
                    batch_size=len(batch),
                )

        return inserted

    def _calculate_retry_delay(self, attempt: int) -> float:
        """Calculate retry delay with optional exponential backoff."""
        if self._config.retry.exponential_backoff:
            delay = self._config.retry.initial_delay * (2**attempt)
        else:
            delay = self._config.retry.initial_delay
        return min(delay, self._config.retry.max_delay)

    async def _get_relay_count(self) -> int:
        """Get current relay count from database."""
        try:
            query = "SELECT COUNT(*) as count FROM relays"
            row = await self._brotr.pool.fetchrow(
                query, timeout=self._config.timeouts.schema_verification
            )
            return row["count"] if row else 0
        except Exception as e:
            _logger.debug("Failed to get relay count: %s", e)
            return 0

    # -------------------------------------------------------------------------
    # State Management
    # -------------------------------------------------------------------------

    async def _save_state(self) -> None:
        """Save current state to service_state table."""
        try:
            state_json = json.dumps(self._state.to_dict())
            current_time = int(time.time())

            query = """
                INSERT INTO service_state (service_name, state, updated_at)
                VALUES ($1, $2::jsonb, $3)
                ON CONFLICT (service_name)
                DO UPDATE SET state = $2::jsonb, updated_at = $3
            """
            await self._brotr.pool.execute(
                query,
                INITIALIZER_SERVICE_NAME,
                state_json,
                current_time,
                timeout=self._config.timeouts.schema_verification,
            )
            self._logger.debug("state_saved", state=self._state.to_dict())

        except Exception as e:
            self._logger.warning("state_save_error", error=str(e))

    async def _load_state(self) -> None:
        """
        Load persisted state from service_state table.

        Restores initialization state from database, allowing the service
        to resume or skip re-initialization if already completed successfully.
        """
        self._state = await InitializerState.load_from_db(
            self._brotr.pool,
            timeout=self._config.timeouts.schema_verification,
        )
        self._initialized = self._state.initialized
        self._logger.debug("state_loaded", state=self._state.to_dict())

    # -------------------------------------------------------------------------
    # Health Check
    # -------------------------------------------------------------------------

    async def health_check(self) -> bool:
        """
        Check if initialization was successful.

        Returns:
            True if initialized successfully, False otherwise
        """
        return self._initialized

    # -------------------------------------------------------------------------
    # Status and Information
    # -------------------------------------------------------------------------

    @property
    def config(self) -> InitializerConfig:
        """Get current configuration (read-only)."""
        return self._config

    @property
    def initialized(self) -> bool:
        """Check if initialization completed successfully."""
        return self._initialized

    @property
    def state(self) -> InitializerState:
        """Get current state (read-only)."""
        return self._state

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"Initializer(" f"initialized={self._initialized}, " f"base_path='{self._base_path}')"
        )
