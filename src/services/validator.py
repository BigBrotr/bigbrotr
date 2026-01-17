"""Validates relay candidates by checking if they speak Nostr protocol.

Valid candidates are promoted to the relays table. Invalid ones have their
failure counter incremented and will be retried in future cycles.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

from core.base_service import BaseService, BaseServiceConfig
from models import Relay
from models.relay import NetworkType
from utils.network import NetworkConfig
from utils.transport import is_nostr_relay


if TYPE_CHECKING:
    from core.brotr import Brotr


# =============================================================================
# Data Types
# =============================================================================


@dataclass(slots=True)
class Candidate:
    """Relay candidate pending validation."""

    relay: Relay
    data: dict[str, Any]

    @property
    def failed_attempts(self) -> int:
        return self.data.get("failed_attempts", 0)


# =============================================================================
# Configuration
# =============================================================================


class ProcessingConfig(BaseModel):
    """Chunk processing settings."""

    chunk_size: int = Field(default=100, ge=10, le=1000)
    max_candidates: int | None = Field(default=None, ge=1)


class CleanupConfig(BaseModel):
    """Exhausted candidate cleanup settings."""

    enabled: bool = Field(default=False)
    max_failures: int = Field(default=100, ge=1, le=1000)


class ValidatorConfig(BaseServiceConfig):
    """Validator service configuration."""

    networks: NetworkConfig = Field(default_factory=NetworkConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    cleanup: CleanupConfig = Field(default_factory=CleanupConfig)


# =============================================================================
# Service
# =============================================================================


class Validator(BaseService[ValidatorConfig]):
    """Relay validation service."""

    SERVICE_NAME: ClassVar[str] = "validator"
    CONFIG_CLASS: ClassVar[type[ValidatorConfig]] = ValidatorConfig

    def __init__(self, brotr: Brotr, config: ValidatorConfig | None = None) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: ValidatorConfig
        self._semaphores: dict[NetworkType, asyncio.Semaphore] = {}
        # Cycle state (reset at start of each run)
        self._start_time: float = 0.0
        self._candidates: int = 0
        self._validated: int = 0
        self._invalidated: int = 0
        self._chunks: int = 0

    # -------------------------------------------------------------------------
    # Main Cycle
    # -------------------------------------------------------------------------

    async def run(self) -> None:
        """Execute one validation cycle."""
        self._reset_cycle_state()
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
        self._candidates = await self._count_candidates(networks)

        self._logger.info("candidates_available", total=self._candidates)
        self._emit_metrics()

        # Process all candidates
        await self._process_all(networks)

        self._emit_metrics()
        self._logger.info(
            "cycle_completed",
            validated=self._validated,
            invalidated=self._invalidated,
            chunks=self._chunks,
            duration_s=round(time.time() - self._start_time, 1),
        )

    def _reset_cycle_state(self) -> None:
        """Reset cycle state for a new run."""
        self._start_time = time.time()
        self._candidates = 0
        self._validated = 0
        self._invalidated = 0
        self._chunks = 0

    def _init_semaphores(self) -> None:
        """Initialize per-network concurrency semaphores."""
        self._semaphores = {
            network: asyncio.Semaphore(self._config.networks.get(network).max_tasks)
            for network in NetworkType
        }

    # -------------------------------------------------------------------------
    # Metrics
    # -------------------------------------------------------------------------

    def _emit_metrics(self) -> None:
        """Emit Prometheus metrics from current state."""
        self.set_gauge("candidates", self._candidates)
        self.set_gauge("validated", self._validated)
        self.set_gauge("invalidated", self._invalidated)

    # -------------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------------

    async def _cleanup_stale(self) -> None:
        """Remove candidates already present in relays table."""
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
        """Remove candidates exceeding failure threshold."""
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
        """Parse PostgreSQL DELETE result (format: 'DELETE N')."""
        if not result:
            return 0
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0

    async def _count_candidates(self, networks: list[str]) -> int:
        """Count total candidates for enabled networks."""
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
        """Process candidates in chunks."""
        if not networks:
            self._logger.warning("no_networks_enabled")
            return

        max_candidates = self._config.processing.max_candidates
        chunk_size = self._config.processing.chunk_size

        while self.is_running:
            # Calculate limit for this chunk
            processed = self._validated + self._invalidated
            if max_candidates is not None:
                budget = max_candidates - processed
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

            self._chunks += 1
            valid, invalid = await self._validate_chunk(candidates)
            await self._persist_results(valid, invalid)

            self._emit_metrics()
            self._logger.info(
                "chunk_completed",
                chunk=self._chunks,
                valid=len(valid),
                invalid=len(invalid),
                remaining=self._candidates - self._validated - self._invalidated,
            )

    async def _fetch_chunk(self, networks: list[str], limit: int) -> list[Candidate]:
        """Fetch next chunk of candidates.

        Note: Stale candidates (already in relays table) are cleaned up at the
        start of each cycle by _cleanup_stale(), so no subquery filter needed here.
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
            int(self._start_time),
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
        """Validate a chunk of candidates."""
        tasks = [self._validate_one(c) for c in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid: list[Relay] = []
        invalid: list[Candidate] = []

        for candidate, result in zip(candidates, results, strict=True):
            if result is True:
                self._validated += 1
                valid.append(candidate.relay)
            else:
                self._invalidated += 1
                invalid.append(candidate)

        return valid, invalid

    async def _validate_one(self, candidate: Candidate) -> bool:
        """Validate a single candidate."""
        relay = candidate.relay
        semaphore = self._semaphores.get(relay.network)

        if semaphore is None:
            self._logger.warning("unknown_network", url=relay.url, network=relay.network)
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
        """Persist validation results."""
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
