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
from datetime import timedelta
from typing import TYPE_CHECKING, Any, ClassVar, Optional

from nostr_sdk import ClientBuilder, ClientOptions, Filter, RelayUrl
from pydantic import BaseModel, Field, model_validator

from core.base_service import BaseService
from models import Keys, Relay


if TYPE_CHECKING:
    from core.brotr import Brotr


# =============================================================================
# Configuration
# =============================================================================


class TorConfig(BaseModel):
    """Tor proxy configuration for .onion relay support."""

    enabled: bool = Field(default=True, description="Enable Tor proxy for .onion relays")
    host: str = Field(default="127.0.0.1", description="Tor proxy host")
    port: int = Field(default=9050, ge=1, le=65535, description="Tor proxy port")

    @property
    def proxy_url(self) -> str:
        """Get the SOCKS5 proxy URL for aiohttp-socks."""
        return f"socks5://{self.host}:{self.port}"


class KeysConfig(BaseModel):
    """Nostr keys configuration for NIP-42 authentication."""

    model_config = {"arbitrary_types_allowed": True}

    keys: Optional[Keys] = Field(
        default=None,
        description="Keys loaded from PRIVATE_KEY env",
    )

    @model_validator(mode="before")
    @classmethod
    def load_keys_from_env(cls, data: Any) -> Any:
        if isinstance(data, dict) and "keys" not in data:
            data["keys"] = Keys.from_env()
        return data


class ConcurrencyConfig(BaseModel):
    """Concurrency configuration for parallel validation."""

    max_parallel: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum concurrent operations",
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


class ValidatorConfig(BaseModel):
    """Validator configuration."""

    interval: float = Field(default=300.0, ge=60.0, description="Seconds between validation cycles")
    connection_timeout: float = Field(
        default=10.0, ge=1.0, le=60.0, description="WebSocket connection timeout"
    )
    max_candidates_per_run: Optional[int] = Field(
        default=None, ge=1, description="Max candidates to validate per cycle (None = unlimited)"
    )
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    cleanup: CleanupConfig = Field(default_factory=CleanupConfig)
    tor: TorConfig = Field(default_factory=TorConfig)
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
        config: Optional[ValidatorConfig] = None,
    ) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: ValidatorConfig
        self._validated_count: int = 0
        self._failed_count: int = 0

        # Nostr keys for NIP-42 authentication
        self._keys: Optional[Keys] = self._config.keys.keys

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

        # Execute batch database operations
        if valid_relays:
            try:
                await self._brotr.insert_relays(valid_relays)
            except Exception as e:
                self._logger.error(
                    "insert_relays_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    count=len(valid_relays),
                )

        if delete_keys:
            try:
                delete_records = [("validator", "candidate", key) for key in delete_keys]
                await self._brotr.delete_service_data(delete_records)
            except Exception as e:
                self._logger.error(
                    "delete_candidates_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    count=len(delete_keys),
                )

        if retry_records:
            try:
                upsert_records = [
                    ("validator", "candidate", url, {"failed_attempts": failed_attempts})
                    for url, failed_attempts in retry_records
                ]
                await self._brotr.upsert_service_data(upsert_records)
            except Exception as e:
                self._logger.error(
                    "upsert_retries_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    count=len(retry_records),
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

    async def _test_connection(self, url: str, keys: Optional[Keys] = None) -> bool:
        """
        Test WebSocket connection and verify Nostr protocol execution.

        Performs a real REQ/EOSE exchange to confirm the server speaks Nostr protocol,
        not just any WebSocket server. If keys are provided, enables automatic NIP-42
        authentication for auth-required relays.

        Returns True if the relay responds with EOSE (valid Nostr relay), False otherwise.
        """
        try:
            # Parse URL to determine network
            relay_url = RelayUrl.parse(url)
            is_tor = relay_url.is_onion()

            # Skip Tor relays if Tor is not enabled
            if is_tor and not self._config.tor.enabled:
                return False

            # Build client options
            opts = ClientOptions().connection_timeout(
                timedelta(seconds=self._config.connection_timeout)
            )

            if is_tor and self._config.tor.enabled:
                opts = opts.proxy(self._config.tor.proxy_url)

            # Build client with signer if keys available (enables NIP-42 auth)
            builder = ClientBuilder().opts(opts)
            if keys:
                builder = builder.signer(keys)

            client = builder.build()

            try:
                await client.add_relay(url)
                await client.connect()

                # Verify Nostr protocol: send REQ and expect EOSE
                # A real Nostr relay must respond with EOSE even for empty results
                # This filters out non-Nostr WebSocket servers
                f = Filter().limit(1)
                await client.fetch_events([f], timedelta(seconds=self._config.connection_timeout))

                # If fetch_events completes, relay sent EOSE (valid Nostr relay)
                await client.disconnect()
                return True

            except Exception:
                return False
            finally:
                try:
                    await client.shutdown()
                except Exception:
                    pass

        except Exception:
            return False
