"""
Initializer Service for BigBrotr.

Handles database initialization:
- Verify PostgreSQL extensions
- Verify database schema (tables, procedures)
- Seed initial relay data

Usage:
    # Standalone
    initializer = Initializer(brotr=brotr)
    async with brotr.pool:
        result = await initializer.run()

    # With context manager (auto start/stop)
    async with brotr.pool:
        async with initializer:
            result = await initializer.run()
"""

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from core.base_service import BaseService, Outcome, Step
from core.brotr import Brotr
from core.utils import build_relay_records


SERVICE_NAME = "initializer"


# ============================================================================
# Configuration
# ============================================================================


class VerificationConfig(BaseModel):
    """What to verify during initialization."""

    tables: bool = Field(default=True, description="Verify tables exist")
    procedures: bool = Field(default=True, description="Verify procedures exist")
    extensions: bool = Field(default=True, description="Verify extensions exist")


class SeedConfig(BaseModel):
    """Seed data configuration."""

    enabled: bool = Field(default=True, description="Enable seeding")
    path: str = Field(default="data/seed_relays.txt", description="Seed file path")
    batch_size: int = Field(default=100, ge=1, le=10000, description="Insert batch size")


class ExpectedSchemaConfig(BaseModel):
    """Expected database schema."""

    extensions: list[str] = Field(
        default_factory=lambda: ["pgcrypto", "btree_gin"],
    )
    tables: list[str] = Field(
        default_factory=lambda: [
            "relays", "events", "events_relays", "nip11", "nip66",
            "relay_metadata", "service_state",
        ],
    )
    procedures: list[str] = Field(
        default_factory=lambda: [
            "insert_event", "insert_relay", "insert_relay_metadata",
            "delete_orphan_events", "delete_orphan_nip11", "delete_orphan_nip66",
        ],
    )


class RetryConfig(BaseModel):
    """Retry configuration."""

    max_attempts: int = Field(default=3, ge=1, le=10)
    initial_delay: float = Field(default=1.0, ge=0.1)
    max_delay: float = Field(default=10.0, ge=0.1)
    exponential_backoff: bool = Field(default=True)


class InitializerConfig(BaseModel):
    """Complete configuration."""

    verification: VerificationConfig = Field(default_factory=VerificationConfig)
    expected_schema: ExpectedSchemaConfig = Field(default_factory=ExpectedSchemaConfig)
    seed: SeedConfig = Field(default_factory=SeedConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)


# ============================================================================
# State
# ============================================================================


@dataclass
class InitializerState:
    """Persistent state."""

    initialized: bool = False
    initialized_at: int = 0
    relays_seeded: int = 0
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "initialized": self.initialized,
            "initialized_at": self.initialized_at,
            "relays_seeded": self.relays_seeded,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InitializerState":
        return cls(
            initialized=data.get("initialized", False),
            initialized_at=data.get("initialized_at", 0),
            relays_seeded=data.get("relays_seeded", 0),
            last_error=data.get("last_error", ""),
        )


# ============================================================================
# Service
# ============================================================================


class Initializer(BaseService[InitializerState]):
    """
    Database initialization service.

    Verifies schema and seeds initial data. Run once at startup.
    """

    SERVICE_NAME = SERVICE_NAME
    CONFIG_CLASS = InitializerConfig

    def __init__(
        self,
        brotr: Brotr,
        config: Optional[InitializerConfig] = None,
    ) -> None:
        """
        Initialize service.

        Args:
            brotr: Brotr instance for database operations
            config: Service configuration
        """
        super().__init__(brotr=brotr, config=config)
        self._config: InitializerConfig = config or InitializerConfig()

    # -------------------------------------------------------------------------
    # BaseService Implementation
    # -------------------------------------------------------------------------

    def _create_default_state(self) -> InitializerState:
        return InitializerState()

    def _state_from_dict(self, data: dict[str, Any]) -> InitializerState:
        return InitializerState.from_dict(data)

    async def health_check(self) -> bool:
        """Service is healthy if initialization completed."""
        return self._state.initialized

    async def run(self) -> Outcome:
        """
        Run initialization.

        Returns:
            Outcome with success status and metrics
        """
        start_time = time.time()
        steps: list[Step] = []
        errors: list[str] = []
        relays_seeded = 0

        self._logger.info("run_started")

        try:
            # Verify extensions
            if self._config.verification.extensions:
                step = await self._verify_extensions()
                steps.append(step)
                if not step.success:
                    errors.append(f"Extensions: {step.message}")

            # Verify tables
            if self._config.verification.tables:
                step = await self._verify_tables()
                steps.append(step)
                if not step.success:
                    errors.append(f"Tables: {step.message}")

            # Verify procedures
            if self._config.verification.procedures:
                step = await self._verify_procedures()
                steps.append(step)
                if not step.success:
                    errors.append(f"Procedures: {step.message}")

            # Seed data
            if self._config.seed.enabled:
                step = await self._seed_relays()
                steps.append(step)
                if step.success:
                    relays_seeded = step.details.get("inserted", 0)
                else:
                    errors.append(f"Seed: {step.message}")

            # Update state
            success = len(errors) == 0
            self._state = InitializerState(
                initialized=success,
                initialized_at=int(time.time()),
                relays_seeded=relays_seeded,
                last_error=errors[0] if errors else "",
            )
            await self._save_state()

            duration = time.time() - start_time
            self._logger.info(
                "run_completed",
                success=success,
                duration_s=round(duration, 2),
                relays_seeded=relays_seeded,
            )

            return Outcome(
                success=success,
                message="Initialization completed" if success else "Initialization failed",
                steps=steps,
                duration_s=duration,
                errors=errors,
                metrics={"relays_seeded": relays_seeded},
            )

        except Exception as e:
            error_msg = str(e)
            self._state = InitializerState(
                initialized=False,
                initialized_at=int(time.time()),
                last_error=error_msg,
            )
            await self._save_state()

            self._logger.error("run_failed", error=error_msg)

            return Outcome(
                success=False,
                message=f"Initialization failed: {error_msg}",
                steps=steps,
                duration_s=time.time() - start_time,
                errors=[error_msg],
                metrics={},
            )

    # -------------------------------------------------------------------------
    # Verification Methods
    # -------------------------------------------------------------------------

    async def _verify_extensions(self) -> Step:
        """Verify PostgreSQL extensions."""
        start = time.time()
        expected = set(self._config.expected_schema.extensions)

        try:
            rows = await self._pool.fetch("SELECT extname FROM pg_extension")
            installed = {row["extname"] for row in rows}
            missing = expected - installed
            duration_ms = (time.time() - start) * 1000

            if missing:
                return Step(
                    name="extensions",
                    success=False,
                    message=f"Missing: {', '.join(missing)}",
                    details={"missing": list(missing)},
                    duration_ms=duration_ms,
                )

            self._logger.debug("extensions_verified", count=len(expected))
            return Step(
                name="extensions",
                success=True,
                message=f"Verified {len(expected)} extensions",
                duration_ms=duration_ms,
            )

        except Exception as e:
            return Step(
                name="extensions",
                success=False,
                message=str(e),
                duration_ms=(time.time() - start) * 1000,
            )

    async def _verify_tables(self) -> Step:
        """Verify database tables."""
        start = time.time()
        expected = set(self._config.expected_schema.tables)

        try:
            query = """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            """
            rows = await self._pool.fetch(query)
            existing = {row["table_name"] for row in rows}
            missing = expected - existing
            duration_ms = (time.time() - start) * 1000

            if missing:
                return Step(
                    name="tables",
                    success=False,
                    message=f"Missing: {', '.join(missing)}",
                    details={"missing": list(missing)},
                    duration_ms=duration_ms,
                )

            self._logger.debug("tables_verified", count=len(expected))
            return Step(
                name="tables",
                success=True,
                message=f"Verified {len(expected)} tables",
                duration_ms=duration_ms,
            )

        except Exception as e:
            return Step(
                name="tables",
                success=False,
                message=str(e),
                duration_ms=(time.time() - start) * 1000,
            )

    async def _verify_procedures(self) -> Step:
        """Verify stored procedures."""
        start = time.time()
        expected = set(self._config.expected_schema.procedures)

        try:
            query = """
                SELECT routine_name FROM information_schema.routines
                WHERE routine_schema = 'public' AND routine_type IN ('FUNCTION', 'PROCEDURE')
            """
            rows = await self._pool.fetch(query)
            existing = {row["routine_name"] for row in rows}
            missing = expected - existing
            duration_ms = (time.time() - start) * 1000

            if missing:
                return Step(
                    name="procedures",
                    success=False,
                    message=f"Missing: {', '.join(missing)}",
                    details={"missing": list(missing)},
                    duration_ms=duration_ms,
                )

            self._logger.debug("procedures_verified", count=len(expected))
            return Step(
                name="procedures",
                success=True,
                message=f"Verified {len(expected)} procedures",
                duration_ms=duration_ms,
            )

        except Exception as e:
            return Step(
                name="procedures",
                success=False,
                message=str(e),
                duration_ms=(time.time() - start) * 1000,
            )

    # -------------------------------------------------------------------------
    # Seed Data
    # -------------------------------------------------------------------------

    async def _seed_relays(self) -> Step:
        """Load and insert seed relay data."""
        start = time.time()

        try:
            urls = self._load_seed_file()

            if not urls:
                return Step(
                    name="seed",
                    success=True,
                    message="No relays to seed",
                    details={"loaded": 0, "inserted": 0},
                    duration_ms=(time.time() - start) * 1000,
                )

            inserted = await self._insert_relays(urls)

            self._logger.info("seed_completed", loaded=len(urls), inserted=inserted)

            return Step(
                name="seed",
                success=True,
                message=f"Seeded {inserted} relays",
                details={"loaded": len(urls), "inserted": inserted},
                duration_ms=(time.time() - start) * 1000,
            )

        except Exception as e:
            return Step(
                name="seed",
                success=False,
                message=str(e),
                duration_ms=(time.time() - start) * 1000,
            )

    def _load_seed_file(self) -> list[str]:
        """Load URLs from seed file."""
        path = Path(self._config.seed.path)

        if not path.exists():
            self._logger.warning("seed_file_not_found", path=str(path))
            return []

        try:
            with path.open(encoding="utf-8") as f:
                urls = [line.strip() for line in f if line.strip().startswith("wss://")]
            return list(dict.fromkeys(urls))  # Dedupe preserving order

        except Exception as e:
            self._logger.error("seed_file_error", error=str(e))
            return []

    async def _insert_relays(self, urls: list[str]) -> int:
        """Insert relays with retry."""
        batch_size = self._config.seed.batch_size
        inserted = 0
        current_time = int(time.time())

        for i in range(0, len(urls), batch_size):
            batch = urls[i : i + batch_size]
            records = build_relay_records(batch, current_time)

            if not records:
                continue

            for attempt in range(self._config.retry.max_attempts):
                try:
                    async with self._pool.transaction() as conn:
                        for r in records:
                            await conn.execute(
                                "SELECT insert_relay($1, $2, $3)",
                                r["url"], r["network"], r["inserted_at"],
                            )
                    inserted += len(records)
                    break

                except Exception as e:
                    if attempt < self._config.retry.max_attempts - 1:
                        delay = self._calculate_delay(attempt)
                        await asyncio.sleep(delay)
                    else:
                        self._logger.warning("batch_insert_failed", batch=i, error=str(e))

        return inserted

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate retry delay."""
        if self._config.retry.exponential_backoff:
            delay = self._config.retry.initial_delay * (2 ** attempt)
        else:
            delay = self._config.retry.initial_delay
        return min(delay, self._config.retry.max_delay)

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------

    @property
    def config(self) -> InitializerConfig:
        """Get configuration."""
        return self._config

    @property
    def initialized(self) -> bool:
        """Check if initialization completed."""
        return self._state.initialized