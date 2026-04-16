"""Publishing coordination for the monitor service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bigbrotr.models import Relay
from bigbrotr.models.constants import NetworkType
from bigbrotr.nips.nip11 import Nip11, Nip11Selection
from bigbrotr.nips.nip66 import Nip66, Nip66Selection
from bigbrotr.utils.protocol import summarize_broadcast_results


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nostr_sdk import Client, EventBuilder

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.core.logger import Logger
    from bigbrotr.models import Relay
    from bigbrotr.utils.protocol import BroadcastClientResult, NostrClientManager

    from .configs import MonitorConfig
    from .utils import CheckResult


@dataclass(frozen=True, slots=True)
class PublishContext:
    """Shared dependencies for monitor publish flows."""

    brotr: Brotr
    config: MonitorConfig
    clients: NostrClientManager
    logger: Logger
    is_due: Callable[[Brotr, str, float], Awaitable[bool]]
    broadcast: Callable[[list[EventBuilder], list[Client]], Awaitable[list[BroadcastClientResult]]]
    save_checkpoints: Callable[[Brotr, list[str]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class DiscoveryContext:
    """Dependencies for per-relay discovery publishing."""

    config: MonitorConfig
    clients: NostrClientManager
    logger: Logger
    broadcast: Callable[[list[EventBuilder], list[Client]], Awaitable[list[BroadcastClientResult]]]


async def publish_profile(
    *,
    context: PublishContext,
    build_profile: Callable[..., EventBuilder],
) -> None:
    """Publish Kind 0 profile metadata when due."""
    cfg = context.config.profile
    if not cfg.enabled:
        return

    relays = cfg.relays if cfg.relays is not None else context.config.publishing.relays
    if not relays or not await context.is_due(context.brotr, "profile", cfg.interval):
        return

    connected_clients = await context.clients.get_relay_clients(relays)
    if not connected_clients:
        context.logger.warning("publish_failed", event="profile", error="no relays reachable")
        return

    successful_relays, failed_relays = summarize_broadcast_results(
        await context.broadcast(
            [
                build_profile(
                    name=cfg.name,
                    about=cfg.about,
                    picture=cfg.picture,
                    nip05=cfg.nip05,
                    website=cfg.website,
                    banner=cfg.banner,
                    lud16=cfg.lud16,
                )
            ],
            connected_clients,
        )
    )
    if not successful_relays:
        context.logger.warning(
            "publish_failed",
            event="profile",
            error="no relays accepted event",
            failed_relays=failed_relays,
        )
        return

    context.logger.info(
        "publish_completed",
        event="profile",
        relays=len(successful_relays),
        failed_relays=len(failed_relays),
    )
    await context.save_checkpoints(context.brotr, ["profile"])


async def publish_relay_list(
    *,
    context: PublishContext,
    build_relay_list: Callable[[list[Relay]], EventBuilder],
) -> None:
    """Publish Kind 10002 relay list metadata when due."""
    cfg = context.config.relay_list
    if not cfg.enabled:
        return

    relays = cfg.relays if cfg.relays is not None else context.config.publishing.relays
    if not relays or not await context.is_due(context.brotr, "relay_list", cfg.interval):
        return

    connected_clients = await context.clients.get_relay_clients(relays)
    if not connected_clients:
        context.logger.warning(
            "publish_failed",
            event="relay_list",
            error="no relays reachable",
        )
        return

    successful_relays, failed_relays = summarize_broadcast_results(
        await context.broadcast([build_relay_list(relays)], connected_clients)
    )
    if not successful_relays:
        context.logger.warning(
            "publish_failed",
            event="relay_list",
            error="no relays accepted event",
            failed_relays=failed_relays,
        )
        return

    context.logger.info(
        "publish_completed",
        event="relay_list",
        relays=len(successful_relays),
        failed_relays=len(failed_relays),
    )
    await context.save_checkpoints(context.brotr, ["relay_list"])


async def publish_announcement(
    *,
    context: PublishContext,
    build_announcement: Callable[..., EventBuilder],
) -> None:
    """Publish Kind 10166 monitor announcement when due."""
    cfg = context.config.announcement
    if not cfg.enabled:
        return

    relays = cfg.relays if cfg.relays is not None else context.config.publishing.relays
    if not relays or not await context.is_due(context.brotr, "announcement", cfg.interval):
        return

    include = cfg.include
    enabled_networks = context.config.networks.get_enabled_networks()
    first_network = enabled_networks[0] if enabled_networks else NetworkType.CLEARNET
    timeout_ms = int(context.config.networks.get(first_network).timeout * 1000)

    connected_clients = await context.clients.get_relay_clients(relays)
    if not connected_clients:
        context.logger.warning(
            "publish_failed",
            event="announcement",
            error="no relays reachable",
        )
        return

    successful_relays, failed_relays = summarize_broadcast_results(
        await context.broadcast(
            [
                build_announcement(
                    interval=int(context.config.discovery.interval),
                    timeout_ms=timeout_ms,
                    enabled_networks=enabled_networks,
                    nip11_selection=Nip11Selection(info=include.nip11_info),
                    nip66_selection=Nip66Selection(
                        rtt=include.nip66_rtt,
                        ssl=include.nip66_ssl,
                        geo=include.nip66_geo,
                        net=include.nip66_net,
                        dns=include.nip66_dns,
                        http=include.nip66_http,
                    ),
                    geohash=cfg.geohash,
                )
            ],
            connected_clients,
        )
    )
    if not successful_relays:
        context.logger.warning(
            "publish_failed",
            event="announcement",
            error="no relays accepted event",
            failed_relays=failed_relays,
        )
        return

    context.logger.info(
        "publish_completed",
        event="announcement",
        relays=len(successful_relays),
        failed_relays=len(failed_relays),
    )
    await context.save_checkpoints(context.brotr, ["announcement"])


async def publish_discovery(
    *,
    context: DiscoveryContext,
    relay: Relay,
    result: CheckResult,
    build_discovery: Callable[[Relay, Nip11, Nip66], EventBuilder],
) -> None:
    """Publish a Kind 30166 discovery event for one successfully checked relay."""
    cfg = context.config.discovery
    if not cfg.enabled:
        return

    relays = cfg.relays if cfg.relays is not None else context.config.publishing.relays
    if not relays:
        return

    connected_clients = await context.clients.get_relay_clients(relays)
    if not connected_clients:
        return

    include = cfg.include
    try:
        nip11 = Nip11(
            relay=relay,
            info=result.nip11_info if include.nip11_info else None,
        )
        nip66 = Nip66(
            relay=relay,
            rtt=result.nip66_rtt if include.nip66_rtt else None,
            ssl=result.nip66_ssl if include.nip66_ssl else None,
            geo=result.nip66_geo if include.nip66_geo else None,
            net=result.nip66_net if include.nip66_net else None,
            dns=result.nip66_dns if include.nip66_dns else None,
            http=result.nip66_http if include.nip66_http else None,
        )
        builder = build_discovery(relay, nip11, nip66)
    except (ValueError, KeyError, TypeError) as e:
        context.logger.debug("build_30166_failed", url=relay.url, error=str(e))
        return

    successful_relays, failed_relays = summarize_broadcast_results(
        await context.broadcast([builder], connected_clients)
    )
    if not successful_relays:
        context.logger.debug(
            "discovery_broadcast_failed",
            url=relay.url,
            failed_relays=failed_relays,
        )
