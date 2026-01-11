"""
Validator Service for BigBrotr.

Validates candidate relay URLs discovered by the Finder service:
- Reads candidates from services table
- Tests WebSocket connectivity
- Adds valid relays to the relays table
- Tracks retry count for failed candidates
- Supports multiprocessing for high throughput validation

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
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any, ClassVar

import aiomultiprocess
from pydantic import BaseModel, Field

from core.base_service import BaseService
from models import Relay
from utils.network import NetworkConfig


if TYPE_CHECKING:
    from core.brotr import Brotr


# =============================================================================
# Configuration
# =============================================================================


class ValidationConfig(BaseModel):
    """Validation settings."""

    interval: float = Field(default=300.0, ge=60.0, description="Seconds between validation cycles")
    connection_timeout: float = Field(
        default=10.0, ge=0.1, le=60.0, description="WebSocket connection timeout"
    )
    max_candidates_per_run: int | None = Field(
        default=None, ge=1, description="Max candidates to validate per cycle (None = unlimited)"
    )


class ConcurrencyConfig(BaseModel):
    """Concurrency configuration for parallel validation."""

    max_processes: int = Field(default=1, ge=1, le=32, description="Number of worker processes")
    tasks_per_process: int = Field(
        default=10, ge=1, le=100, description="Maximum concurrent tasks per process"
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

    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    cleanup: CleanupConfig = Field(default_factory=CleanupConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)


# =============================================================================
# Worker Logic (Pure Functions for Multiprocessing)
# =============================================================================


async def validate_relay_task(
    url: str,
    network: str,
    failed_attempts: int,
    config_dump: dict[str, Any],
) -> tuple[str, bool, int]:
    """
    Worker task for validating a single relay.

    This is a pure function that can be executed in a worker process.

    Args:
        url: Relay URL to validate
        network: Network type string (clearnet, tor, i2p, loki)
        failed_attempts: Current number of failed attempts
        config_dump: Serialized ValidatorConfig

    Returns:
        Tuple of (url, is_valid, failed_attempts)
    """
    from nostr_sdk import Filter  # noqa: PLC0415

    from models import Relay  # noqa: PLC0415
    from utils.network import NetworkConfig  # noqa: PLC0415
    from utils.transport import connect_relay  # noqa: PLC0415

    # Reconstruct config
    network_config = NetworkConfig.model_validate(config_dump["network"])
    connection_timeout = config_dump["validation"]["connection_timeout"]

    # Get proxy URL for overlay networks
    proxy_url = network_config.get_proxy_url(network)

    try:
        # Connect to relay using transport helper
        relay = Relay(url)
        client = await connect_relay(
            relay=relay,
            proxy_url=proxy_url,
            timeout=connection_timeout,
        )

        try:
            # Send REQ for kind:1 limit:1
            req_filter = Filter().kind(1).limit(1)

            # Wait for response with timeout
            await client.fetch_events(req_filter, timedelta(seconds=connection_timeout))

            # If we got here without error, the relay is valid
            # (even if no events returned, it means it speaks Nostr)
            return (url, True, failed_attempts)

        finally:
            await client.disconnect()

    except Exception:
        return (url, False, failed_attempts)


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

    async def run(self) -> None:
        """Run single validation cycle."""
        cycle_start = time.time()
        self._validated_count = 0
        self._failed_count = 0

        # Step 1: Remove candidates that already exist in relays table
        removed = await self._cleanup_existing_candidates()
        if removed > 0:
            self._logger.info("stale_candidates_removed", count=removed)

        # Step 2: Remove candidates that exceeded max attempts (if enabled)
        if self._config.cleanup.enabled:
            deleted = await self._cleanup_failed_candidates()
            if deleted > 0:
                self._logger.info("failed_candidates_deleted", count=deleted)

        # Step 3: Fetch candidates ordered by failed_attempts ASC
        candidates = await self._fetch_candidates()

        if not candidates:
            self._logger.info("no_candidates_to_validate")
            return

        self._logger.info("validation_started", selected=len(candidates))

        # Convert candidates to Relay objects with failed_attempts
        relays_to_validate: list[tuple[Relay, int]] = []
        for candidate in candidates:
            try:
                relay = Relay(candidate["key"])
                failed_attempts = candidate["value"].get("failed_attempts", 0)
                relays_to_validate.append((relay, failed_attempts))
            except Exception as e:
                self._logger.warning(
                    "parse_candidate_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    url=candidate["key"],
                )

        if not relays_to_validate:
            self._logger.info("no_valid_candidates")
            return

        # Run validation (single or multiprocess)
        if self._config.concurrency.max_processes > 1:
            results = await self._run_multiprocess(relays_to_validate)
        else:
            results = await self._run_single_process(relays_to_validate)

        # Process results and collect batch operations
        valid_relays: list[Relay] = []
        delete_keys: list[str] = []
        retry_records: list[tuple[str, int]] = []

        for url, is_valid, failed_attempts in results:
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

        # Execute batch database operations in chunks
        batch_size = self._brotr.config.batch.max_batch_size

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
                key_chunk = delete_keys[i : i + batch_size]
                try:
                    delete_records = [("validator", "candidate", key) for key in key_chunk]
                    await self._brotr.delete_service_data(delete_records)
                except Exception as e:
                    self._logger.error(
                        "delete_candidates_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        count=len(key_chunk),
                    )

        if retry_records:
            for i in range(0, len(retry_records), batch_size):
                retry_chunk = retry_records[i : i + batch_size]
                try:
                    upsert_records = [
                        ("validator", "candidate", rec_url, {"failed_attempts": rec_attempts})
                        for rec_url, rec_attempts in retry_chunk
                    ]
                    await self._brotr.upsert_service_data(upsert_records)
                except Exception as e:
                    self._logger.error(
                        "upsert_retries_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        count=len(retry_chunk),
                    )

        elapsed = time.time() - cycle_start
        self._logger.info(
            "cycle_completed",
            validated=self._validated_count,
            failed=self._failed_count,
            duration=round(elapsed, 2),
        )

    async def _run_single_process(
        self, relays: list[tuple[Relay, int]]
    ) -> list[tuple[str, bool, int]]:
        """Run validation in single process using asyncio concurrency."""
        semaphore = asyncio.Semaphore(self._config.concurrency.tasks_per_process)
        tasks = [
            self._validate_relay(relay, failed_attempts, semaphore)
            for relay, failed_attempts in relays
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions
        valid_results: list[tuple[str, bool, int]] = []
        for result in results:
            if isinstance(result, (Exception, BaseException)):
                continue
            if result is not None:
                valid_results.append(result)

        return valid_results

    async def _run_multiprocess(
        self, relays: list[tuple[Relay, int]]
    ) -> list[tuple[str, bool, int]]:
        """Run validation using aiomultiprocess Pool."""
        # Prepare task arguments
        config_dump = self._config.model_dump()
        tasks = [
            (relay.url, relay.network.value, failed_attempts, config_dump)
            for relay, failed_attempts in relays
        ]

        async with aiomultiprocess.Pool(
            processes=self._config.concurrency.max_processes,
            childconcurrency=self._config.concurrency.tasks_per_process,
        ) as pool:
            results = await pool.starmap(validate_relay_task, tasks)

        return list(results)

    async def _validate_relay(
        self, relay: Relay, failed_attempts: int, semaphore: asyncio.Semaphore
    ) -> tuple[str, bool, int]:
        """
        Validate a single relay.

        Args:
            relay: Relay object to validate
            failed_attempts: Current number of failed attempts
            semaphore: Semaphore for concurrency control

        Returns:
            Tuple of (url, is_valid, failed_attempts) for batch processing.
        """
        async with semaphore:
            is_valid = await self._test_connection(relay)

            if is_valid:
                self._logger.debug("candidate_validated", url=relay.url)
            else:
                self._logger.debug(
                    "candidate_failed", url=relay.url, failed_attempts=failed_attempts + 1
                )

            return (relay.url, is_valid, failed_attempts)

    async def _cleanup_existing_candidates(self) -> int:
        """
        Delete candidates whose URL already exists in relays table.

        This ensures data consistency - if a relay was added by another process
        (e.g., seeder with to_validate=False), we clean up the stale candidate.

        Returns number of candidates deleted.
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
        # Result format: "DELETE N"
        return int(result.split()[-1]) if result else 0

    async def _cleanup_failed_candidates(self) -> int:
        """
        Delete candidates that exceeded max validation attempts.

        Returns number of candidates deleted.
        """
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
        # Result format: "DELETE N"
        return int(result.split()[-1]) if result else 0

    async def _fetch_candidates(self) -> list[dict[str, Any]]:
        """
        Fetch candidates ordered by failed_attempts ASC, with optional limit.

        Candidates with fewer failed attempts are prioritized for validation.
        Filters out candidates from disabled networks.

        Returns list of candidate records with keys: key, value, updated_at.
        """
        limit = self._config.validation.max_candidates_per_run

        # Build WHERE conditions for enabled networks
        # Overlay networks are identified by suffix, clearnet is everything else
        conditions: list[str] = []

        if self._config.network.clearnet.enabled:
            # Clearnet = NOT any overlay suffix
            conditions.append(
                "(data_key NOT LIKE '%.onion%' AND data_key NOT LIKE '%.i2p%' AND data_key NOT LIKE '%.loki%')"
            )
        if self._config.network.tor.enabled:
            conditions.append("data_key LIKE '%.onion%'")
        if self._config.network.i2p.enabled:
            conditions.append("data_key LIKE '%.i2p%'")
        if self._config.network.loki.enabled:
            conditions.append("data_key LIKE '%.loki%'")

        # If no networks enabled, return empty list
        if not conditions:
            return []

        network_filter = "(" + " OR ".join(conditions) + ")"

        query = f"""
            SELECT data_key, data, updated_at
            FROM service_data
            WHERE service_name = 'validator'
              AND data_type = 'candidate'
              AND {network_filter}
            ORDER BY COALESCE((data->>'failed_attempts')::int, 0) ASC
        """

        if limit is not None:
            query += f" LIMIT {limit}"

        rows = await self._brotr.pool.fetch(
            query,
            timeout=self._brotr.config.timeouts.query,
        )

        return [
            {"key": row["data_key"], "value": row["data"], "updated_at": row["updated_at"]}
            for row in rows
        ]

    async def _test_connection(self, relay: Relay) -> bool:
        """
        Validate relay by sending a REQ and checking for valid response.

        A relay is considered valid if it responds to a REQ without error.

        Args:
            relay: Relay object to test

        Returns:
            True if relay speaks Nostr protocol, False otherwise.
        """
        from nostr_sdk import Filter  # noqa: PLC0415

        from utils.transport import connect_relay  # noqa: PLC0415

        try:
            # Get proxy URL for overlay networks (clearnet returns None)
            proxy_url = self._config.network.get_proxy_url(relay.network)
            timeout = self._config.validation.connection_timeout

            # Connect to relay using transport helper
            client = await connect_relay(
                relay=relay,
                proxy_url=proxy_url,
                timeout=timeout,
            )

            try:
                # Send REQ for kind:1 limit:1 and wait for response
                req_filter = Filter().kind(1).limit(1)
                await client.fetch_events(req_filter, timedelta(seconds=timeout))

                # If we got here without error, the relay is valid
                return True

            finally:
                await client.disconnect()

        except Exception:
            return False
