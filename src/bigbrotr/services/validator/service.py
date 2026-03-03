"""Validator service for BigBrotr.

Validates relay candidates discovered by the
[Finder][bigbrotr.services.finder.Finder] service by checking whether
they speak the Nostr protocol via WebSocket. Valid candidates are promoted
to the relays table; invalid ones have their failure counter incremented
and are retried in future cycles.

Validation criteria: a candidate is valid if it accepts a WebSocket
connection and responds to a Nostr REQ message with EOSE, EVENT, NOTICE,
or AUTH, as determined by
[is_nostr_relay][bigbrotr.utils.protocol.is_nostr_relay].

Note:
    Each cycle initializes per-network semaphores from
    [NetworksConfig][bigbrotr.services.common.configs.NetworksConfig],
    cleans up stale/exhausted candidates, then processes remaining
    candidates in configurable chunks. CandidateCheckpoint priority is ordered by
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
    [is_nostr_relay][bigbrotr.utils.protocol.is_nostr_relay]: WebSocket
        probe function used for validation.
    [promote_candidates][bigbrotr.services.common.queries.promote_candidates]:
        Insert+delete for promotion (with cleanup safety net).

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
from typing import TYPE_CHECKING, ClassVar

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.relay import Relay
from bigbrotr.services.common.mixins import NetworkSemaphoresMixin
from bigbrotr.utils.protocol import is_nostr_relay

from .configs import ValidatorConfig
from .queries import (
    count_candidates,
    delete_exhausted_candidates,
    delete_promoted_candidates,
    fail_candidates,
    fetch_candidates,
    promote_candidates,
)


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models.constants import NetworkType
    from bigbrotr.services.common.types import CandidateCheckpoint


class Validator(NetworkSemaphoresMixin, BaseService[ValidatorConfig]):
    """Validates relay candidates by checking if they speak the Nostr protocol.

    Processes candidate URLs discovered by the
    [Finder][bigbrotr.services.finder.Finder] service. Valid relays are
    promoted to the relays table via
    [promote_candidates][bigbrotr.services.common.queries.promote_candidates];
    invalid ones have their failure counter incremented for retry in
    future cycles.

    Each cycle initializes per-network semaphores via
    [NetworkSemaphoresMixin][bigbrotr.services.common.mixins.NetworkSemaphoresMixin],
    cleans up stale/exhausted candidates, then processes remaining
    candidates in configurable chunks. Supports clearnet (direct),
    Tor (.onion via SOCKS5), I2P (.i2p via SOCKS5), and Lokinet
    (.loki via SOCKS5).

    See Also:
        [ValidatorConfig][bigbrotr.services.validator.ValidatorConfig]:
            Configuration model for this service.
        [Finder][bigbrotr.services.finder.Finder]: Upstream service that
            creates the candidates validated here.
        [Monitor][bigbrotr.services.monitor.Monitor]: Downstream service
            that health-checks promoted relays.
        [is_nostr_relay][bigbrotr.utils.protocol.is_nostr_relay]:
            WebSocket probe used by ``_validate_candidate()``.
    """

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.VALIDATOR
    CONFIG_CLASS: ClassVar[type[ValidatorConfig]] = ValidatorConfig

    def __init__(self, brotr: Brotr, config: ValidatorConfig | None = None) -> None:
        config = config or ValidatorConfig()
        super().__init__(brotr=brotr, config=config, networks=config.networks)
        self._config: ValidatorConfig

    async def run(self) -> None:
        """Execute one complete validation cycle."""
        await self.validate()

    async def cleanup(self) -> int:
        """Remove promoted candidates and exhausted candidates."""
        removed = await delete_promoted_candidates(self._brotr)
        if self._config.cleanup.enabled:
            removed += await delete_exhausted_candidates(
                self._brotr, self._config.cleanup.max_failures
            )
        return removed

    async def validate(self) -> int:
        """Validate all pending candidates and persist results.

        Returns:
            Total number of candidates processed (valid + invalid).
        """
        networks = self._config.networks.get_enabled_networks()
        if not networks:
            self._logger.warning("no_networks_enabled")
            return 0

        attempted_before = int(time.time() - self._config.processing.interval)

        total = await count_candidates(self._brotr, networks, attempted_before)
        self._logger.info("candidates_available", total=total)

        self.set_gauge("total", total)
        self.set_gauge("validated", 0)
        self.set_gauge("not_validated", 0)
        self.set_gauge("chunk", 0)

        processed = 0
        cumulative_promoted = 0
        cumulative_failed = 0
        chunk_num = 0

        async for valid, invalid in self._validate_chunks(networks, attempted_before):
            failed_count = await fail_candidates(self._brotr, invalid)
            promoted_count = await promote_candidates(self._brotr, valid)

            processed += len(valid) + len(invalid)
            cumulative_promoted += promoted_count
            cumulative_failed += failed_count
            chunk_num += 1

            self.inc_counter("total_promoted", promoted_count)
            self.set_gauge("validated", cumulative_promoted)
            self.set_gauge("not_validated", cumulative_failed)
            self.set_gauge("chunk", chunk_num)

            self._logger.info(
                "chunk_completed",
                chunk=chunk_num,
                promoted=promoted_count,
                failed=failed_count,
                remaining=total - processed,
            )

        return processed

    async def _validate_candidate(self, candidate: CandidateCheckpoint) -> bool:
        """Validate a single relay candidate by connecting and testing the Nostr protocol.

        Uses the network-specific semaphore and proxy settings from
        [NetworksConfig][bigbrotr.services.common.configs.NetworksConfig].
        Delegates the actual WebSocket probe to
        [is_nostr_relay][bigbrotr.utils.protocol.is_nostr_relay].

        Args:
            candidate: [CandidateCheckpoint][bigbrotr.services.common.types.CandidateCheckpoint]
                to validate.

        Returns:
            ``True`` if the relay speaks Nostr protocol, ``False`` otherwise.
        """
        network = candidate.network
        semaphore = self.network_semaphores.get(network)

        if semaphore is None:
            self._logger.warning("unknown_network", url=candidate.key, network=network.value)
            return False

        async with semaphore:
            network_config = self._config.networks.get(network)
            proxy_url = self._config.networks.get_proxy_url(network)
            try:
                relay = Relay(candidate.key)
                return await is_nostr_relay(relay, proxy_url, network_config.timeout)
            except (TimeoutError, OSError):
                return False

    async def _validate_chunks(
        self,
        networks: list[NetworkType],
        attempted_before: int,
    ) -> AsyncIterator[tuple[list[CandidateCheckpoint], list[CandidateCheckpoint]]]:
        """Fetch, validate, and yield candidate chunks.

        Handles chunk fetching, budget calculation, and concurrent validation.
        Persistence is left to the caller.

        Args:
            networks: Enabled network types to process.
            attempted_before: Unix timestamp cutoff for candidate retry interval.

        Yields:
            Tuple of (valid CandidateCheckpoint list, invalid CandidateCheckpoint list) per chunk.
        """
        chunk_size = self._config.processing.chunk_size
        max_candidates = self._config.processing.max_candidates
        processed = 0

        while self.is_running:
            if max_candidates is not None:
                budget = max_candidates - processed
                if budget <= 0:
                    break
                limit = min(chunk_size, budget)
            else:
                limit = chunk_size

            candidates = await fetch_candidates(self._brotr, networks, attempted_before, limit)
            if not candidates:
                break

            tasks = [self._validate_candidate(c) for c in candidates]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            valid: list[CandidateCheckpoint] = []
            invalid: list[CandidateCheckpoint] = []

            for candidate, result in zip(candidates, results, strict=True):
                if isinstance(result, asyncio.CancelledError):
                    raise result
                if isinstance(result, BaseException):
                    self._logger.warning(
                        "validate_unexpected_error",
                        url=candidate.key,
                        error=str(result),
                    )
                    invalid.append(candidate)
                elif result is True:
                    valid.append(candidate)
                else:
                    invalid.append(candidate)

            processed += len(valid) + len(invalid)
            yield valid, invalid
