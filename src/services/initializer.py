"""
Initializer Service for BigBrotr.

Handles database initialization and verification:
- Verify PostgreSQL extensions are installed
- Verify database schema (tables, procedures, views)
- Seed initial relay data from file

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
from typing import TYPE_CHECKING, Any, Optional

from nostr_tools import Relay, RelayValidationError
from pydantic import BaseModel, Field

from core.base_service import BaseService

if TYPE_CHECKING:
    from core.brotr import Brotr

SERVICE_NAME = "initializer"


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
            "nip11",
            "nip66",
            "relay_metadata",
            "service_state",
        ],
    )
    procedures: list[str] = Field(
        default_factory=lambda: [
            "insert_event",
            "insert_relay",
            "insert_relay_metadata",
            "delete_orphan_events",
            "delete_orphan_nip11",
            "delete_orphan_nip66",
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

    SERVICE_NAME = SERVICE_NAME
    CONFIG_CLASS = InitializerConfig

    def __init__(
        self,
        brotr: Brotr,
        config: Optional[InitializerConfig] = None,
    ) -> None:
        """
        Initialize the service.

        Args:
            brotr: Brotr instance for database operations
            config: Service configuration (uses defaults if not provided)
        """
        super().__init__(brotr=brotr, config=config or InitializerConfig())
        self._config: InitializerConfig

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

        duration = time.time() - start_time
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

    async def _seed_relays(self) -> None:
        """Load and insert seed relay data from file."""
        path = Path(self._config.seed.file_path)

        if not path.exists():
            self._logger.warning("seed_file_not_found", path=str(path))
            return

        # Parse file and validate each line with Relay
        current_time = int(time.time())
        relays: list[dict[str, Any]] = []

        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    relay = Relay(line)
                    relays.append(
                        {
                            "url": relay.url,
                            "network": relay.network,
                            "inserted_at": current_time,
                        }
                    )
                except RelayValidationError:
                    pass

        if not relays:
            return

        # Insert in batches (respecting Brotr batch size)
        batch_size = self._brotr.config.batch.max_batch_size
        total = len(relays)
        inserted = 0

        for i in range(0, total, batch_size):
            batch = relays[i : i + batch_size]
            try:
                count = await self._brotr.insert_relays(batch)
                inserted += count
            except Exception as e:
                self._logger.error("seed_batch_failed", error=str(e), batch_start=i)

        self._logger.info("seed_completed", count=inserted, total=total)


class InitializerError(Exception):
    """Raised when initialization fails."""

    pass
