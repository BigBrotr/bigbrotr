"""Validator service for BigBrotr.

Validates relay candidates discovered by the
[Finder][bigbrotr.services.finder.Finder] service by checking whether
they speak the Nostr protocol via WebSocket. Valid candidates are promoted
to the relays table; invalid ones have their failure counter incremented
and are retried in future cycles.

Validation criteria: a candidate is valid if it accepts a WebSocket
connection and responds to a Nostr REQ message with EOSE, EVENT, NOTICE,
or AUTH, as determined by
[is_nostr_relay][bigbrotr.utils.transport.is_nostr_relay].

Note:
    Each cycle initializes per-network semaphores from
    [NetworkConfig][bigbrotr.services.common.configs.NetworkConfig],
    cleans up stale/exhausted candidates, then processes remaining
    candidates in configurable chunks. Candidate priority is ordered by
    fewest failures first (most likely to succeed).

See Also:
    [ValidatorConfig][bigbrotr.services.validator.ValidatorConfig]:
        Configuration model for networks, processing, and cleanup.
    [BaseService][bigbrotr.core.base_service.BaseService]: Abstract base
        class providing ``run()``, ``run_forever()``, and ``from_yaml()``.
    [Brotr][bigbrotr.core.brotr.Brotr]: Database facade used for
        candidate queries and relay promotion.
    [Finder][bigbrotr.services.finder.Finder]: Upstream service that
        discovers and inserts candidates.
    [Monitor][bigbrotr.services.monitor.Monitor]: Downstream service
        that health-checks promoted relays.
    [is_nostr_relay][bigbrotr.utils.transport.is_nostr_relay]: WebSocket
        probe function used for validation.
    [promote_candidates][bigbrotr.services.common.queries.promote_candidates]:
        Atomic insert+delete query for promotion.

Examples:
    ```python
    from bigbrotr.core import Brotr
    from bigbrotr.services import Validator

    brotr = Brotr.from_yaml("config/brotr.yaml")
    validator = Validator.from_yaml("config/services/validator.yaml", brotr=brotr)

    async with brotr:
        async with validator:
            await validator.run_forever()
    ```
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

import asyncpg

from bigbrotr.core.base_service import BaseService
from bigbrotr.models import Relay
from bigbrotr.models.constants import (
    NetworkType,
    ServiceName,
)
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.mixins import BatchProgressMixin, NetworkSemaphoreMixin
from bigbrotr.services.common.queries import (
    count_candidates,
    delete_exhausted_candidates,
    delete_stale_candidates,
    fetch_candidate_chunk,
    promote_candidates,
)
from bigbrotr.utils.transport import is_nostr_relay

from .configs import ValidatorConfig


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr


# =============================================================================
# Data Types
# =============================================================================


@dataclass(frozen=True, slots=True)
class Candidate:
    """Relay candidate pending validation.

    Wraps a [Relay][bigbrotr.models.relay.Relay] object with its
    ``service_state`` metadata, providing convenient access to validation
    state (e.g., failure count).

    Attributes:
        relay: [Relay][bigbrotr.models.relay.Relay] object with URL and
            network information.
        data: Metadata from the ``service_state`` table (``network``,
            ``failed_attempts``, etc.).

    See Also:
        [fetch_candidate_chunk][bigbrotr.services.common.queries.fetch_candidate_chunk]:
            Query that produces the rows from which candidates are built.
    """

    relay: Relay
    data: dict[str, Any]

    @property
    def failed_attempts(self) -> int:
        """Return the number of failed validation attempts for this candidate."""
        attempts: int = self.data.get("failed_attempts", 0)
        return attempts


# =============================================================================
# Service
# =============================================================================


class Validator(BatchProgressMixin, NetworkSemaphoreMixin, BaseService[ValidatorConfig]):
    """Validates relay candidates by checking if they speak the Nostr protocol.

    Processes candidate URLs discovered by the
    [Finder][bigbrotr.services.finder.Finder] service. Valid relays are
    promoted to the relays table via
    [promote_candidates][bigbrotr.services.common.queries.promote_candidates];
    invalid ones have their failure counter incremented for retry in
    future cycles.

    Each cycle initializes per-network semaphores via
    [NetworkSemaphoreMixin][bigbrotr.services.common.mixins.NetworkSemaphoreMixin],
    cleans up stale/exhausted candidates, then processes remaining
    candidates in configurable chunks. Supports clearnet (direct),
    Tor (.onion via SOCKS5), and I2P (.i2p via SOCKS5).

    See Also:
        [ValidatorConfig][bigbrotr.services.validator.ValidatorConfig]:
            Configuration model for this service.
        [Finder][bigbrotr.services.finder.Finder]: Upstream service that
            creates the candidates validated here.
        [Monitor][bigbrotr.services.monitor.Monitor]: Downstream service
            that health-checks promoted relays.
        [is_nostr_relay][bigbrotr.utils.transport.is_nostr_relay]:
            WebSocket probe used by ``_validate_one()``.
    """

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.VALIDATOR
    CONFIG_CLASS: ClassVar[type[ValidatorConfig]] = ValidatorConfig

    def __init__(self, brotr: Brotr, config: ValidatorConfig | None = None) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: ValidatorConfig
        self._semaphores: dict[NetworkType, asyncio.Semaphore] = {}
        self._init_progress()

    # -------------------------------------------------------------------------
    # Main Cycle
    # -------------------------------------------------------------------------

    async def run(self) -> None:
        """Execute one complete validation cycle.

        Orchestrates cleanup, candidate counting, chunk-based processing, and
        metrics emission. Respects ``is_running`` for graceful shutdown and
        ``max_candidates`` for per-cycle limits.
        """
        self._progress.reset()
        self._init_semaphores(self._config.networks)

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
        self._progress.total = await count_candidates(self._brotr, networks)

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

    # -------------------------------------------------------------------------
    # Metrics
    # -------------------------------------------------------------------------

    def _emit_metrics(self) -> None:
        """Emit Prometheus gauge metrics for the current cycle state.

        Updates total, processed, success, and failure gauges. Called after
        cleanup, after each chunk, and at cycle completion.
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

        Stale candidates appear when a relay was validated by another cycle,
        manually added, or re-discovered by the
        [Finder][bigbrotr.services.finder.Finder]. Removing them prevents
        wasted validation attempts.

        See Also:
            [delete_stale_candidates][bigbrotr.services.common.queries.delete_stale_candidates]:
                The SQL query executed by this method.
        """
        count = await delete_stale_candidates(self._brotr)
        if count > 0:
            self.inc_counter("total_stale_removed", count)
            self._logger.info("stale_removed", count=count)

    async def _cleanup_exhausted(self) -> None:
        """Remove candidates that have exceeded the maximum failure threshold.

        Prevents permanently broken relays from consuming validation resources.
        Controlled by ``cleanup.enabled`` and ``cleanup.max_failures`` in
        [CleanupConfig][bigbrotr.services.validator.CleanupConfig].

        See Also:
            ``delete_exhausted_candidates``: The SQL query executed.
        """
        if not self._config.cleanup.enabled:
            return

        count = await delete_exhausted_candidates(
            self._brotr,
            self._config.cleanup.max_failures,
        )
        if count > 0:
            self.inc_counter("total_exhausted_removed", count)
            self._logger.info(
                "exhausted_removed",
                count=count,
                threshold=self._config.cleanup.max_failures,
            )

    # -------------------------------------------------------------------------
    # Processing
    # -------------------------------------------------------------------------

    async def _process_all(self, networks: list[str]) -> None:
        """Process all pending candidates in configurable chunks.

        Iterates until no candidates remain, the ``max_candidates`` limit is
        reached, or the service is stopped. Each chunk is fetched, validated
        concurrently, and persisted in a single iteration.

        Args:
            networks: Enabled network type strings to process.
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
        """Fetch the next chunk of candidates ordered by priority.

        Prioritizes candidates with fewer failures (more likely to succeed),
        then by age (FIFO within the same failure count). Only fetches
        candidates updated before the cycle start to avoid reprocessing.

        Args:
            networks: Enabled network type strings to fetch.
            limit: Maximum candidates to return.

        Returns:
            List of Candidate objects, possibly empty if none remain.
        """
        rows = await fetch_candidate_chunk(
            self._brotr,
            networks,
            int(self._progress.started_at),
            limit,
        )

        candidates = []
        for row in rows:
            try:
                relay = Relay(row["state_key"])
                candidates.append(Candidate(relay=relay, data=dict(row["state_value"])))
            except (ValueError, TypeError) as e:
                self._logger.warning("parse_failed", url=row["state_key"], error=str(e))

        return candidates

    async def _validate_chunk(
        self, candidates: list[Candidate]
    ) -> tuple[list[Relay], list[Candidate]]:
        """Validate a chunk of candidates concurrently.

        Runs all validations via ``asyncio.gather`` with per-network semaphores
        and updates progress counters as results arrive.

        Args:
            candidates: Candidates to validate.

        Returns:
            Tuple of (valid_relays, invalid_candidates).
        """
        tasks = [self._validate_one(c) for c in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Re-raise CancelledError — gather(return_exceptions=True) captures it as a result
        for r in results:
            if isinstance(r, asyncio.CancelledError):
                raise r

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
        """Validate a single relay candidate by connecting and testing the Nostr protocol.

        Uses the network-specific semaphore and proxy settings from
        [NetworkConfig][bigbrotr.services.common.configs.NetworkConfig].
        Delegates the actual WebSocket probe to
        [is_nostr_relay][bigbrotr.utils.transport.is_nostr_relay].

        Args:
            candidate: [Candidate][bigbrotr.services.validator.Candidate]
                to validate.

        Returns:
            ``True`` if the relay speaks Nostr protocol, ``False`` otherwise.
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
            except (TimeoutError, OSError):
                return False

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    async def _persist_results(self, valid: list[Relay], invalid: list[Candidate]) -> None:
        """Persist validation results to the database.

        Invalid candidates have their failure counter incremented (as
        [ServiceState][bigbrotr.models.service_state.ServiceState]
        updates) for prioritization in future cycles. Valid relays are
        atomically inserted into the relays table and their candidate
        records deleted via
        [promote_candidates][bigbrotr.services.common.queries.promote_candidates].

        Args:
            valid: [Relay][bigbrotr.models.relay.Relay] objects that
                passed validation.
            invalid: [Candidate][bigbrotr.services.validator.Candidate]
                objects that failed validation.
        """
        # Update failed candidates
        if invalid:
            now = int(time.time())
            updates: list[ServiceState] = [
                ServiceState(
                    service_name=self.SERVICE_NAME,
                    state_type=ServiceStateType.CANDIDATE,
                    state_key=c.relay.url,
                    state_value={**c.data, "failed_attempts": c.failed_attempts + 1},
                    updated_at=now,
                )
                for c in invalid
            ]
            try:
                await self._brotr.upsert_service_state(updates)
            except (asyncpg.PostgresError, OSError) as e:
                self._logger.error("update_failed", count=len(invalid), error=str(e))

        # Promote valid relays (atomic: insert + delete in one transaction)
        if valid:
            try:
                await promote_candidates(self._brotr, valid)
                for relay in valid:
                    self._logger.info("promoted", url=relay.url, network=relay.network.value)
            except (asyncpg.PostgresError, OSError) as e:
                self._logger.error("promote_failed", count=len(valid), error=str(e))
