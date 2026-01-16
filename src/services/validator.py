"""
Validator Service for BigBrotr.

Validates candidate relay URLs discovered by the Finder service:
- Streams candidates from services table (with cursor-based pagination)
- Tests WebSocket connectivity with network-aware timeouts
- Adds valid relays to the relays table
- Tracks retry count for failed candidates

Architecture:
    Stream (DB pages) -> Bounded Pending (backpressure) -> Per-network Semaphores -> Batch Collector

Features:
    - Pure asyncio (Python 3.10+)
    - Bounded pending tasks (memory efficient, O(max_pending) not O(N))
    - Per-network semaphores (50 clearnet vs 10 Tor vs 5 I2P)
    - Network-aware timeouts (10s clearnet vs 30s Tor vs 45s I2P)
    - Continuous checkpoints (crash-resilient)
    - Optional max candidates per run
    - Graceful shutdown support via BaseService

Usage:
    from core import Brotr
    from services import Validator

    brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
    validator = Validator.from_yaml("yaml/services/validator.yaml", brotr=brotr)

    async with brotr.pool:
        async with validator:
            await validator.run_forever()
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, Field

from core.base_service import BaseService, BaseServiceConfig
from models import Relay
from models.relay import NetworkType
from utils.network import NetworkConfig
from utils.transport import is_nostr_relay


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.brotr import Brotr


# =============================================================================
# Data Types
# =============================================================================


@dataclass(slots=True)
class RunStats:
    """Statistics for a single validation run."""

    validated: int = 0
    failed: int = 0
    total_candidates: int = 0
    start_time: float = field(default_factory=time.time)
    by_network: dict[NetworkType, dict[str, int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.by_network:
            self.by_network = {
                net: {"validated": 0, "failed": 0} for net in NetworkType
            }

    @property
    def elapsed(self) -> float:
        return time.time() - self.start_time

    def record_result(self, network: NetworkType, *, valid: bool) -> None:
        """Record a validation result."""
        if valid:
            self.validated += 1
            self.by_network[network]["validated"] += 1
        else:
            self.failed += 1
            self.by_network[network]["failed"] += 1

    def get_active_networks(self) -> dict[str, dict[str, int]]:
        """Get stats only for networks with activity."""
        return {
            net.value: stats
            for net, stats in self.by_network.items()
            if stats["validated"] > 0 or stats["failed"] > 0
        }


# =============================================================================
# Configuration
# =============================================================================


class BatchConfig(BaseModel):
    """Batch sizes and limits for validation."""

    fetch_size: int = Field(
        default=500,
        ge=100,
        le=5000,
        description="DB page size for streaming candidates",
    )
    max_pending: int = Field(
        default=500,
        ge=50,
        le=5000,
        description="Max pending tasks (memory limit, enables backpressure)",
    )
    write_size: int = Field(
        default=100,
        ge=10,
        le=500,
        description="Flush results to DB every N validations (checkpoint interval)",
    )
    max_candidates: int | None = Field(
        default=None,
        ge=1,
        description="Max candidates to validate per run (None = unlimited)",
    )


class CleanupConfig(BaseModel):
    """Cleanup configuration for failed candidates."""

    enabled: bool = Field(
        default=False,
        description="Enable automatic cleanup of candidates that exceeded max attempts",
    )
    max_attempts: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Delete candidates after this many failed validation attempts",
    )


class ValidatorConfig(BaseServiceConfig):
    """Validator configuration.

    Concurrency is controlled per-network via networks.*.max_tasks.
    Memory is bounded by batch.max_pending (backpressure kicks in when reached).

    Example YAML:
        interval: 300.0

        networks:
          clearnet:
            enabled: true
            max_tasks: 50      # Max concurrent clearnet connections
            timeout: 10.0
          tor:
            enabled: true
            proxy_url: "socks5://tor:9050"
            max_tasks: 10      # Max concurrent Tor connections
            timeout: 30.0
          i2p:
            enabled: true
            proxy_url: "socks5://i2p:4447"
            max_tasks: 5       # Max concurrent I2P connections
            timeout: 45.0
          loki:
            enabled: false
            proxy_url: "socks5://lokinet:1080"
            max_tasks: 5
            timeout: 30.0

        batch:
          fetch_size: 500      # DB page size
          max_pending: 500     # Max tasks in memory (backpressure)
          write_size: 100      # Checkpoint every N results
          max_candidates: null # null = unlimited, or set a number

        cleanup:
          enabled: false
          max_attempts: 10
    """

    networks: NetworkConfig = Field(default_factory=NetworkConfig)
    batch: BatchConfig = Field(default_factory=BatchConfig)
    cleanup: CleanupConfig = Field(default_factory=CleanupConfig)


# =============================================================================
# Service
# =============================================================================


class Validator(BaseService[ValidatorConfig]):
    """
    Relay validation service with bounded pending architecture.

    Validates candidate relay URLs discovered by the Seeder and Finder services.
    Tests WebSocket connectivity and adds valid relays to the database.

    Architecture:
        Stream (DB pages) -> Bounded Pending -> Per-network Semaphores -> Batch Collector

    The bounded pending pool ensures:
        - Memory is O(max_pending), not O(total_candidates)
        - Backpressure: producer slows down when max_pending reached
        - Parallelism is maximized (always max_tasks active per network)

    Workflow:
        1. Remove promoted candidates (data integrity)
        2. Remove exhausted candidates (cleanup, if enabled)
        3. Stream candidates from DB with async generator
        4. Create tasks with backpressure (wait when max_pending reached)
        5. Each task uses per-network semaphore for concurrency control
        6. Collect results with lock, auto-flush every write_size

    Features:
        - Pure asyncio (Python 3.10+)
        - Bounded memory via max_pending
        - Per-network semaphores (50 clearnet vs 10 Tor vs 5 I2P)
        - Network-aware timeouts (10s clearnet vs 30s Tor vs 45s I2P)
        - Continuous checkpoints (crash-resilient)
        - Optional max_candidates limit per run
        - Graceful shutdown (respects BaseService.is_running)
    """

    SERVICE_NAME: ClassVar[str] = "validator"
    CONFIG_CLASS: ClassVar[type[ValidatorConfig]] = ValidatorConfig

    def __init__(
        self,
        brotr: Brotr,
        config: ValidatorConfig | None = None,
    ) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: ValidatorConfig

        # Per-network semaphores (created fresh each run)
        self._semaphores: dict[NetworkType, asyncio.Semaphore] = {}

        # Cycle stats (reset each run)
        self._stats: RunStats = RunStats()

        # Batch collection
        self._valid_batch: list[tuple[Relay, int]] = []  # (relay, failed_attempts)
        self._failed_batch: list[tuple[Relay, int]] = []  # (relay, failed_attempts)
        self._batch_lock: asyncio.Lock = asyncio.Lock()

    # -------------------------------------------------------------------------
    # Main Entry Point
    # -------------------------------------------------------------------------

    async def run(self) -> None:
        """Run a single validation cycle."""
        self._reset_cycle()

        await self._cleanup_promoted_candidates()
        await self._cleanup_exhausted_candidates()

        self._init_semaphores()
        await self._process_all_candidates()
        await self._persist_results()

        self._log_cycle_completed()

    # -------------------------------------------------------------------------
    # Cycle Setup
    # -------------------------------------------------------------------------

    def _reset_cycle(self) -> None:
        """Reset state for a new cycle."""
        self._stats = RunStats()
        self._valid_batch = []
        self._failed_batch = []

    def _init_semaphores(self) -> None:
        """Create per-network semaphores from config."""
        self._semaphores = {
            NetworkType.CLEARNET: asyncio.Semaphore(
                self._config.networks.clearnet.max_tasks
            ),
            NetworkType.TOR: asyncio.Semaphore(self._config.networks.tor.max_tasks),
            NetworkType.I2P: asyncio.Semaphore(self._config.networks.i2p.max_tasks),
            NetworkType.LOKI: asyncio.Semaphore(self._config.networks.loki.max_tasks),
        }

    # -------------------------------------------------------------------------
    # Cleanup (Data Integrity + Optional Pruning)
    # -------------------------------------------------------------------------

    async def _cleanup_promoted_candidates(self) -> None:
        """
        Remove candidates already promoted to relays table.

        Data integrity operation: ensures consistency when a relay was added
        by another process (e.g., seeder with to_validate=False).
        """
        result = await self._brotr.pool.execute(
            """
            DELETE FROM service_data
            WHERE service_name = 'validator'
              AND data_type = 'candidate'
              AND data_key IN (SELECT url FROM relays)
            """,
            timeout=self._brotr.config.timeouts.query,
        )
        count = int(result.split()[-1]) if result else 0
        if count > 0:
            self._logger.info("cleanup.promoted_removed", count=count)

    async def _cleanup_exhausted_candidates(self) -> None:
        """
        Remove candidates that exceeded max validation attempts.

        Optional pruning operation, controlled by cleanup.enabled config.
        """
        if not self._config.cleanup.enabled:
            return

        result = await self._brotr.pool.execute(
            """
            DELETE FROM service_data
            WHERE service_name = 'validator'
              AND data_type = 'candidate'
              AND COALESCE((data->>'failed_attempts')::int, 0) >= $1
            """,
            self._config.cleanup.max_attempts,
            timeout=self._brotr.config.timeouts.query,
        )
        count = int(result.split()[-1]) if result else 0
        if count > 0:
            self._logger.info("cleanup.exhausted_removed", count=count)

    # -------------------------------------------------------------------------
    # Candidate Processing (Producer Loop)
    # -------------------------------------------------------------------------

    async def _process_all_candidates(self) -> None:
        """Process candidates with bounded pending set (backpressure).

        Candidates are excluded from fetch when:
        - updated_at >= cycle_start: already processed this cycle (failed)
        - url IN relays: already validated this cycle (promoted)

        Additionally, we track processed URLs in memory to handle the race
        condition where a page is fetched before the flush updates updated_at.
        """
        pending: set[asyncio.Task[None]] = set()
        processed_urls: set[str] = set()
        cycle_start_ts = int(self._stats.start_time)

        async for relay, failed_attempts in self._stream_candidates(cycle_start_ts):
            # Check stop conditions
            if not self.is_running:
                self._logger.info(
                    "cycle.interrupted", reason="shutdown", pending=len(pending)
                )
                break

            if self._reached_max_candidates():
                self._logger.info(
                    "cycle.interrupted",
                    reason="max_reached",
                    limit=self._config.batch.max_candidates,
                )
                break

            # Skip if already processed (race condition: fetched before flush)
            if relay.url in processed_urls:
                continue
            processed_urls.add(relay.url)

            # Backpressure: wait if pending set is full
            pending = await self._wait_for_capacity(pending)

            # Create validation task
            self._stats.total_candidates += 1
            task = asyncio.create_task(
                self._process_candidate(relay, failed_attempts)
            )
            pending.add(task)

        # Drain remaining tasks
        await self._drain_pending(pending)

    def _reached_max_candidates(self) -> bool:
        """Check if max candidates limit is reached."""
        max_candidates = self._config.batch.max_candidates
        return (
            max_candidates is not None
            and self._stats.total_candidates >= max_candidates
        )

    async def _wait_for_capacity(
        self, pending: set[asyncio.Task[None]]
    ) -> set[asyncio.Task[None]]:
        """Wait until pending set has capacity (backpressure)."""
        max_pending = self._config.batch.max_pending
        while len(pending) >= max_pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            self._log_task_errors(done)
        return pending

    async def _drain_pending(self, pending: set[asyncio.Task[None]]) -> None:
        """Wait for all pending tasks to complete or cancel on shutdown."""
        if not pending:
            return

        if not self.is_running:
            # Graceful shutdown: cancel all pending
            self._logger.debug("drain.cancelling", count=len(pending))
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        else:
            # Normal drain: wait for completion
            while pending:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                self._log_task_errors(done)

    def _log_task_errors(self, done: set[asyncio.Task[None]]) -> None:
        """Log exceptions from completed tasks."""
        for task in done:
            try:
                exc = task.exception()
                if exc is not None:
                    self._logger.warning(
                        "validate.task_error",
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )
            except asyncio.CancelledError:
                pass

    # -------------------------------------------------------------------------
    # Candidate Streaming (DB Pagination)
    # -------------------------------------------------------------------------

    async def _stream_candidates(
        self, before_ts: int
    ) -> AsyncIterator[tuple[Relay, int]]:
        """
        Stream candidates from DB with cursor-based pagination.

        Yields (Relay, failed_attempts) tuples ordered by priority score.

        Priority scoring (lower = higher priority):
        - failed_attempts * 10 (fewer failures = higher priority)
        - age_in_days (fresher = higher priority)
        - network_bonus (-5 for clearnet, faster to validate)

        Args:
            before_ts: Only fetch candidates with updated_at < this timestamp.
                       Prevents re-fetching candidates updated during this run.
        """
        enabled_networks = self._config.networks.get_enabled_networks()
        if not enabled_networks:
            self._logger.info("stream.no_networks_enabled")
            return

        while self.is_running:
            rows = await self._fetch_candidate_page(enabled_networks, before_ts)

            if not rows:
                break

            self._logger.debug("stream.page_fetched", count=len(rows))

            for row in rows:
                try:
                    relay = Relay(row["data_key"])
                    failed_attempts = row["data"].get("failed_attempts", 0)
                    yield relay, failed_attempts
                except Exception as e:
                    self._logger.warning(
                        "stream.parse_error",
                        url=row["data_key"],
                        error=str(e),
                    )

    async def _fetch_candidate_page(
        self,
        enabled_networks: list[str],
        before_ts: int,
    ) -> list:
        """Fetch a page of candidates to validate.

        Simple query with two exclusion criteria:
        - updated_at < before_ts: excludes candidates already processed this cycle
          (their updated_at gets bumped when failed_attempts is incremented)
        - NOT IN relays: excludes candidates already promoted (validated but not yet
          deleted from service_data due to batched flush)

        No cursor needed - the same query naturally returns different results as:
        - Failed candidates get updated_at >= before_ts (excluded)
        - Validated candidates appear in relays table (excluded)

        Ordering: failed_attempts ASC, then updated_at ASC
        - Candidates with fewer failures are tried first (more likely to succeed)
        - At equal failures, oldest (not tried for longest) have priority
        """
        return await self._brotr.pool.fetch(
            """
            SELECT data_key, data
            FROM service_data
            WHERE service_name = 'validator'
              AND data_type = 'candidate'
              AND data->>'network' = ANY($1)
              AND updated_at < $2
              AND data_key NOT IN (SELECT url FROM relays)
            ORDER BY COALESCE((data->>'failed_attempts')::int, 0) ASC,
                     updated_at ASC
            LIMIT $3
            """,
            enabled_networks,
            before_ts,
            self._config.batch.fetch_size,
            timeout=self._brotr.config.timeouts.query,
        )

    # -------------------------------------------------------------------------
    # Validation - I/O
    # -------------------------------------------------------------------------

    async def _process_candidate(self, relay: Relay, failed_attempts: int) -> None:
        """Validate a single relay and collect result."""
        is_valid = await self._validate_relay(relay)
        await self._collect_result(relay, failed_attempts, is_valid)

    async def _validate_relay(self, relay: Relay) -> bool:
        """Test if relay speaks Nostr protocol (I/O operation)."""
        semaphore = self._semaphores[relay.network]

        async with semaphore:
            net_config = self._config.networks.get(relay.network)
            proxy_url = self._config.networks.get_proxy_url(relay.network)

            try:
                return await is_nostr_relay(relay, proxy_url, net_config.timeout)
            except Exception:
                return False

    # -------------------------------------------------------------------------
    # Result Collection (Batching)
    # -------------------------------------------------------------------------

    async def _collect_result(
        self, relay: Relay, failed_attempts: int, is_valid: bool
    ) -> None:
        """Collect validation result and auto-flush when batch is full."""
        async with self._batch_lock:
            if is_valid:
                self._valid_batch.append((relay, failed_attempts))
            else:
                self._failed_batch.append((relay, failed_attempts))

            self._stats.record_result(relay.network, valid=is_valid)

            # Auto-flush checkpoint
            total = len(self._valid_batch) + len(self._failed_batch)
            if total >= self._config.batch.write_size:
                await self._persist_results_unlocked()

    # -------------------------------------------------------------------------
    # Persistence (DB Writes)
    # -------------------------------------------------------------------------

    async def _persist_results(self) -> None:
        """Persist all batched results (with lock)."""
        async with self._batch_lock:
            await self._persist_results_unlocked()

    async def _persist_results_unlocked(self) -> None:
        """
        Write results to DB. Must be called with _batch_lock held.

        Valid relays: insert into relays table, then delete from candidates.
        Failed relays: increment failed_attempts counter.
        """
        await self._persist_valid_batch()
        await self._persist_failed_batch()

    async def _persist_valid_batch(self) -> None:
        """Insert valid relays and remove from candidates."""
        if not self._valid_batch:
            return

        try:
            # Deduplicate by URL (same URL could appear if validated concurrently)
            seen: set[str] = set()
            relays: list[Relay] = []
            for relay, _ in self._valid_batch:
                if relay.url not in seen:
                    seen.add(relay.url)
                    relays.append(relay)

            await self._brotr.insert_relays(relays)

            # Delete from candidates only after successful insert
            delete_records = [
                ("validator", "candidate", relay.url) for relay in relays
            ]
            await self._brotr.delete_service_data(delete_records)

            self._logger.debug("flush.valid_persisted", count=len(relays))
        except Exception as e:
            self._logger.error(
                "flush.valid_error",
                error=str(e),
                error_type=type(e).__name__,
                count=len(self._valid_batch),
            )

        self._valid_batch = []

    async def _persist_failed_batch(self) -> None:
        """Update failed_attempts counter for failed candidates."""
        if not self._failed_batch:
            return

        try:
            # Deduplicate by URL, keeping highest failed_attempts
            # (same URL can appear multiple times if validated concurrently)
            deduplicated: dict[str, int] = {}
            for relay, attempts in self._failed_batch:
                current = deduplicated.get(relay.url, -1)
                deduplicated[relay.url] = max(current, attempts + 1)

            upsert_records = [
                ("validator", "candidate", url, {"failed_attempts": attempts})
                for url, attempts in deduplicated.items()
            ]
            await self._brotr.upsert_service_data(upsert_records)

            self._logger.debug("flush.failed_updated", count=len(upsert_records))
        except Exception as e:
            self._logger.error(
                "flush.failed_error",
                error=str(e),
                error_type=type(e).__name__,
                count=len(self._failed_batch),
            )

        self._failed_batch = []

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def _log_cycle_completed(self) -> None:
        """Log cycle completion summary."""
        self._logger.info(
            "cycle.completed",
            candidates=self._stats.total_candidates,
            validated=self._stats.validated,
            failed=self._stats.failed,
            duration=round(self._stats.elapsed, 2),
            by_network=self._stats.get_active_networks(),
        )
