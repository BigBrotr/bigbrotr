"""
Initializer Service for BigBrotr.

Handles database initialization and verification:
- Verify PostgreSQL extensions are installed
- Verify database schema (tables, procedures, views)
- Seed initial relay data as candidates for validation

This is a one-shot service that runs once at startup.

Usage:
    from core import Brotr
    from services import Initializer

    brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
    initializer = Initializer.from_yaml("yaml/services/initializer.yaml", brotr=brotr)

    async with brotr.pool:
        await initializer.run()
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

from core.base_service import BaseService
from models import Relay
from services.validator import Validator

if TYPE_CHECKING:
    from core.brotr import Brotr


# =============================================================================
# Configuration
# =============================================================================


class VerifyConfig(BaseModel):
    """What to verify during initialization."""

    extensions: bool = Field(default=True, description="Verify extensions exist")
    tables: bool = Field(default=True, description="Verify tables exist")
    procedures: bool = Field(default=True, description="Verify procedures exist")
    views: bool = Field(default=True, description="Verify views exist")


class SeedConfig(BaseModel):
    """Seed data configuration."""

    enabled: bool = Field(default=True, description="Enable seeding")
    file_path: str = Field(default="data/seed_relays.txt", description="Seed file path")
    max_retries: int = Field(default=3, ge=1, le=10, description="Max retries on failure")


class SchemaConfig(BaseModel):
    """Expected database schema elements."""

    extensions: list[str] = Field(
        default_factory=lambda: ["pgcrypto", "btree_gin"],
    )
    tables: list[str] = Field(
        default_factory=lambda: [
            "relays",
            "events",
            "events_relays",
            "metadata",
            "relay_metadata",
            "service_data",
        ],
    )
    procedures: list[str] = Field(
        default_factory=lambda: [
            "insert_event",
            "insert_relay",
            "insert_relay_metadata",
            "upsert_service_data",
            "delete_service_data",
        ],
    )
    views: list[str] = Field(
        default_factory=lambda: [
            "relay_metadata_latest",
        ],
    )


class InitializerConfig(BaseModel):
    """Complete initializer configuration."""

    verify: VerifyConfig = Field(default_factory=VerifyConfig)
    schema_: SchemaConfig = Field(default_factory=SchemaConfig, alias="schema")
    seed: SeedConfig = Field(default_factory=SeedConfig)


# =============================================================================
# Service
# =============================================================================


class Initializer(BaseService):
    """
    Database initialization service.

    Verifies that the database schema is correctly set up and seeds
    initial relay data. This is a one-shot service - run once at startup.

    The service checks:
    1. PostgreSQL extensions (pgcrypto, btree_gin)
    2. Required tables exist
    3. Stored procedures exist
    4. Required views exist
    5. Optionally seeds relay URLs from a file

    Raises InitializerError if verification fails.
    """

    SERVICE_NAME = "initializer"
    CONFIG_CLASS = InitializerConfig

    def __init__(
        self,
        brotr: Brotr,
        config: Optional[InitializerConfig] = None,
    ) -> None:
        super().__init__(brotr=brotr, config=config)

    # -------------------------------------------------------------------------
    # BaseService Implementation
    # -------------------------------------------------------------------------

    async def run(self) -> None:
        """
        Run initialization sequence.

        Verifies schema and seeds data.
        Raises InitializerError if any verification fails.
        """
        self._logger.info("run_started")
        start_time = time.time()

        # Verify extensions
        if self._config.verify.extensions:
            await self._verify_extensions()

        # Verify tables
        if self._config.verify.tables:
            await self._verify_tables()

        # Verify procedures
        if self._config.verify.procedures:
            await self._verify_procedures()

        # Verify views
        if self._config.verify.views:
            await self._verify_views()

        # Seed relays
        if self._config.seed.enabled:
            await self._seed_relays()

        # Record successful completion
        duration = time.time() - start_time
        await self._brotr.upsert_service_data([
            (self.SERVICE_NAME, "state", "completed", {
                "completed_at": int(time.time()),
                "duration_s": round(duration, 2),
            })
        ])

        self._logger.info("run_completed", duration_s=round(duration, 2))

    # -------------------------------------------------------------------------
    # Verification
    # -------------------------------------------------------------------------

    async def _verify_extensions(self) -> None:
        """Verify PostgreSQL extensions are installed."""
        expected = set(self._config.schema_.extensions)

        rows = await self._brotr.pool.fetch(
            "SELECT extname FROM pg_extension",
            timeout=self._brotr.config.timeouts.query,
        )
        installed = {row["extname"] for row in rows}
        missing = expected - installed

        if missing:
            raise InitializerError(f"Missing extensions: {', '.join(sorted(missing))}")

        self._logger.info("extensions_verified", count=len(expected))

    async def _verify_tables(self) -> None:
        """Verify required tables exist."""
        expected = set(self._config.schema_.tables)

        rows = await self._brotr.pool.fetch(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            """,
            timeout=self._brotr.config.timeouts.query,
        )
        existing = {row["table_name"] for row in rows}
        missing = expected - existing

        if missing:
            raise InitializerError(f"Missing tables: {', '.join(sorted(missing))}")

        self._logger.info("tables_verified", count=len(expected))

    async def _verify_procedures(self) -> None:
        """Verify stored procedures exist."""
        expected = set(self._config.schema_.procedures)

        rows = await self._brotr.pool.fetch(
            """
            SELECT routine_name FROM information_schema.routines
            WHERE routine_schema = 'public'
              AND routine_type IN ('FUNCTION', 'PROCEDURE')
            """,
            timeout=self._brotr.config.timeouts.query,
        )
        existing = {row["routine_name"] for row in rows}
        missing = expected - existing

        if missing:
            raise InitializerError(f"Missing procedures: {', '.join(sorted(missing))}")

        self._logger.info("procedures_verified", count=len(expected))

    async def _verify_views(self) -> None:
        """Verify required views exist."""
        expected = set(self._config.schema_.views)

        rows = await self._brotr.pool.fetch(
            """
            SELECT table_name FROM information_schema.views
            WHERE table_schema = 'public'
            """,
            timeout=self._brotr.config.timeouts.query,
        )
        existing = {row["table_name"] for row in rows}
        missing = expected - existing

        if missing:
            raise InitializerError(f"Missing views: {', '.join(sorted(missing))}")

        self._logger.info("views_verified", count=len(expected))

    # -------------------------------------------------------------------------
    # Seed Data
    # -------------------------------------------------------------------------

    def _parse_seed_file(self, path: Path) -> list[Relay]:
        """
        Parse seed file and validate relay URLs.

        Args:
            path: Path to the seed file

        Returns:
            List of validated Relay objects
        """
        relays: list[Relay] = []

        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    relays.append(Relay(line))
                except Exception as e:
                    self._logger.warning(
                        "seed_invalid_relay",
                        line=line,
                        error=str(e),
                    )

        return relays

    async def _seed_relays(self) -> None:
        """
        Load and insert seed relay data as candidates for validation.

        Inserts all seed relays atomically into the services table as candidates
        for the Validator service. If insertion fails, retries by re-reading the
        file up to max_retries times.
        """
        path = Path(self._config.seed.file_path)

        if not path.exists():
            self._logger.warning("seed_file_not_found", path=str(path))
            return

        max_retries = self._config.seed.max_retries
        last_error: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            # Re-read and parse file on each attempt
            relays = self._parse_seed_file(path)

            if not relays:
                self._logger.info("seed_no_valid_relays")
                return

            try:
                # Build records and insert in batches respecting max_batch_size
                records = [
                    (Validator.SERVICE_NAME, "candidate", relay._url_without_scheme, {"retries": 0})
                    for relay in relays
                ]
                batch_size = self._brotr.config.batch.max_batch_size
                for i in range(0, len(records), batch_size):
                    batch = records[i : i + batch_size]
                    await self._brotr.upsert_service_data(batch)

                self._logger.info("seed_completed", count=len(relays))
                return

            except Exception as e:
                last_error = e
                self._logger.warning(
                    "seed_attempt_failed",
                    attempt=attempt,
                    max_retries=max_retries,
                    error=str(e),
                )

        # All retries exhausted
        raise InitializerError(
            f"Failed to seed relays after {max_retries} attempts: {last_error}"
        )


class InitializerError(Exception):
    """Raised when initialization fails."""

    pass
