"""
Finder Service for BigBrotr.

Discovers Nostr relay URLs from multiple sources:
- Database events: Scans event content for relay URLs
- External APIs: Fetches relay lists from nostr.watch etc.

Usage:
    # Single discovery cycle
    finder = Finder(pool=pool, brotr=brotr)
    async with pool:
        result = await finder.run()

    # Continuous discovery
    async with pool:
        async with finder:
            await finder.run_forever(interval=3600)
"""

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import aiohttp
import yaml
from nostr_tools import find_ws_urls
from pydantic import BaseModel, Field, field_validator

from core.base_service import BaseService, Outcome
from core.brotr import Brotr
from core.logger import validate_log_level
from core.pool import Pool
from core.utils import build_relay_records, load_service_state

from .initializer import InitializerState


SERVICE_NAME = "finder"


# ============================================================================
# Configuration
# ============================================================================


class EventScanConfig(BaseModel):
    """Event scanning configuration."""

    enabled: bool = Field(default=True, description="Enable event scanning")
    batch_size: int = Field(default=1000, ge=100, le=10000, description="Events per batch")
    max_events_per_cycle: int = Field(default=100000, ge=1000, le=1000000, description="Max per cycle")


class ApiSourceConfig(BaseModel):
    """Single API source."""

    url: str = Field(description="API endpoint URL")
    enabled: bool = Field(default=True, description="Enable this source")
    timeout: float = Field(default=30.0, ge=1.0, le=120.0, description="Request timeout")


class ApiConfig(BaseModel):
    """API fetching configuration."""

    enabled: bool = Field(default=True, description="Enable API fetching")
    sources: list[ApiSourceConfig] = Field(
        default_factory=lambda: [
            ApiSourceConfig(url="https://api.nostr.watch/v1/online"),
            ApiSourceConfig(url="https://api.nostr.watch/v1/offline"),
        ]
    )
    request_delay: float = Field(default=1.0, ge=0.0, le=10.0, description="Delay between requests")


class LoggingConfig(BaseModel):
    """Logging configuration."""

    log_progress: bool = Field(default=True, description="Log progress")
    log_level: str = Field(default="INFO", description="Log level")
    progress_interval: int = Field(default=5000, ge=100, le=50000, description="Progress interval")

    @field_validator("log_level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        return validate_log_level(v)


class TimeoutsConfig(BaseModel):
    """Timeout configuration."""

    db_query: float = Field(default=30.0, ge=5.0, le=120.0, description="DB query timeout")


class FinderConfig(BaseModel):
    """Complete configuration."""

    event_scan: EventScanConfig = Field(default_factory=EventScanConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    insert_batch_size: int = Field(default=100, ge=10, le=1000, description="Insert batch size")
    discovery_interval: float = Field(default=3600.0, ge=60.0, le=86400.0, description="Cycle interval")


# ============================================================================
# State
# ============================================================================


@dataclass
class FinderState:
    """Persistent state."""

    last_seen_at: int = 0  # Watermark for event scanning
    total_events_processed: int = 0
    total_relays_found: int = 0
    last_run_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_seen_at": self.last_seen_at,
            "total_events_processed": self.total_events_processed,
            "total_relays_found": self.total_relays_found,
            "last_run_at": self.last_run_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FinderState":
        return cls(
            last_seen_at=data.get("last_seen_at", 0),
            total_events_processed=data.get("total_events_processed", 0),
            total_relays_found=data.get("total_relays_found", 0),
            last_run_at=data.get("last_run_at", 0),
        )


# ============================================================================
# Service
# ============================================================================


class Finder(BaseService[FinderState]):
    """
    Relay discovery service.

    Discovers Nostr relay URLs from database events and external APIs.
    Uses watermark-based batch processing for crash consistency.
    """

    SERVICE_NAME = SERVICE_NAME

    def __init__(
        self,
        pool: Pool,
        brotr: Optional[Brotr] = None,
        config: Optional[FinderConfig] = None,
    ) -> None:
        """
        Initialize service.

        Args:
            pool: Database pool
            brotr: Brotr instance for relay insertion (creates default if None)
            config: Service configuration
        """
        super().__init__(pool=pool, config=config)
        self._config: FinderConfig = config or FinderConfig()
        self._brotr = brotr or Brotr(pool=pool)
        self._found_urls: set[str] = set()

    # -------------------------------------------------------------------------
    # BaseService Implementation
    # -------------------------------------------------------------------------

    def _create_default_state(self) -> FinderState:
        return FinderState()

    def _state_from_dict(self, data: dict[str, Any]) -> FinderState:
        return FinderState.from_dict(data)

    async def health_check(self) -> bool:
        """Service is healthy if database is connected."""
        try:
            result = await self._pool.fetchval(
                "SELECT 1", timeout=self._config.timeouts.db_query
            )
            return result == 1
        except Exception:
            return False

    async def run(self) -> Outcome:
        """
        Run single discovery cycle.

        Returns:
            Outcome with statistics
        """
        start_time = time.time()
        errors: list[str] = []
        self._found_urls.clear()

        self._logger.info("run_started")

        try:
            # Check initializer completed
            if not await self._check_initializer():
                return Outcome(
                    success=False,
                    message="Initializer not completed",
                    duration_s=time.time() - start_time,
                    errors=["Initializer must complete first"],
                    metrics={},
                )

            # Fetch from APIs
            api_count = 0
            if self._config.api.enabled:
                result = await self._fetch_from_apis()
                api_count = result["sources_checked"]
                errors.extend(result.get("errors", []))

            # Scan database events
            events_scanned = 0
            event_relays_inserted = 0
            if self._config.event_scan.enabled:
                result = await self._scan_events()
                events_scanned = result["events_scanned"]
                event_relays_inserted = result.get("relays_inserted", 0)
                errors.extend(result.get("errors", []))

            # Insert API-discovered relays
            api_relays_inserted = 0
            if api_count > 0 and self._found_urls:
                api_relays_inserted = await self._insert_api_relays()

            # Update state
            self._state.last_run_at = int(time.time())
            await self._save_state()

            duration = time.time() - start_time
            success = len(errors) == 0

            self._logger.info(
                "run_completed",
                success=success,
                duration_s=round(duration, 2),
                relays_found=len(self._found_urls),
            )

            return Outcome(
                success=success,
                message="Discovery completed" if success else "Completed with errors",
                duration_s=duration,
                errors=errors,
                metrics={
                    "relays_found": len(self._found_urls),
                    "relays_inserted": event_relays_inserted + api_relays_inserted,
                    "events_scanned": events_scanned,
                    "api_sources_checked": api_count,
                },
            )

        except Exception as e:
            error_msg = str(e)
            self._logger.error("run_failed", error=error_msg)
            return Outcome(
                success=False,
                message=f"Discovery failed: {error_msg}",
                duration_s=time.time() - start_time,
                errors=[error_msg],
                metrics={},
            )

    # -------------------------------------------------------------------------
    # Factory Methods
    # -------------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, config_path: str, pool: Pool, brotr: Optional[Brotr] = None) -> "Finder":
        """Create from YAML file."""
        with Path(config_path).open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data, pool=pool, brotr=brotr)

    @classmethod
    def from_dict(cls, data: dict[str, Any], pool: Pool, brotr: Optional[Brotr] = None) -> "Finder":
        """Create from dictionary."""
        config = FinderConfig(**data)
        return cls(pool=pool, brotr=brotr, config=config)

    # -------------------------------------------------------------------------
    # Initializer Check
    # -------------------------------------------------------------------------

    async def _check_initializer(self) -> bool:
        """Check if initializer has completed."""
        state_data = await load_service_state(
            self._pool, "initializer", self._config.timeouts.db_query
        )
        if state_data:
            state = InitializerState.from_dict(state_data)
            if state.initialized:
                return True

        self._logger.warning("initializer_not_completed")
        return False

    # -------------------------------------------------------------------------
    # API Fetching
    # -------------------------------------------------------------------------

    async def _fetch_from_apis(self) -> dict[str, Any]:
        """Fetch relay URLs from APIs."""
        sources_checked = 0
        errors: list[str] = []

        for source in self._config.api.sources:
            if not source.enabled:
                continue

            try:
                urls = await self._fetch_api_source(source)
                self._found_urls.update(urls)
                sources_checked += 1

                if self._config.logging.log_progress:
                    self._logger.debug("api_fetched", url=source.url, count=len(urls))

                if self._config.api.request_delay > 0:
                    await asyncio.sleep(self._config.api.request_delay)

            except Exception as e:
                errors.append(f"API {source.url}: {e}")
                self._logger.warning("api_error", url=source.url, error=str(e))

        return {"sources_checked": sources_checked, "errors": errors}

    async def _fetch_api_source(self, source: ApiSourceConfig) -> set[str]:
        """Fetch from single API source."""
        urls: set[str] = set()

        async with (
            aiohttp.ClientSession() as session,
            session.get(source.url, timeout=aiohttp.ClientTimeout(total=source.timeout)) as resp,
        ):
            resp.raise_for_status()
            data = await resp.json()

            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str) and item.startswith("wss://"):
                        urls.add(item)

        return urls

    # -------------------------------------------------------------------------
    # Event Scanning
    # -------------------------------------------------------------------------

    async def _scan_events(self) -> dict[str, Any]:
        """Scan events for relay URLs (atomic batch processing)."""
        events_scanned = 0
        relays_inserted = 0
        errors: list[str] = []

        try:
            batch_size = self._config.event_scan.batch_size
            max_events = self._config.event_scan.max_events_per_cycle
            watermark = self._state.last_seen_at

            while events_scanned < max_events:
                # Fetch batch
                query = """
                    SELECT er.event_id, er.seen_at, e.content
                    FROM events_relays er
                    JOIN events e ON e.id = er.event_id
                    WHERE er.seen_at > $1
                    ORDER BY er.seen_at ASC
                    LIMIT $2
                """
                rows = await self._pool.fetch(
                    query, watermark, batch_size,
                    timeout=self._config.timeouts.db_query
                )

                if not rows:
                    break

                # Extract URLs
                batch_urls: set[str] = set()
                for row in rows:
                    content = row.get("content", "")
                    if content:
                        try:
                            urls = find_ws_urls(content)
                            if urls:
                                batch_urls.update(urls)
                        except Exception:
                            pass

                batch_max_seen_at = max(row["seen_at"] for row in rows)

                # Atomic commit
                batch_inserted = await self._commit_batch(
                    batch_urls, batch_max_seen_at, len(rows)
                )
                relays_inserted += batch_inserted

                watermark = batch_max_seen_at
                events_scanned += len(rows)
                self._found_urls.update(batch_urls)

                # Progress logging
                if (
                    self._config.logging.log_progress
                    and events_scanned % self._config.logging.progress_interval == 0
                ):
                    self._logger.debug(
                        "scan_progress",
                        events=events_scanned,
                        relays=len(self._found_urls),
                    )

        except Exception as e:
            errors.append(f"Scan error: {e}")
            self._logger.error("scan_error", error=str(e))

        return {"events_scanned": events_scanned, "relays_inserted": relays_inserted, "errors": errors}

    async def _commit_batch(
        self, urls: set[str], new_watermark: int, events_count: int
    ) -> int:
        """Atomically commit batch: insert relays + update watermark."""
        inserted = 0
        current_time = int(time.time())
        records = build_relay_records(urls, current_time)

        async with self._pool.transaction() as conn:
            # Insert relays
            if records:
                for r in records:
                    try:
                        await conn.execute(
                            "SELECT insert_relay($1, $2, $3)",
                            r["url"], r["network"], r["inserted_at"],
                        )
                        inserted += 1
                    except Exception:
                        pass  # Skip duplicates

            # Update state atomically
            new_total_events = self._state.total_events_processed + events_count
            new_total_relays = self._state.total_relays_found + inserted

            state_json = json.dumps({
                "last_seen_at": new_watermark,
                "total_events_processed": new_total_events,
                "total_relays_found": new_total_relays,
                "last_run_at": self._state.last_run_at,
            })

            await conn.execute(
                """
                INSERT INTO service_state (service_name, state, updated_at)
                VALUES ($1, $2::jsonb, $3)
                ON CONFLICT (service_name) DO UPDATE SET state = $2::jsonb, updated_at = $3
                """,
                SERVICE_NAME, state_json, current_time,
            )

        # Update in-memory state after commit
        self._state.last_seen_at = new_watermark
        self._state.total_events_processed += events_count
        self._state.total_relays_found += inserted

        return inserted

    # -------------------------------------------------------------------------
    # API Relay Insertion
    # -------------------------------------------------------------------------

    async def _insert_api_relays(self) -> int:
        """Insert API-discovered relays."""
        if not self._found_urls:
            return 0

        inserted = 0
        current_time = int(time.time())
        batch_size = self._config.insert_batch_size
        urls_list = list(self._found_urls)

        for i in range(0, len(urls_list), batch_size):
            batch = urls_list[i : i + batch_size]
            records = build_relay_records(set(batch), current_time)

            if records:
                try:
                    if await self._brotr.insert_relays(records):
                        inserted += len(records)
                except Exception as e:
                    self._logger.warning("api_insert_error", batch=i, error=str(e))

        return inserted

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------

    @property
    def config(self) -> FinderConfig:
        """Get configuration."""
        return self._config