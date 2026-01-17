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

    chunk_size: int = Field(default=100, ge=10, le=1000, description="Candidates per chunk")
    max_candidates: int | None = Field(
        default=None, ge=1, description="Limit per run (None=unlimited)"
    )


class CleanupConfig(BaseModel):
    """Exhausted candidate cleanup settings."""

    enabled: bool = Field(default=False, description="Remove candidates with too many failures")
    max_failures: int = Field(default=10, ge=1, le=100, description="Failure threshold for removal")


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
        self._run_start: float = 0.0
        self._cycle_valid: int = 0
        self._cycle_invalid: int = 0
        # Per-network tracking
        self._cycle_valid_by_network: dict[str, int] = {}
        self._cycle_invalid_by_network: dict[str, int] = {}
        self._cycle_chunks: int = 0

    async def run(self) -> None:
        self._run_start = time.time()
        self._cycle_valid = 0
        self._cycle_invalid = 0
        self._cycle_valid_by_network = {}
        self._cycle_invalid_by_network = {}
        self._cycle_chunks = 0
        self._init_semaphores()

        networks = self._config.networks.get_enabled_networks()
        self._logger.info(
            "cycle_started",
            chunk_size=self._config.processing.chunk_size,
            max_candidates=self._config.processing.max_candidates,
            networks=networks,
        )

        await self._cleanup_promoted()
        await self._cleanup_exhausted()

        stats = await self._count_candidates_by_network(networks)
        total = sum(stats.values())
        self.set_gauge("candidates", total)
        # Per-network candidate gauges
        for network, count in stats.items():
            self.set_gauge(f"candidates_{network}", count)
        self._logger.info("candidates_available", total=total, by_network=stats)

        await self._process(networks)

        duration = time.time() - self._run_start

        # Final metrics update (also called after each chunk for real-time visibility)
        self._update_progress_metrics(networks)

        # Cumulative counters (only at end of cycle)
        self.inc_counter("total_processed", self._cycle_valid + self._cycle_invalid)
        self.inc_counter("total_promoted", self._cycle_valid)

        self._logger.info(
            "cycle_completed",
            valid=self._cycle_valid,
            invalid=self._cycle_invalid,
            chunks=self._cycle_chunks,
            duration_s=round(duration, 1),
        )

    def _init_semaphores(self) -> None:
        """Initialize per-network concurrency semaphores."""
        self._semaphores = {
            network: asyncio.Semaphore(self._config.networks.get(network).max_tasks)
            for network in NetworkType
        }

    def _update_progress_metrics(self, networks: list[str]) -> None:
        """Update gauges with current cycle progress.

        Called after each chunk for real-time visibility in Grafana,
        and once more at end of cycle.
        """
        self.set_gauge("validated", self._cycle_valid)
        self.set_gauge("invalidated", self._cycle_invalid)
        self.set_gauge("chunks", self._cycle_chunks)

        for network in networks:
            self.set_gauge(f"validated_{network}", self._cycle_valid_by_network.get(network, 0))
            self.set_gauge(f"invalidated_{network}", self._cycle_invalid_by_network.get(network, 0))

    # -------------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------------

    @staticmethod
    def _parse_delete_count(result: str | None) -> int:
        """Extract row count from PostgreSQL DELETE result (format: 'DELETE N')."""
        if not result:
            return 0
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0

    async def _cleanup_promoted(self) -> None:
        """Remove stale candidates already present in relays table."""
        result = await self._brotr.pool.execute(
            """
            DELETE FROM service_data
            WHERE service_name = 'validator'
              AND data_type = 'candidate'
              AND data_key IN (SELECT url FROM relays)
            """,
            timeout=self._brotr.config.timeouts.query,
        )
        count = self._parse_delete_count(result)
        self.set_gauge("stale_removed", count)
        if count > 0:
            self.inc_counter("total_stale_removed", count)
            self._logger.info("stale_candidates_removed", count=count)

    async def _cleanup_exhausted(self) -> None:
        """Remove candidates that exceeded the failure threshold."""
        if not self._config.cleanup.enabled:
            self.set_gauge("exhausted_removed", 0)
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
        count = self._parse_delete_count(result)
        self.set_gauge("exhausted_removed", count)
        if count > 0:
            self.inc_counter("total_exhausted_removed", count)
            self._logger.info(
                "exhausted_candidates_removed",
                count=count,
                threshold=self._config.cleanup.max_failures,
            )

    async def _count_candidates_by_network(self, networks: list[str]) -> dict[str, int]:
        """Get candidate counts by network."""
        rows = await self._brotr.pool.fetch(
            """
            SELECT data->>'network' AS network, COUNT(*) AS count
            FROM service_data
            WHERE service_name = 'validator'
              AND data_type = 'candidate'
              AND data->>'network' = ANY($1)
            GROUP BY data->>'network'
            """,
            networks,
            timeout=self._brotr.config.timeouts.query,
        )
        return {row["network"]: row["count"] for row in rows}

    # -------------------------------------------------------------------------
    # Processing
    # -------------------------------------------------------------------------

    async def _process(self, networks: list[str]) -> None:
        """Process candidates in chunks until exhausted or limit reached."""
        if not networks:
            self._logger.warning("no_networks_enabled")
            return

        chunk_index = 0
        total_processed = 0

        while self.is_running:
            # Compute chunk limit respecting max_candidates
            if self._config.processing.max_candidates is not None:
                remaining = self._config.processing.max_candidates - total_processed
                if remaining <= 0:
                    self._logger.debug(
                        "max_candidates_reached", limit=self._config.processing.max_candidates
                    )
                    break
                limit = min(self._config.processing.chunk_size, remaining)
            else:
                limit = self._config.processing.chunk_size

            candidates = await self._fetch_candidates(networks, limit)
            if not candidates:
                self._logger.debug("no_more_candidates")
                break

            chunk_index += 1

            # Validate candidates in parallel (bounded by per-network semaphores)
            tasks = [self._validate_candidate(c) for c in candidates]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            valid_relays: list[Relay] = []
            failed_candidates: list[Candidate] = []

            for candidate, result in zip(candidates, results, strict=True):
                network = candidate.relay.network.value
                if result is True:
                    self._cycle_valid += 1
                    self._cycle_valid_by_network[network] = (
                        self._cycle_valid_by_network.get(network, 0) + 1
                    )
                    valid_relays.append(candidate.relay)
                else:
                    self._cycle_invalid += 1
                    self._cycle_invalid_by_network[network] = (
                        self._cycle_invalid_by_network.get(network, 0) + 1
                    )
                    failed_candidates.append(candidate)

            total_processed += len(candidates)
            self._cycle_chunks = chunk_index

            await self._persist_results(valid_relays, failed_candidates)

            # Update metrics after each chunk for real-time visibility
            self._update_progress_metrics(networks)

            self._logger.debug(
                "chunk_completed",
                chunk=chunk_index,
                valid=len(valid_relays),
                invalid=len(failed_candidates),
                total=total_processed,
            )

            # Log progress every 10 chunks
            if chunk_index % 10 == 0:
                elapsed = time.time() - self._run_start
                self._logger.info(
                    "progress",
                    chunks=chunk_index,
                    processed=total_processed,
                    valid=self._cycle_valid,
                    invalid=self._cycle_invalid,
                    elapsed_s=round(elapsed, 1),
                )

    async def _fetch_candidates(self, networks: list[str], limit: int) -> list[Candidate]:
        """Fetch candidates prioritized by fewest failures, then oldest.

        Only returns candidates updated before this cycle to prevent
        re-processing freshly persisted ones within the same run.
        """
        rows = await self._brotr.pool.fetch(
            """
            SELECT data_key, data
            FROM service_data
            WHERE service_name = 'validator'
              AND data_type = 'candidate'
              AND data->>'network' = ANY($1)
              AND data_key NOT IN (SELECT url FROM relays)
              AND updated_at < $2
            ORDER BY COALESCE((data->>'failed_attempts')::int, 0) ASC,
                     updated_at ASC
            LIMIT $3
            """,
            networks,
            int(self._run_start),
            limit,
            timeout=self._brotr.config.timeouts.query,
        )

        candidates = []
        for row in rows:
            try:
                relay = Relay(row["data_key"])
                candidates.append(Candidate(relay=relay, data=dict(row["data"])))
            except Exception as e:
                self._logger.warning("candidate_parse_failed", url=row["data_key"], error=str(e))

        return candidates

    async def _validate_candidate(self, candidate: Candidate) -> bool:
        """Check if candidate speaks Nostr protocol."""
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

    async def _persist_results(
        self, valid_relays: list[Relay], failed_candidates: list[Candidate]
    ) -> None:
        """Persist validation results: promote valid, increment failures for invalid."""
        if failed_candidates:
            updates = [
                (
                    "validator",
                    "candidate",
                    c.relay.url,
                    {**c.data, "failed_attempts": c.failed_attempts + 1},
                )
                for c in failed_candidates
            ]
            try:
                await self._brotr.upsert_service_data(updates)
            except Exception as e:
                self._logger.error(
                    "failures_update_failed", count=len(failed_candidates), error=str(e)
                )

        if valid_relays:
            try:
                await self._brotr.insert_relays(valid_relays)
                deletes = [("validator", "candidate", r.url) for r in valid_relays]
                await self._brotr.delete_service_data(deletes)
                for relay in valid_relays:
                    self._logger.info("relay_promoted", url=relay.url, network=relay.network.value)
            except Exception as e:
                self._logger.error("promotion_failed", count=len(valid_relays), error=str(e))
