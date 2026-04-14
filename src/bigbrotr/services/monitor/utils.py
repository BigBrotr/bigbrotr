"""Monitor service utility functions.

Pure helpers for health check result inspection, chunk classification,
and retry logic.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NamedTuple, TypeVar

from bigbrotr.models import Metadata, MetadataType, RelayMetadata


if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from bigbrotr.models import Relay
    from bigbrotr.nips.base import BaseNipMetadata
    from bigbrotr.nips.nip11.info import Nip11InfoMetadata
    from bigbrotr.nips.nip66 import (
        Nip66DnsMetadata,
        Nip66GeoMetadata,
        Nip66HttpMetadata,
        Nip66NetMetadata,
        Nip66RttMetadata,
        Nip66SslMetadata,
    )
    from bigbrotr.services.monitor.configs import MetadataFlags, RetryConfig


_T = TypeVar("_T")
logger = logging.getLogger(__name__)


class CheckResult(NamedTuple):
    """Result of a single relay health check.

    Each field contains the typed NIP metadata container if that check was run
    and produced data, or ``None`` if the check was skipped (disabled in config)
    or failed completely. Use ``has_data`` to test whether any check produced
    results.

    Attributes:
        generated_at: Unix timestamp when the health check was performed.
        nip11_info: NIP-11 relay information document (name, description, pubkey, etc.).
        nip66_rtt: Round-trip times for open/read/write operations in milliseconds.
        nip66_ssl: SSL certificate validation (valid, expiry timestamp, issuer).
        nip66_geo: Geolocation data (country, city, coordinates, timezone, geohash).
        nip66_net: Network information (IP address, ASN, organization).
        nip66_dns: DNS resolution data (IPs, CNAME, nameservers, reverse DNS).
        nip66_http: HTTP metadata (server software and framework headers).

    See Also:
        [MetadataFlags][bigbrotr.services.monitor.MetadataFlags]: Boolean
            flags controlling which check types are computed and stored.
    """

    generated_at: int = 0
    nip11_info: Nip11InfoMetadata | None = None
    nip66_rtt: Nip66RttMetadata | None = None
    nip66_ssl: Nip66SslMetadata | None = None
    nip66_geo: Nip66GeoMetadata | None = None
    nip66_net: Nip66NetMetadata | None = None
    nip66_dns: Nip66DnsMetadata | None = None
    nip66_http: Nip66HttpMetadata | None = None

    @property
    def has_data(self) -> bool:
        """True if at least one NIP check produced data."""
        return any(
            (
                self.nip11_info,
                self.nip66_rtt,
                self.nip66_ssl,
                self.nip66_geo,
                self.nip66_net,
                self.nip66_dns,
                self.nip66_http,
            )
        )


@dataclass(frozen=True, slots=True)
class MonitorChunkOutcome:
    """Classification result for one processed monitor chunk."""

    successful: tuple[tuple[Relay, CheckResult], ...] = ()
    failed: tuple[Relay, ...] = ()

    @property
    def succeeded_count(self) -> int:
        """Number of relays that produced at least one metadata document."""
        return len(self.successful)

    @property
    def failed_count(self) -> int:
        """Number of relays that produced no usable monitoring data."""
        return len(self.failed)

    @property
    def checked_relays(self) -> tuple[Relay, ...]:
        """All relays classified in this chunk, successful first then failed."""
        return tuple(relay for relay, _ in self.successful) + self.failed


def log_success(result: Any) -> bool:
    """Extract semantic success status from a metadata result."""
    success = getattr(result, "succeeded", None)
    if isinstance(success, bool):
        return success

    logs = getattr(result, "logs", None)
    success = getattr(logs, "succeeded", None)
    return success if isinstance(success, bool) else False


def log_reason(result: Any) -> str | None:
    """Extract a semantic failure reason from a metadata result."""
    reason = getattr(result, "failure_reason", None)
    if isinstance(reason, str):
        return reason

    logs = getattr(result, "logs", None)
    reason = getattr(logs, "failure_reason", None)
    return reason if isinstance(reason, str) else None


def extract_result(results: dict[str, Any], key: str) -> Any:
    """Extract a successful result from asyncio.gather output.

    Returns None if the key is absent or the result is an exception.
    """
    value = results.get(key)
    if value is None or isinstance(value, BaseException):
        return None
    return value


def collect_metadata(
    successful: list[tuple[Relay, CheckResult]],
    store: MetadataFlags,
) -> list[RelayMetadata]:
    """Build storable metadata records from successful health check results.

    Iterates over successful relay/result pairs and collects metadata for
    each check type enabled in ``store``. Field names in ``CheckResult``,
    ``MetadataFlags``, and ``MetadataType`` are aligned by convention
    (e.g. ``nip11_info``, ``nip66_rtt``).

    Args:
        successful: Relays with their health check results.
        store: Flags controlling which metadata types to include.

    Returns:
        List of [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]
        ready for batch insertion.
    """
    metadata: list[RelayMetadata] = []
    for relay, result in successful:
        for meta_type in MetadataType:
            field = meta_type.value
            nip_meta: BaseNipMetadata | None = getattr(result, field)
            if nip_meta and getattr(store, field):
                metadata.append(
                    RelayMetadata(
                        relay=relay,
                        metadata=Metadata(type=meta_type, data=nip_meta.to_dict()),
                        generated_at=result.generated_at,
                    )
                )
    return metadata


async def retry_fetch(
    relay: Relay,
    coro_factory: Callable[[], Coroutine[Any, Any, _T]],
    retry: RetryConfig,
    operation: str,
    wait: Callable[[float], Coroutine[Any, Any, bool]] | None = None,
) -> _T | None:
    """Execute a metadata fetch with exponential backoff retry.

    Retries on network failures up to ``retry.max_attempts`` times.
    Returns the result (possibly with ``success=False``) or ``None`` on
    exception.

    Args:
        relay: Target relay (used for logging context).
        coro_factory: Factory producing a fresh coroutine per attempt.
        retry: Backoff configuration (max attempts, delays, jitter).
        operation: Check name for log messages (e.g. ``"nip11_info"``).
        wait: Optional shutdown-aware sleep. Receives delay in seconds,
            returns ``True`` if shutdown was requested. When ``None``,
            falls back to ``asyncio.sleep``.

    Note:
        The ``coro_factory`` pattern (a callable returning a coroutine)
        is required because Python coroutines are single-use: once
        awaited, they cannot be re-awaited. The factory creates a fresh
        coroutine for each retry attempt.

    Warning:
        Jitter is computed via ``random.uniform()`` (PRNG, ``# noqa: S311``).
        This is intentional -- jitter only needs to decorrelate
        concurrent retries, not provide cryptographic randomness.
    """
    max_retries = retry.max_attempts
    result = None

    for attempt in range(max_retries + 1):
        try:
            result = await coro_factory()
            if log_success(result):
                return result
        except (TimeoutError, OSError) as e:
            logger.debug(
                "check_error",
                extra={
                    "operation": operation,
                    "relay": relay.url,
                    "attempt": attempt + 1,
                    "error": str(e),
                },
            )
            result = None

        # Network failure - retry if attempts remaining
        if attempt < max_retries:
            delay = min(retry.initial_delay * (2**attempt), retry.max_delay)
            jitter = random.uniform(0, retry.jitter)  # noqa: S311
            total_delay = delay + jitter
            if wait is not None:
                if await wait(total_delay):
                    return None
            else:
                await asyncio.sleep(total_delay)
            logger.debug(
                "check_retry",
                extra={
                    "operation": operation,
                    "relay": relay.url,
                    "attempt": attempt + 1,
                    "reason": log_reason(result) if result else None,
                    "delay_s": round(total_delay, 2),
                },
            )

    # All retries exhausted
    logger.debug(
        "check_exhausted",
        extra={
            "operation": operation,
            "relay": relay.url,
            "total_attempts": max_retries + 1,
            "reason": log_reason(result) if result else None,
        },
    )
    return result
