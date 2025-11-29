"""
Finder Service for BigBrotr Relay Discovery.

This service discovers new Nostr relay URLs from multiple sources:
1. Database events - Scans event content for relay URLs using nostr-tools
2. External APIs - Fetches relay lists from services like nostr.watch

Key features:
- Watermark-based tracking to avoid re-processing events
- Atomic batch processing for crash consistency
- Persistent state storage in service_state table
- Automatic network detection (clearnet/tor) via nostr-tools

Crash Consistency:
Each batch of events is processed atomically:
1. Fetch batch of events (seen_at > watermark)
2. Extract relay URLs from event content
3. In a single transaction: insert relays + update watermark
4. Commit → batch is durable

If a crash occurs at any point, the watermark only reflects fully
committed batches. On restart, unprocessed events are re-scanned.

Implements BackgroundService protocol for use with Service wrapper.

Example usage:
    from services.finder import Finder
    from core.brotr import Brotr
    from core.pool import Pool
    from core.service import Service

    pool = Pool(host="localhost", database="brotr")
    brotr = Brotr(pool=pool)
    finder = Finder(brotr=brotr)

    # Run discovery cycle
    async with pool:
        result = await finder.discover()
        print(f"Found {result.relays_found} new relays")

    # Or use with Service wrapper for logging/monitoring
    service = Service(finder, name="finder")
    async with service:
        result = await service.instance.discover()
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import aiohttp
import yaml
from nostr_tools import Relay, find_ws_urls
from pydantic import BaseModel, Field, field_validator

from core.brotr import Brotr
from core.logger import get_service_logger, validate_log_level
from services.initializer import InitializerState

# ============================================================================
# Constants
# ============================================================================

# Fixed service name for finder - used for state persistence
FINDER_SERVICE_NAME = "finder"

# ============================================================================
# Pydantic Models for Configuration Validation
# ============================================================================


class EventScanConfig(BaseModel):
    """Configuration for database event scanning."""

    enabled: bool = Field(default=True, description="Enable event scanning for relay URLs")
    batch_size: int = Field(
        default=1000, ge=100, le=10000, description="Number of events to fetch per batch"
    )
    max_events_per_cycle: int = Field(
        default=100000, ge=1000, le=1000000, description="Maximum events to process per cycle"
    )


class ApiSourceConfig(BaseModel):
    """Configuration for a single API source."""

    url: str = Field(description="API endpoint URL")
    enabled: bool = Field(default=True, description="Enable this API source")
    timeout: float = Field(default=30.0, ge=1.0, le=120.0, description="Request timeout (seconds)")


class ApiConfig(BaseModel):
    """Configuration for external API sources."""

    enabled: bool = Field(default=True, description="Enable API fetching")
    sources: list[ApiSourceConfig] = Field(
        default_factory=lambda: [
            ApiSourceConfig(url="https://api.nostr.watch/v1/online"),
            ApiSourceConfig(url="https://api.nostr.watch/v1/offline"),
        ],
        description="List of API sources to fetch relay URLs from",
    )
    request_delay: float = Field(
        default=1.0, ge=0.0, le=10.0, description="Delay between API requests (seconds)"
    )


class LoggingConfig(BaseModel):
    """Logging configuration."""

    log_progress: bool = Field(default=True, description="Log discovery progress")
    log_level: str = Field(
        default="INFO", description="Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    progress_interval: int = Field(
        default=5000, ge=100, le=50000, description="Log progress every N events"
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level_field(cls, v: str) -> str:
        """Validate log level using shared validator."""
        return validate_log_level(v)


class TimeoutsConfig(BaseModel):
    """Timeout configuration."""

    db_query: float = Field(
        default=30.0, ge=5.0, le=120.0, description="Database query timeout (seconds)"
    )


class FinderConfig(BaseModel):
    """Complete Finder service configuration."""

    event_scan: EventScanConfig = Field(
        default_factory=EventScanConfig, description="Event scanning configuration"
    )
    api: ApiConfig = Field(default_factory=ApiConfig, description="API fetching configuration")
    logging: LoggingConfig = Field(
        default_factory=LoggingConfig, description="Logging configuration"
    )
    timeouts: TimeoutsConfig = Field(
        default_factory=TimeoutsConfig, description="Timeout configuration"
    )
    insert_batch_size: int = Field(
        default=100, ge=10, le=1000, description="Batch size for relay inserts"
    )


# ============================================================================
# Result Data Classes
# ============================================================================


@dataclass
class DiscoveryResult:
    """Result of a discovery cycle."""

    success: bool
    message: str
    relays_found: int = 0
    relays_inserted: int = 0
    events_scanned: int = 0
    api_sources_checked: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "success": self.success,
            "message": self.message,
            "relays_found": self.relays_found,
            "relays_inserted": self.relays_inserted,
            "events_scanned": self.events_scanned,
            "api_sources_checked": self.api_sources_checked,
            "duration_seconds": round(self.duration_seconds, 3),
            "errors": self.errors,
        }


@dataclass
class FinderState:
    """Persistent state for the Finder service."""

    last_seen_at: int = 0  # Watermark: last processed event's seen_at
    total_events_processed: int = 0
    total_relays_found: int = 0
    last_run_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "last_seen_at": self.last_seen_at,
            "total_events_processed": self.total_events_processed,
            "total_relays_found": self.total_relays_found,
            "last_run_at": self.last_run_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FinderState":
        """Create from dictionary."""
        return cls(
            last_seen_at=data.get("last_seen_at", 0),
            total_events_processed=data.get("total_events_processed", 0),
            total_relays_found=data.get("total_relays_found", 0),
            last_run_at=data.get("last_run_at", 0),
        )


# ============================================================================
# Finder Service
# ============================================================================


class Finder:
    """
    Relay discovery service for BigBrotr.

    Discovers new Nostr relay URLs from database events and external APIs.
    Implements BackgroundService protocol for Service wrapper compatibility.

    Features:
    - Scan database events for relay URLs (parallelized with workers)
    - Fetch relay lists from external APIs (nostr.watch)
    - Watermark-based tracking to avoid re-processing
    - Persistent state in service_state table
    - Automatic network detection (clearnet/tor)

    Example:
        brotr = Brotr(pool=pool)
        finder = Finder(brotr=brotr)

        async with pool:
            result = await finder.discover()
            print(f"Found {result.relays_found} relays")
    """

    def __init__(
        self,
        brotr: Brotr,
        config: Optional[FinderConfig] = None,
    ) -> None:
        """
        Initialize the Finder service.

        Args:
            brotr: Brotr instance for database operations
            config: Service configuration (uses defaults if not provided)
        """
        self._brotr = brotr
        self._config = config or FinderConfig()
        self._is_running = False
        self._state = FinderState()
        self._logger = get_service_logger("finder", "Finder")

        # Collected URLs across all sources (cleared each discover() cycle)
        self._found_urls: set[str] = set()
        self._urls_lock = asyncio.Lock()

    # -------------------------------------------------------------------------
    # BackgroundService Protocol Implementation
    # -------------------------------------------------------------------------

    async def start(self) -> None:
        """Start the finder service."""
        self._is_running = True
        await self._load_state()
        self._logger.info("finder_starting", state=self._state.to_dict())

    async def stop(self) -> None:
        """Stop the finder service."""
        self._is_running = False
        await self._save_state()
        self._logger.info("finder_stopped")

    @property
    def is_running(self) -> bool:
        """Check if service is running."""
        return self._is_running

    # -------------------------------------------------------------------------
    # Factory Methods
    # -------------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, config_path: str, brotr: Brotr) -> "Finder":
        """
        Create Finder from YAML configuration file.

        Args:
            config_path: Path to YAML configuration file
            brotr: Brotr instance for database operations

        Returns:
            Configured Finder instance
        """
        path = Path(config_path)
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls.from_dict(data, brotr=brotr)

    @classmethod
    def from_dict(cls, data: dict[str, Any], brotr: Brotr) -> "Finder":
        """
        Create Finder from dictionary configuration.

        Args:
            data: Configuration dictionary
            brotr: Brotr instance for database operations

        Returns:
            Configured Finder instance
        """
        config = FinderConfig(**data)
        return cls(brotr=brotr, config=config)

    # -------------------------------------------------------------------------
    # Main Discovery
    # -------------------------------------------------------------------------

    async def discover(self) -> DiscoveryResult:
        """
        Run a complete discovery cycle.

        This method:
        0. Verifies initializer has completed successfully
        1. Loads persisted state (watermark)
        2. Fetches relay URLs from external APIs
        3. Scans database events for relay URLs (parallelized)
        4. Inserts discovered relays into database
        5. Saves updated state

        Returns:
            DiscoveryResult with statistics and status

        Raises:
            RuntimeError: If initializer has not completed successfully
        """
        start_time = time.time()
        errors: list[str] = []
        self._found_urls.clear()

        self._logger.info("discovery_started", config=self._config.model_dump())

        try:
            # 0. Verify initializer has completed
            if not await self._check_initializer_state():
                error_msg = "Cannot start discovery: initializer has not completed successfully"
                self._logger.error("discovery_blocked", reason=error_msg)
                return DiscoveryResult(
                    success=False,
                    message=error_msg,
                    duration_seconds=time.time() - start_time,
                    errors=[error_msg],
                )

            # Load state
            await self._load_state()

            # 1. Fetch from APIs
            api_count = 0
            if self._config.api.enabled:
                api_result = await self._fetch_from_apis()
                api_count = api_result["sources_checked"]
                if api_result["errors"]:
                    errors.extend(api_result["errors"])

            # 2. Scan database events (atomically commits relay inserts + watermark)
            events_scanned = 0
            event_relays_inserted = 0
            if self._config.event_scan.enabled:
                scan_result = await self._scan_events()
                events_scanned = scan_result["events_scanned"]
                event_relays_inserted = scan_result.get("relays_inserted", 0)
                if scan_result["errors"]:
                    errors.extend(scan_result["errors"])

            # 3. Insert API-discovered relays (not part of atomic batch)
            api_relays_inserted = 0
            if api_count > 0 and self._found_urls:
                # Only insert relays that weren't already found in event scan
                api_relays_inserted = await self._insert_discovered_relays()

            total_relays_inserted = event_relays_inserted + api_relays_inserted

            # 4. Update and save final state (for API relays and run timestamp)
            self._state.last_run_at = int(time.time())
            await self._save_state()

            duration = time.time() - start_time
            success = len(errors) == 0

            result = DiscoveryResult(
                success=success,
                message="Discovery completed successfully"
                if success
                else "Discovery completed with errors",
                relays_found=len(self._found_urls),
                relays_inserted=total_relays_inserted,
                events_scanned=events_scanned,
                api_sources_checked=api_count,
                duration_seconds=duration,
                errors=errors,
            )

            self._logger.info("discovery_completed", result=result.to_dict())
            return result

        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"Discovery failed: {e}"
            self._logger.error("discovery_failed", error=str(e))
            return DiscoveryResult(
                success=False,
                message=error_msg,
                duration_seconds=duration,
                errors=[error_msg],
            )

    # -------------------------------------------------------------------------
    # API Fetching
    # -------------------------------------------------------------------------

    async def _fetch_from_apis(self) -> dict[str, Any]:
        """
        Fetch relay URLs from configured API sources.

        Returns:
            Dictionary with sources_checked count and errors list
        """
        sources_checked = 0
        errors: list[str] = []

        for source in self._config.api.sources:
            if not source.enabled:
                continue

            try:
                urls = await self._fetch_api_source(source)
                async with self._urls_lock:
                    self._found_urls.update(urls)
                sources_checked += 1

                if self._config.logging.log_progress:
                    self._logger.debug(
                        "api_source_fetched",
                        url=source.url,
                        relays_found=len(urls),
                    )

                # Delay between requests
                if self._config.api.request_delay > 0:
                    await asyncio.sleep(self._config.api.request_delay)

            except Exception as e:
                error_msg = f"Failed to fetch {source.url}: {e}"
                errors.append(error_msg)
                self._logger.warning("api_fetch_error", url=source.url, error=str(e))

        return {"sources_checked": sources_checked, "errors": errors}

    async def _fetch_api_source(self, source: ApiSourceConfig) -> set[str]:
        """
        Fetch relay URLs from a single API source.

        Expects API to return a JSON array of relay URL strings.

        Args:
            source: API source configuration

        Returns:
            Set of discovered relay URLs
        """
        urls: set[str] = set()

        async with (
            aiohttp.ClientSession() as session,
            session.get(
                source.url,
                timeout=aiohttp.ClientTimeout(total=source.timeout),
            ) as response,
        ):
            response.raise_for_status()
            data = await response.json()

            # Expect list of strings
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str) and item.startswith("wss://"):
                        urls.add(item)

        return urls

    # -------------------------------------------------------------------------
    # Event Scanning (Parallelized)
    # -------------------------------------------------------------------------

    async def _scan_events(self) -> dict[str, Any]:
        """
        Scan database events for relay URLs using atomic batch processing.

        Each batch is processed atomically:
        1. Fetch batch of events (seen_at > watermark)
        2. Extract relay URLs from event content
        3. In a single transaction:
           - Insert discovered relays
           - Update watermark to batch's max seen_at
        4. Commit → batch is durable

        This ensures crash consistency: watermark only advances after
        relay inserts are committed. No data loss on crash.

        Returns:
            Dictionary with events_scanned count, relays_inserted, and errors list
        """
        events_scanned = 0
        relays_inserted = 0
        errors: list[str] = []

        try:
            batch_size = self._config.event_scan.batch_size
            max_events = self._config.event_scan.max_events_per_cycle
            watermark = self._state.last_seen_at

            while events_scanned < max_events:
                # 1. Fetch batch of events
                query = """
                    SELECT er.event_id, er.seen_at, e.content
                    FROM events_relays er
                    JOIN events e ON e.id = er.event_id
                    WHERE er.seen_at > $1
                    ORDER BY er.seen_at ASC
                    LIMIT $2
                """
                rows = await self._brotr.pool.fetch(
                    query, watermark, batch_size, timeout=self._config.timeouts.db_query
                )

                if not rows:
                    break

                # 2. Extract URLs from batch (in memory, no side effects)
                batch_urls: set[str] = set()
                for row in rows:
                    content = row.get("content", "")
                    if content:
                        try:
                            urls = find_ws_urls(content)
                            if urls:
                                batch_urls.update(urls)
                        except Exception as e:
                            self._logger.debug(
                                "event_parse_error",
                                event_id=row.get("event_id"),
                                error=str(e),
                            )

                # Calculate batch's max seen_at (new watermark)
                batch_max_seen_at = max(row["seen_at"] for row in rows)

                # 3. Atomic transaction: insert relays + update watermark
                batch_inserted = await self._commit_batch_atomic(
                    batch_urls, batch_max_seen_at, len(rows)
                )
                relays_inserted += batch_inserted

                # Update local state after successful commit
                watermark = batch_max_seen_at
                events_scanned += len(rows)
                self._found_urls.update(batch_urls)

                # Log progress
                if (
                    self._config.logging.log_progress
                    and events_scanned % self._config.logging.progress_interval == 0
                ):
                    self._logger.debug(
                        "event_scan_progress",
                        events_scanned=events_scanned,
                        relays_found=len(self._found_urls),
                    )

        except Exception as e:
            error_msg = f"Event scan error: {e}"
            errors.append(error_msg)
            self._logger.error("event_scan_error", error=str(e))

        return {
            "events_scanned": events_scanned,
            "relays_inserted": relays_inserted,
            "errors": errors,
        }

    # -------------------------------------------------------------------------
    # Atomic Batch Commit
    # -------------------------------------------------------------------------

    async def _commit_batch_atomic(
        self,
        urls: set[str],
        new_watermark: int,
        events_in_batch: int,
    ) -> int:
        """
        Atomically commit a batch: insert relays and update watermark.

        This is the critical method for crash consistency. Both operations
        happen in a single transaction:
        1. Insert relay URLs into database
        2. Update watermark in service_state

        If either fails, the transaction rolls back and nothing is committed.
        The caller can safely retry the batch.

        Args:
            urls: Set of relay URLs discovered in this batch
            new_watermark: The max seen_at from the batch (new watermark)
            events_in_batch: Number of events processed in this batch

        Returns:
            Number of relays inserted
        """
        inserted = 0
        current_time = int(time.time())

        # Build relay records from URLs
        relay_records = []
        for url in urls:
            try:
                relay = Relay(url)
                relay_records.append(
                    {
                        "url": relay.url,
                        "network": relay.network,
                        "inserted_at": current_time,
                    }
                )
            except Exception as e:
                self._logger.debug("invalid_relay_url", url=url, error=str(e))

        # Atomic transaction: insert relays + update state
        async with self._brotr.pool.transaction() as conn:
            # 1. Insert relays (if any)
            if relay_records:
                for record in relay_records:
                    try:
                        await conn.execute(
                            "SELECT insert_relay($1, $2, $3)",
                            record["url"],
                            record["network"],
                            record["inserted_at"],
                        )
                        inserted += 1
                    except Exception as e:
                        # Log but continue - duplicates cause errors
                        self._logger.debug(
                            "relay_insert_skip",
                            url=record["url"],
                            error=str(e),
                        )

            # 2. Prepare state for database (compute new values)
            new_total_events = self._state.total_events_processed + events_in_batch
            new_total_relays = self._state.total_relays_found + inserted

            state_to_save = {
                "last_seen_at": new_watermark,
                "total_events_processed": new_total_events,
                "total_relays_found": new_total_relays,
                "last_run_at": self._state.last_run_at,
            }
            state_json = json.dumps(state_to_save)

            await conn.execute(
                """
                INSERT INTO service_state (service_name, state, updated_at)
                VALUES ($1, $2::jsonb, $3)
                ON CONFLICT (service_name)
                DO UPDATE SET state = $2::jsonb, updated_at = $3
                """,
                FINDER_SERVICE_NAME,
                state_json,
                current_time,
            )

        # Update in-memory state AFTER transaction commits successfully
        self._state.last_seen_at = new_watermark
        self._state.total_events_processed += events_in_batch
        self._state.total_relays_found += inserted

        self._logger.debug(
            "batch_committed",
            relays_inserted=inserted,
            new_watermark=new_watermark,
            events_processed=events_in_batch,
        )

        return inserted

    # -------------------------------------------------------------------------
    # Relay Insertion (Legacy - for API-discovered relays)
    # -------------------------------------------------------------------------

    async def _insert_discovered_relays(self) -> int:
        """
        Insert discovered relay URLs into database.

        Note: This method is used for API-discovered relays only.
        Event-scanned relays are inserted atomically via _commit_batch_atomic.

        Uses nostr-tools Relay class for automatic network detection.
        Duplicates are handled by database (ON CONFLICT DO NOTHING).

        Returns:
            Number of relays inserted
        """
        if not self._found_urls:
            return 0

        inserted = 0
        current_time = int(time.time())
        batch_size = self._config.insert_batch_size
        urls_list = list(self._found_urls)

        for i in range(0, len(urls_list), batch_size):
            batch = urls_list[i : i + batch_size]

            # Build relay records with auto-detected network
            relay_records = []
            for url in batch:
                try:
                    relay = Relay(url)
                    relay_records.append(
                        {
                            "url": relay.url,
                            "network": relay.network,
                            "inserted_at": current_time,
                        }
                    )
                except Exception as e:
                    self._logger.debug("invalid_relay_url", url=url, error=str(e))

            if relay_records:
                try:
                    success = await self._brotr.insert_relays(relay_records)
                    if success:
                        inserted += len(relay_records)
                except Exception as e:
                    self._logger.warning(
                        "relay_insert_error",
                        batch_start=i,
                        batch_size=len(relay_records),
                        error=str(e),
                    )

        return inserted

    # -------------------------------------------------------------------------
    # State Management
    # -------------------------------------------------------------------------

    async def _check_initializer_state(self) -> bool:
        """
        Check if initializer has completed successfully.

        Uses InitializerState.load_from_db to load the state, ensuring
        the logic is centralized in the initializer module.

        Returns:
            True if initializer completed successfully, False otherwise
        """
        state = await InitializerState.load_from_db(
            self._brotr.pool,
            timeout=self._config.timeouts.db_query,
        )

        if not state.initialized:
            self._logger.warning(
                "initializer_not_completed",
                initialized_at=state.initialized_at,
                errors=state.errors,
            )
            return False

        return True

    async def _load_state(self) -> None:
        """Load persisted state from service_state table."""
        try:
            query = "SELECT state FROM service_state WHERE service_name = $1"
            row = await self._brotr.pool.fetchrow(
                query, FINDER_SERVICE_NAME, timeout=self._config.timeouts.db_query
            )

            if row and row["state"]:
                state_data = row["state"]
                if isinstance(state_data, str):
                    state_data = json.loads(state_data)
                self._state = FinderState.from_dict(state_data)
                self._logger.debug("state_loaded", state=self._state.to_dict())
            else:
                self._state = FinderState()
                self._logger.debug("state_initialized")

        except Exception as e:
            self._logger.warning("state_load_error", error=str(e))
            self._state = FinderState()

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
                FINDER_SERVICE_NAME,
                state_json,
                current_time,
                timeout=self._config.timeouts.db_query,
            )
            self._logger.debug("state_saved", state=self._state.to_dict())

        except Exception as e:
            self._logger.warning("state_save_error", error=str(e))

    # -------------------------------------------------------------------------
    # Health Check
    # -------------------------------------------------------------------------

    async def health_check(self) -> bool:
        """
        Check if finder service is healthy.

        Returns:
            True if service can connect to database
        """
        try:
            query = "SELECT 1"
            result = await self._brotr.pool.fetchval(query, timeout=self._config.timeouts.db_query)
            return result == 1
        except Exception:
            return False

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------

    @property
    def config(self) -> FinderConfig:
        """Get current configuration (read-only)."""
        return self._config

    @property
    def state(self) -> FinderState:
        """Get current state (read-only)."""
        return self._state

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"Finder("
            f"is_running={self._is_running}, "
            f"last_seen_at={self._state.last_seen_at}, "
            f"total_found={self._state.total_relays_found})"
        )
