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
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.common.mixins import BatchProgressMixin, NetworkSemaphoreMixin
from bigbrotr.services.common.queries import (
    count_candidates,
    delete_exhausted_candidates,
    delete_stale_candidates,
    fetch_candidate_chunk,
    promote_candidates,
)
from bigbrotr.utils.protocol import is_nostr_relay

from .configs import ValidatorConfig


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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
            WebSocket probe used by ``validate_candidate()``.
    """

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.VALIDATOR
    CONFIG_CLASS: ClassVar[type[ValidatorConfig]] = ValidatorConfig

    def __init__(self, brotr: Brotr, config: ValidatorConfig | None = None) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: ValidatorConfig

    # -------------------------------------------------------------------------
    # Main Cycle
    # -------------------------------------------------------------------------

    async def run(self) -> None:
        """Execute one complete validation cycle.

        Orchestrates cleanup, candidate counting, chunk-based processing, and
        metrics emission. Respects ``is_running`` for graceful shutdown and
        ``max_candidates`` for per-cycle limits.
        """
        self.progress.reset()

        networks = self._config.networks.get_enabled_networks()
        self._logger.info(
            "cycle_started",
            chunk_size=self._config.processing.chunk_size,
            max_candidates=self._config.processing.max_candidates,
            networks=networks,
        )

        # Cleanup and count
        await self.cleanup_stale()
        await self.cleanup_exhausted()
        self.progress.total = await count_candidates(self._brotr, networks)

        self._logger.info("candidates_available", total=self.progress.total)
        self.emit_progress_metrics()

        # Process all candidates
        await self._process_all(networks)

        self.emit_progress_metrics()
        self._logger.info(
            "cycle_completed",
            validated=self.progress.success,
            invalidated=self.progress.failure,
            chunks=self.progress.chunks,
            duration_s=self.progress.elapsed,
        )

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def cleanup_stale(self) -> int:
        """Remove candidates whose URLs already exist in the relays table.

        Stale candidates appear when a relay was validated by another cycle,
        manually added, or re-discovered by the
        [Finder][bigbrotr.services.finder.Finder]. Removing them prevents
        wasted validation attempts.

        Returns:
            Number of stale candidates removed.

        See Also:
            [delete_stale_candidates][bigbrotr.services.common.queries.delete_stale_candidates]:
                The SQL query executed by this method.
        """
        count = await delete_stale_candidates(self._brotr)
        if count > 0:
            self.inc_counter("total_stale_removed", count)
            self._logger.info("stale_removed", count=count)
        return count

    async def cleanup_exhausted(self) -> int:
        """Remove candidates that have exceeded the maximum failure threshold.

        Prevents permanently broken relays from consuming validation resources.
        Controlled by ``cleanup.enabled`` and ``cleanup.max_failures`` in
        [CleanupConfig][bigbrotr.services.validator.CleanupConfig].

        Returns:
            Number of exhausted candidates removed.

        See Also:
            ``delete_exhausted_candidates``: The SQL query executed.
        """
        if not self._config.cleanup.enabled:
            return 0

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
        return count

    async def validate_candidate(self, candidate: Candidate) -> bool:
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
        semaphore = self.get_semaphore(relay.network)

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

    async def validate_chunks(
        self,
        networks: list[str] | None = None,
        *,
        chunk_size: int | None = None,
        max_candidates: int | None = None,
    ) -> AsyncIterator[tuple[list[Relay], list[Candidate]]]:
        """Yield ``(valid_relays, invalid_candidates)`` for each processed chunk.

        Handles chunk fetching, budget calculation, and concurrent validation.
        Persistence is left to the caller.

        Args:
            networks: Network types to process. ``None`` uses config defaults.
            chunk_size: Override for per-chunk limit. ``None`` uses config.
            max_candidates: Override for total limit. ``None`` uses config.

        Yields:
            Tuple of (valid Relay list, invalid Candidate list) per chunk.
        """
        if networks is None:
            networks = self._config.networks.get_enabled_networks()

        _chunk_size = chunk_size or self._config.processing.chunk_size
        _max = (
            max_candidates if max_candidates is not None else self._config.processing.max_candidates
        )
        processed = 0

        while self.is_running:
            if _max is not None:
                budget = _max - processed
                if budget <= 0:
                    break
                limit = min(_chunk_size, budget)
            else:
                limit = _chunk_size

            candidates = await self._fetch_chunk(networks, limit)
            if not candidates:
                break

            valid, invalid = await self._validate_chunk(candidates)
            processed += len(valid) + len(invalid)
            yield valid, invalid

    async def _process_all(self, networks: list[str]) -> None:
        """Process all pending candidates using the ``validate_chunks`` generator.

        Consumes chunks, updates progress, persists results, and emits metrics.

        Args:
            networks: Enabled network type strings to process.
        """
        if not networks:
            self._logger.warning("no_networks_enabled")
            return

        async for valid, invalid in self.validate_chunks(networks):
            self.progress.processed += len(valid) + len(invalid)
            self.progress.success += len(valid)
            self.progress.failure += len(invalid)
            self.progress.chunks += 1

            await self._persist_results(valid, invalid)
            self.emit_progress_metrics()
            self._logger.info(
                "chunk_completed",
                chunk=self.progress.chunks,
                valid=len(valid),
                invalid=len(invalid),
                remaining=self.progress.remaining,
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
            int(self.progress.started_at),
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

        Runs all validations via ``asyncio.gather`` with per-network semaphores.
        Progress tracking is handled by the caller (``_process_all``).

        Args:
            candidates: Candidates to validate.

        Returns:
            Tuple of (valid_relays, invalid_candidates).
        """
        tasks = [self.validate_candidate(c) for c in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Re-raise CancelledError — gather(return_exceptions=True) captures it as a result
        for r in results:
            if isinstance(r, asyncio.CancelledError):
                raise r

        valid: list[Relay] = []
        invalid: list[Candidate] = []

        for candidate, result in zip(candidates, results, strict=True):
            if result is True:
                valid.append(candidate.relay)
            else:
                invalid.append(candidate)

        return valid, invalid

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
