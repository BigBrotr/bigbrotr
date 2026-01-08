"""
Validator Service for BigBrotr.

Validates candidate relay URLs discovered by the Finder service:
- Reads candidates from services table
- Tests WebSocket connectivity
- Adds valid relays to the relays table
- Tracks retry count for failed candidates

Usage:
    from core import Brotr
    from services import Validator

    brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
    validator = Validator.from_yaml("yaml/services/validator.yaml", brotr=brotr)

    async with brotr.pool:
        async with validator:
            await validator.run_forever(interval=300)
"""

from __future__ import annotations

import asyncio
import heapq
import math
import random
import time
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

from core.base_service import BaseService
from models import Relay
from models.relay import NetworkType
from utils.keys import KeysConfig
from utils.proxy import ProxyConfig


if TYPE_CHECKING:
    from nostr_sdk import Keys

    from core.brotr import Brotr


# =============================================================================
# Configuration
# =============================================================================


class ConcurrencyConfig(BaseModel):
    """Concurrency configuration for parallel validation."""

    max_parallel: int = Field(default=10, ge=1, le=100, description="Maximum concurrent operations")


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


class ValidatorConfig(BaseModel):
    """Validator configuration."""

    interval: float = Field(default=300.0, ge=60.0, description="Seconds between validation cycles")
    connection_timeout: float = Field(
        default=10.0, ge=0.1, le=60.0, description="WebSocket connection timeout"
    )
    max_candidates_per_run: int | None = Field(
        default=None, ge=1, description="Max candidates to validate per cycle (None = unlimited)"
    )
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    cleanup: CleanupConfig = Field(default_factory=CleanupConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    keys: KeysConfig = Field(default_factory=KeysConfig)


# =============================================================================
# Service
# =============================================================================


class Validator(BaseService[ValidatorConfig]):
    """
    Relay validation service.

    Validates candidate relay URLs discovered by the Seeder and Finder services.
    Tests WebSocket connectivity and adds valid relays to the database.

    Workflow:
    1. Read candidates from service_data table (service_name=validator, data_type=candidate)
    2. If max_candidates_per_run is set, select candidates probabilistically
       (candidates with more failed attempts have lower probability)
    3. Test WebSocket connection for each candidate
    4. If valid: insert into relays table, remove from candidates
    5. If invalid: increment retry counter in value.failed_attempts
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
        self._validated_count: int = 0
        self._failed_count: int = 0

        # Nostr keys for NIP-42 authentication
        self._keys: Keys | None = self._config.keys.keys

    async def run(self) -> None:
        """Run single validation cycle."""
        cycle_start = time.time()
        self._validated_count = 0
        self._failed_count = 0

        # Fetch all candidates from service_data table
        # Candidates are written by Seeder and Finder with service_name='validator'
        all_candidates = await self._brotr.get_service_data("validator", "candidate")

        if not all_candidates:
            self._logger.info("no_candidates_to_validate")
            return

        # Select candidates to validate this run
        candidates = self._select_candidates(all_candidates)
        self._logger.info(
            "validation_started",
            total_candidates=len(all_candidates),
            selected=len(candidates),
        )

        # Test each candidate in parallel
        semaphore = asyncio.Semaphore(self._config.concurrency.max_parallel)
        tasks = [self._validate_candidate(c, semaphore) for c in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect batch operations
        valid_relays: list[Relay] = []
        delete_keys: list[str] = []
        retry_records: list[tuple[str, int]] = []

        for result in results:
            if isinstance(result, (Exception, BaseException)):
                continue
            if result is None:
                continue
            url, is_valid, failed_attempts = result
            if is_valid:
                try:
                    relay = Relay(url)
                    valid_relays.append(relay)
                    delete_keys.append(url)
                    self._validated_count += 1
                except Exception as e:
                    self._logger.warning(
                        "parse_failed", error=str(e), error_type=type(e).__name__, url=url
                    )
                    self._failed_count += 1
            else:
                retry_records.append((url, failed_attempts + 1))
                self._failed_count += 1

        # Execute batch database operations in chunks (max 1000 per batch)
        batch_size = 1000

        if valid_relays:
            for i in range(0, len(valid_relays), batch_size):
                chunk = valid_relays[i : i + batch_size]
                try:
                    await self._brotr.insert_relays(chunk)
                except Exception as e:
                    self._logger.error(
                        "insert_relays_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        count=len(chunk),
                    )

        if delete_keys:
            for i in range(0, len(delete_keys), batch_size):
                chunk = delete_keys[i : i + batch_size]
                try:
                    delete_records = [("validator", "candidate", key) for key in chunk]
                    await self._brotr.delete_service_data(delete_records)
                except Exception as e:
                    self._logger.error(
                        "delete_candidates_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        count=len(chunk),
                    )

        if retry_records:
            for i in range(0, len(retry_records), batch_size):
                chunk = retry_records[i : i + batch_size]
                try:
                    upsert_records = [
                        ("validator", "candidate", url, {"failed_attempts": failed_attempts})
                        for url, failed_attempts in chunk
                    ]
                    await self._brotr.upsert_service_data(upsert_records)
                except Exception as e:
                    self._logger.error(
                        "upsert_retries_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        count=len(chunk),
                    )

        # Optional cleanup of candidates that exceeded max attempts
        if self._config.cleanup.enabled:
            try:
                deleted = await self._brotr.delete_failed_candidates(
                    max_attempts=self._config.cleanup.max_attempts
                )
                if deleted > 0:
                    self._logger.info("failed_candidates_deleted", count=deleted)
            except Exception as e:
                self._logger.error("cleanup_failed", error=str(e), error_type=type(e).__name__)

        elapsed = time.time() - cycle_start
        self._logger.info(
            "cycle_completed",
            validated=self._validated_count,
            failed=self._failed_count,
            duration=round(elapsed, 2),
        )

    def _select_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Select candidates to validate this run.

        If max_candidates_per_run is None, return all candidates.
        Otherwise, use weighted random selection where candidates with
        fewer failed_attempts have higher probability of being selected.

        Uses Efraimidis-Spirakis algorithm for O(n log k) weighted sampling
        without replacement, where n = len(candidates), k = max_per_run.
        This is much faster than the previous O(n * k) approach for large n.
        """
        max_per_run = self._config.max_candidates_per_run

        if max_per_run is None or len(candidates) <= max_per_run:
            return candidates

        # Calculate weights: weight = 1 / (failed_attempts + 1)
        # More failed_attempts = lower weight = less likely to be selected
        weights = []
        for c in candidates:
            failed_attempts = c["value"].get("failed_attempts", 0)
            weight = 1.0 / (failed_attempts + 1)
            weights.append(weight)

        # Check for zero total weight edge case
        total_weight = sum(weights)
        if total_weight == 0:
            return random.sample(candidates, max_per_run)

        # Efraimidis-Spirakis algorithm: O(n log k) weighted sampling without replacement
        # For each item, compute key = u^(1/weight) where u ~ Uniform(0,1)
        # Then select the k items with the largest keys
        # We use -log(key) = -log(u)/weight to avoid numerical issues with small numbers
        # and use a min-heap of size k to efficiently track the top k items

        # Generate (priority, index) pairs where priority = log(random()) / weight
        # We want the LARGEST keys, so we use a min-heap with NEGATIVE priorities
        heap: list[tuple[float, int]] = []

        for i, weight in enumerate(weights):
            if weight > 0:
                # key = random^(1/weight), we want largest keys
                # Using log: log(key) = log(random) / weight
                # For max-heap behavior with min-heap, we negate
                u = random.random()
                if u > 0:
                    priority = math.log(u) / weight
                    if len(heap) < max_per_run:
                        heapq.heappush(heap, (priority, i))
                    elif priority > heap[0][0]:
                        heapq.heapreplace(heap, (priority, i))

        # Extract selected candidates
        selected_indices = [idx for _, idx in heap]
        return [candidates[i] for i in selected_indices]

    async def _validate_candidate(
        self, candidate: dict[str, Any], semaphore: asyncio.Semaphore
    ) -> tuple[str, bool, int]:
        """
        Validate a single candidate relay URL.

        Returns:
            Tuple of (url, is_valid, failed_attempts) for batch processing.
        """
        async with semaphore:
            url = candidate["key"]
            value = candidate["value"]
            failed_attempts = value.get("failed_attempts", 0)

            # Test connection (with signer for NIP-42 auth if available)
            is_valid = await self._test_connection(url, self._keys)

            if is_valid:
                self._logger.debug("candidate_validated", url=url)
            else:
                self._logger.debug("candidate_failed", url=url, failed_attempts=failed_attempts + 1)

            return (url, is_valid, failed_attempts)

    async def _test_connection(self, url: str, keys: Keys) -> bool:
        """
        Validate relay by testing NIP-11 and NIP-66 RTT.

        A relay is considered valid if either:
        - NIP-11 document is fetchable (relay has info endpoint)
        - NIP-66 RTT open test succeeds (relay accepts WebSocket connections)

        This is more thorough than just opening a WebSocket - it verifies
        the relay actually speaks Nostr protocol.

        Returns True if NIP-11 or RTT test succeeds, False otherwise.
        """
        from nostr_sdk import EventBuilder, Filter  # noqa: PLC0415

        from models import Nip11, Nip66  # noqa: PLC0415

        try:
            # Create temporary Relay object from URL (auto-detects network)
            relay = Relay(url)

            # Skip overlay network relays if proxy is not enabled
            overlay_networks = (NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI)
            if relay.network in overlay_networks:
                if not self._config.proxy.is_network_enabled(relay.network):
                    return False

            # Get proxy URL for overlay networks
            proxy_url = self._config.proxy.get_proxy_url(relay.network)
            timeout = self._config.connection_timeout

            # Test 1: Try to fetch NIP-11
            nip11: Nip11 | None = None
            try:
                nip11 = await Nip11.fetch(relay, timeout=timeout, proxy_url=proxy_url)
            except Exception:
                pass

            # Test 2: Try NIP-66 RTT test (open connection)
            nip66: Nip66 | None = None
            try:
                # Create minimal event builder and filter for RTT test
                event_builder = EventBuilder.text_note("bigbrotr validation test")
                read_filter = Filter().limit(1)

                nip66 = await Nip66.test(
                    relay=relay,
                    timeout=timeout,
                    keys=keys,
                    event_builder=event_builder,
                    read_filter=read_filter,
                    proxy_url=proxy_url,
                    # Only run RTT test, skip others for validation
                    run_rtt=True,
                    run_ssl=False,
                    run_geo=False,
                    run_dns=False,
                    run_http=False,
                )
            except Exception:
                pass

            # Relay is valid if NIP-11 or RTT open succeeded
            nip11_valid = nip11 is not None
            rtt_valid = nip66 is not None and nip66.rtt_open is not None

            return nip11_valid or rtt_valid

        except Exception:
            return False

    @staticmethod
    def _detect_network(url: str) -> NetworkType:
        """Detect network type from URL.

        Args:
            url: Relay URL (e.g., wss://relay.example.com, ws://abc.onion)

        Returns:
            Network type: NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI, or NetworkType.CLEARNET
        """
        # Extract host from URL
        url_lower = url.lower()

        # Check for overlay network TLDs
        if ".onion" in url_lower:
            return NetworkType.TOR
        elif ".i2p" in url_lower:
            return NetworkType.I2P
        elif ".loki" in url_lower:
            return NetworkType.LOKI
        else:
            return NetworkType.CLEARNET
