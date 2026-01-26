"""Validates relay candidates by checking if they speak Nostr protocol.

Valid candidates are promoted to the relays table. Invalid ones have their
failure counter incremented and will be retried in future cycles.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

from core.base_service import BaseService, BaseServiceConfig
from models import Relay
from models.relay import NetworkType
from utils.network import NetworkConfig
from utils.progress import BatchProgress
from utils.transport import is_nostr_relay


if TYPE_CHECKING:
    from core.brotr import Brotr


# =============================================================================
# Data Types
# =============================================================================


@dataclass(slots=True)
class Candidate:
    """Relay candidate pending validation.

    Wraps a Relay object with its associated service_data metadata, providing
    convenient access to validation state like failure counts.

    Attributes:
        relay: The Relay object containing URL and network information.
        data: Dictionary of metadata from service_data table, including
            'network' and 'failed_attempts' fields.
    """

    relay: Relay
    data: dict[str, Any]

    @property
    def failed_attempts(self) -> int:
        """Return the number of failed validation attempts for this candidate."""
        return self.data.get("failed_attempts", 0)


# =============================================================================
# Configuration
# =============================================================================


class ProcessingConfig(BaseModel):
    """Candidate processing settings.

    Attributes:
        chunk_size: Number of candidates to fetch and validate per iteration.
            Larger chunks reduce database round-trips but increase memory usage.
        max_candidates: Optional limit on total candidates processed per cycle.
            When None, processes all available candidates.
    """

    chunk_size: int = Field(default=100, ge=10, le=1000)
    max_candidates: int | None = Field(default=None, ge=1)


class CleanupConfig(BaseModel):
    """Exhausted candidate cleanup settings.

    Controls removal of candidates that have failed validation too many times,
    preventing permanently broken relays from consuming resources indefinitely.

    Attributes:
        enabled: Whether to enable exhausted candidate cleanup.
        max_failures: Failure threshold after which candidates are removed.
    """

    enabled: bool = Field(default=False)
    max_failures: int = Field(default=100, ge=1, le=1000)


class ValidatorConfig(BaseServiceConfig):
    """Validator service configuration.

    Attributes:
        networks: Network-specific settings (timeouts, proxies, concurrency).
        processing: Chunk size and candidate limits for validation cycles.
        cleanup: Settings for removing exhausted candidates.
    """

    networks: NetworkConfig = Field(default_factory=NetworkConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    cleanup: CleanupConfig = Field(default_factory=CleanupConfig)


# =============================================================================
# Service
# =============================================================================


class Validator(BaseService[ValidatorConfig]):
    """Validates relay candidates by checking if they speak the Nostr protocol.

    This service processes relay URLs discovered by the Finder service and determines
    whether they are valid Nostr relays. Valid relays are promoted to the main relays
    table, while invalid ones have their failure counter incremented for retry in
    future cycles.

    Validation Criteria:
        A relay is considered valid if it:
        1. Accepts a WebSocket connection at its URL
        2. Responds to a Nostr REQ message within the configured timeout
        3. Returns a valid Nostr response (EOSE, EVENT, or NOTICE)

    Workflow:
        1. Reset cycle state and initialize per-network concurrency semaphores
        2. Clean up stale candidates (URLs already in relays table)
        3. Optionally clean up exhausted candidates (exceeded max failure threshold)
        4. Count available candidates for enabled networks
        5. Process candidates in configurable chunks:
           a. Fetch chunk ordered by failed_attempts ASC, updated_at ASC
           b. Validate each candidate concurrently (respecting network semaphores)
           c. Persist results: promote valid relays, increment failure count for invalid
        6. Emit metrics and log completion statistics

    Network Support:
        - Clearnet (wss://): Direct WebSocket connections
        - Tor (wss://*.onion): Connections via SOCKS5 proxy (configurable)
        - I2P (wss://*.i2p): Connections via HTTP proxy (configurable)

    Attributes:
        SERVICE_NAME: Service identifier for configuration and logging.
        CONFIG_CLASS: Pydantic configuration model class.
    """

    SERVICE_NAME: ClassVar[str] = "validator"
    CONFIG_CLASS: ClassVar[type[ValidatorConfig]] = ValidatorConfig

    def __init__(self, brotr: Brotr, config: ValidatorConfig | None = None) -> None:
        """Initialize the Validator service.

        Args:
            brotr: Database interface for relay and service_data operations.
            config: Optional configuration. If None, loads from YAML file.
        """
        super().__init__(brotr=brotr, config=config)
        self._config: ValidatorConfig
        self._semaphores: dict[NetworkType, asyncio.Semaphore] = {}
        self._progress = BatchProgress()

    # -------------------------------------------------------------------------
    # Main Cycle
    # -------------------------------------------------------------------------

    async def run(self) -> None:
        """Execute one complete validation cycle.

        Orchestrates the full validation workflow: cleanup, counting, processing,
        and metrics emission. Each cycle processes candidates in chunks to manage
        memory and provide progress feedback.

        The cycle respects the `is_running` flag and will exit early if the service
        is stopped. It also respects `max_candidates` configuration to limit the
        number of candidates processed per cycle.

        Raises:
            Exception: Database errors are logged but not raised to allow the
                service to continue with subsequent cycles.
        """
        self._progress.reset()
        self._init_semaphores()

        networks = self._config.networks.get_enabled_networks()
        self._logger.info(
            "cycle_started",
            chunk_size=self._config.processing.chunk_size,
            max_candidates=self._config.processing.max_candidates,
            networks=networks,
        )

        # Cleanup and count
        await self._cleanup_stale()
        await self._cleanup_exhausted()
        self._progress.total = await self._count_candidates(networks)

        self._logger.info("candidates_available", total=self._progress.total)
        self._emit_metrics()

        # Process all candidates
        await self._process_all(networks)

        self._emit_metrics()
        self._logger.info(
            "cycle_completed",
            validated=self._progress.success,
            invalidated=self._progress.failure,
            chunks=self._progress.chunks,
            duration_s=self._progress.elapsed,
        )

    def _init_semaphores(self) -> None:
        """Initialize per-network concurrency semaphores.

        Creates an asyncio.Semaphore for each network type (clearnet, tor, i2p)
        to limit concurrent validation connections. This prevents overwhelming
        network resources, especially important for Tor where too many simultaneous
        connections can degrade performance.

        The max_tasks value for each network is read from the configuration's
        networks section. Semaphores are recreated each cycle to pick up any
        configuration changes.
        """
        self._semaphores = {
            network: asyncio.Semaphore(self._config.networks.get(network).max_tasks)
            for network in NetworkType
        }

    # -------------------------------------------------------------------------
    # Metrics
    # -------------------------------------------------------------------------

    def _emit_metrics(self) -> None:
        """Emit Prometheus metrics reflecting current cycle state.

        Updates gauge metrics for monitoring dashboards:
            - total: Total candidates available at cycle start
            - processed: Candidates processed (cumulative in cycle)
            - success: Relays that passed validation (cumulative in cycle)
            - failure: Relays that failed validation (cumulative in cycle)

        Called after cleanup/counting, after each chunk, and at cycle completion
        to provide real-time visibility into validation progress.
        """
        self.set_gauge("total", self._progress.total)
        self.set_gauge("processed", self._progress.processed)
        self.set_gauge("success", self._progress.success)
        self.set_gauge("failure", self._progress.failure)

    # -------------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------------

    async def _cleanup_stale(self) -> None:
        """Remove candidates whose URLs already exist in the relays table.

        Stale candidates occur when:
            - A relay was validated by another process/cycle
            - A relay was manually added to the relays table
            - The Finder re-discovered an already-validated relay

        This cleanup prevents wasted validation attempts and ensures the
        candidate pool only contains URLs not yet in the relays table.

        Increments the 'total_stale_removed' counter metric when candidates
        are removed.
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
        count = self._parse_delete_result(result)
        if count > 0:
            self.inc_counter("total_stale_removed", count)
            self._logger.info("stale_removed", count=count)

    async def _cleanup_exhausted(self) -> None:
        """Remove candidates that have exceeded the maximum failure threshold.

        When enabled via configuration, this removes candidates that have failed
        validation too many times (default: 100 attempts). This prevents
        permanently broken or non-existent relays from consuming validation
        resources indefinitely.

        The threshold is configurable via cleanup.max_failures. Setting
        cleanup.enabled to False disables this cleanup entirely, allowing
        unlimited retry attempts.

        Increments the 'total_exhausted_removed' counter metric when candidates
        are removed.
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
            self._config.cleanup.max_failures,
            timeout=self._brotr.config.timeouts.query,
        )
        count = self._parse_delete_result(result)
        if count > 0:
            self.inc_counter("total_exhausted_removed", count)
            self._logger.info(
                "exhausted_removed",
                count=count,
                threshold=self._config.cleanup.max_failures,
            )

    @staticmethod
    def _parse_delete_result(result: str | None) -> int:
        """Parse the row count from a PostgreSQL DELETE command result.

        PostgreSQL returns DELETE results in the format 'DELETE N' where N is
        the number of rows affected. This method extracts that count.

        Args:
            result: The raw result string from asyncpg execute(), typically
                in the format 'DELETE N'. May be None if the query failed.

        Returns:
            The number of rows deleted, or 0 if the result is None, empty,
            or cannot be parsed.

        Examples:
            >>> Validator._parse_delete_result("DELETE 5")
            5
            >>> Validator._parse_delete_result("DELETE 0")
            0
            >>> Validator._parse_delete_result(None)
            0
        """
        if not result:
            return 0
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0

    async def _count_candidates(self, networks: list[str]) -> int:
        """Count the total number of pending candidates for the specified networks.

        Queries the service_data table to count candidates whose network type
        matches one of the enabled networks. This count is used for progress
        reporting and metrics.

        Args:
            networks: List of enabled network type strings (e.g., ['clearnet', 'tor']).

        Returns:
            Total count of candidates matching the specified networks.
            Returns 0 if no candidates exist or if the query fails.
        """
        row = await self._brotr.pool.fetchrow(
            """
            SELECT COUNT(*)::int AS count
            FROM service_data
            WHERE service_name = 'validator'
              AND data_type = 'candidate'
              AND data->>'network' = ANY($1)
            """,
            networks,
            timeout=self._brotr.config.timeouts.query,
        )
        return row["count"] if row else 0

    # -------------------------------------------------------------------------
    # Processing
    # -------------------------------------------------------------------------

    async def _process_all(self, networks: list[str]) -> None:
        """Process all pending candidates in configurable chunks.

        Iteratively fetches and validates candidates until one of these conditions:
            - No more candidates remain
            - max_candidates limit is reached (if configured)
            - Service is stopped (is_running becomes False)

        Each iteration fetches a chunk of candidates, validates them concurrently,
        persists the results, and emits progress metrics. Chunk size is configurable
        to balance memory usage against database round-trips.

        Args:
            networks: List of enabled network type strings to process.
                If empty, logs a warning and returns immediately.
        """
        if not networks:
            self._logger.warning("no_networks_enabled")
            return

        max_candidates = self._config.processing.max_candidates
        chunk_size = self._config.processing.chunk_size

        while self.is_running:
            # Calculate limit for this chunk
            if max_candidates is not None:
                budget = max_candidates - self._progress.processed
                if budget <= 0:
                    self._logger.debug("max_candidates_reached", limit=max_candidates)
                    break
                limit = min(chunk_size, budget)
            else:
                limit = chunk_size

            # Fetch and process chunk
            candidates = await self._fetch_chunk(networks, limit)
            if not candidates:
                self._logger.debug("no_more_candidates")
                break

            self._progress.chunks += 1
            valid, invalid = await self._validate_chunk(candidates)
            await self._persist_results(valid, invalid)

            self._emit_metrics()
            self._logger.info(
                "chunk_completed",
                chunk=self._progress.chunks,
                valid=len(valid),
                invalid=len(invalid),
                remaining=self._progress.remaining,
            )

    async def _fetch_chunk(self, networks: list[str], limit: int) -> list[Candidate]:
        """Fetch the next chunk of candidates for validation.

        Retrieves candidates from the service_data table, ordered to prioritize:
            1. Candidates with fewer failed attempts (more likely to succeed)
            2. Older candidates (FIFO within same failure count)

        Only fetches candidates updated before the cycle start time to avoid
        re-processing candidates that were just updated in this cycle.

        Args:
            networks: List of enabled network type strings to fetch.
            limit: Maximum number of candidates to return in this chunk.

        Returns:
            List of Candidate objects ready for validation. May be empty if no
            candidates remain or all have been processed this cycle.

        Note:
            Stale candidates (URLs already in relays table) are cleaned up at the
            start of each cycle by _cleanup_stale(), so no subquery filter is
            needed here.
        """
        rows = await self._brotr.pool.fetch(
            """
            SELECT data_key, data
            FROM service_data
            WHERE service_name = 'validator'
              AND data_type = 'candidate'
              AND data->>'network' = ANY($1)
              AND updated_at < $2
            ORDER BY COALESCE((data->>'failed_attempts')::int, 0) ASC,
                     updated_at ASC
            LIMIT $3
            """,
            networks,
            int(self._progress.started_at),
            limit,
            timeout=self._brotr.config.timeouts.query,
        )

        candidates = []
        for row in rows:
            try:
                relay = Relay(row["data_key"])
                candidates.append(Candidate(relay=relay, data=dict(row["data"])))
            except Exception as e:
                self._logger.warning("parse_failed", url=row["data_key"], error=str(e))

        return candidates

    async def _validate_chunk(
        self, candidates: list[Candidate]
    ) -> tuple[list[Relay], list[Candidate]]:
        """Validate a chunk of candidates concurrently.

        Creates validation tasks for all candidates and awaits them together
        using asyncio.gather. Each validation respects network-specific
        semaphores to limit concurrency.

        Updates the progress counters (processed, success, failure) as results
        are processed.

        Args:
            candidates: List of Candidate objects to validate.

        Returns:
            A tuple of (valid_relays, invalid_candidates) where:
                - valid_relays: List of Relay objects that passed validation
                - invalid_candidates: List of Candidate objects that failed
        """
        tasks = [self._validate_one(c) for c in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid: list[Relay] = []
        invalid: list[Candidate] = []

        for candidate, result in zip(candidates, results, strict=True):
            self._progress.processed += 1
            if result is True:
                self._progress.success += 1
                valid.append(candidate.relay)
            else:
                self._progress.failure += 1
                invalid.append(candidate)

        return valid, invalid

    async def _validate_one(self, candidate: Candidate) -> bool:
        """Validate a single relay candidate using the Nostr protocol.

        Attempts to connect to the relay and verify it speaks Nostr by:
            1. Establishing a WebSocket connection (with proxy for Tor/I2P)
            2. Sending a REQ message with an impossible filter
            3. Expecting a valid Nostr response (EOSE, EVENT, or NOTICE)

        Uses the network-specific semaphore to limit concurrent connections.
        Timeouts and proxy settings are determined by the relay's network type.

        Args:
            candidate: The Candidate object containing the relay to validate.

        Returns:
            True if the relay is a valid Nostr relay, False otherwise.
            Returns False for unknown network types or any exceptions.
        """
        relay = candidate.relay
        semaphore = self._semaphores.get(relay.network)

        if semaphore is None:
            self._logger.warning("unknown_network", url=relay.url, network=relay.network.value)
            return False

        async with semaphore:
            network_config = self._config.networks.get(relay.network)
            proxy_url = self._config.networks.get_proxy_url(relay.network)
            try:
                return await is_nostr_relay(relay, proxy_url, network_config.timeout)
            except Exception:
                return False

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    async def _persist_results(self, valid: list[Relay], invalid: list[Candidate]) -> None:
        """Persist validation results to the database.

        For invalid candidates:
            - Increments the failed_attempts counter in their service_data record
            - This allows prioritization by failure count in future cycles

        For valid relays:
            - Inserts them into the relays table via brotr.insert_relays()
            - Deletes their candidate records from service_data
            - Logs each promotion with URL and network type

        Errors during persistence are logged but do not raise exceptions,
        allowing the cycle to continue processing other results.

        Args:
            valid: List of Relay objects that passed validation.
            invalid: List of Candidate objects that failed validation.
        """
        # Update failed candidates
        if invalid:
            updates = [
                (
                    "validator",
                    "candidate",
                    c.relay.url,
                    {**c.data, "failed_attempts": c.failed_attempts + 1},
                )
                for c in invalid
            ]
            try:
                await self._brotr.upsert_service_data(updates)
            except Exception as e:
                self._logger.error("update_failed", count=len(invalid), error=str(e))

        # Promote valid relays
        if valid:
            try:
                await self._brotr.insert_relays(valid)
                deletes = [("validator", "candidate", r.url) for r in valid]
                await self._brotr.delete_service_data(deletes)
                for relay in valid:
                    self._logger.info("promoted", url=relay.url, network=relay.network.value)
            except Exception as e:
                self._logger.error("promote_failed", count=len(valid), error=str(e))
