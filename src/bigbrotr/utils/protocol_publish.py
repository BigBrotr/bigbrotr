"""Helpers for publishing Nostr events through pre-connected clients.

This module contains the relay-level normalization used by services that
publish through shared nostr-sdk clients. It is intentionally kept free of
client-construction concerns so the public protocol facade can re-export it
without dragging the whole connection stack into publishing-specific code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from nostr_sdk import Client, EventBuilder


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BroadcastClientResult:
    """Normalized per-client outcome of publishing one or more events."""

    event_ids: tuple[str, ...]
    successful_relays: tuple[str, ...]
    failed_relays: dict[str, str]


async def broadcast_events(
    builders: list[EventBuilder],
    clients: list[Client],
) -> int:
    """Broadcast Nostr events to pre-connected clients.

    Each client must already be connected and configured with a signer.
    The caller is responsible for creating, connecting, and shutting down
    the clients.

    Args:
        builders: Event builders to sign and send.
        clients: Pre-connected ``Client`` instances.

    Returns:
        Number of clients that successfully received all events.
    """
    detailed_results = await broadcast_events_detailed(builders, clients)
    return sum(1 for result in detailed_results if result.successful_relays)


async def broadcast_events_detailed(
    builders: list[EventBuilder],
    clients: list[Client],
) -> list[BroadcastClientResult]:
    """Broadcast events and preserve the per-relay send semantics from nostr-sdk."""
    if not builders or not clients:
        return []

    results: list[BroadcastClientResult] = []
    for client in clients:
        try:
            event_ids: list[str] = []
            successful_relays: set[str] | None = None
            failed_relays: dict[str, str] = {}

            for builder in builders:
                output = await client.send_event_builder(builder)
                event_ids.append(str(getattr(output, "id", "")))

                builder_success = {str(relay_url) for relay_url in getattr(output, "success", ())}
                builder_failed = {
                    str(relay_url): str(error)
                    for relay_url, error in getattr(output, "failed", {}).items()
                }

                if successful_relays is None:
                    successful_relays = set(builder_success)
                else:
                    successful_relays.intersection_update(builder_success)
                failed_relays.update(builder_failed)

            results.append(
                BroadcastClientResult(
                    event_ids=tuple(event_ids),
                    successful_relays=tuple(sorted(successful_relays or ())),
                    failed_relays=failed_relays,
                )
            )
        except (OSError, TimeoutError) as e:
            logger.warning("broadcast_send_failed error=%s", e)

    return results


def summarize_broadcast_results(
    results: list[BroadcastClientResult],
) -> tuple[tuple[str, ...], dict[str, str]]:
    """Collapse detailed per-client publish results into relay-level outcomes."""
    successful_relays = tuple(
        sorted({relay_url for result in results for relay_url in result.successful_relays})
    )
    failed_relays: dict[str, str] = {}
    for result in results:
        failed_relays.update(result.failed_relays)
    return successful_relays, failed_relays


def normalize_send_output(output: object) -> tuple[tuple[str, ...], dict[str, str]]:
    """Normalize one nostr-sdk send/subscribe output into relay-level outcomes."""
    successful_relays = tuple(str(relay_url) for relay_url in getattr(output, "success", ()))
    failed_relays = {
        str(relay_url): str(error) for relay_url, error in getattr(output, "failed", {}).items()
    }
    return successful_relays, failed_relays
