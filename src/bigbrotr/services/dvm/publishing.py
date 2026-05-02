"""Helpers for DVM event publishing and announcements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from bigbrotr.utils.protocol import normalize_send_output

from .utils import build_announcement_event


if TYPE_CHECKING:
    from bigbrotr.core.logger import Logger


@dataclass(frozen=True, slots=True)
class AnnouncementContext:
    """Parameters required to build one DVM announcement event."""

    d_tag: str
    kind: int
    name: str
    about: str
    read_models: list[str]


async def send_event(
    *,
    client: Any | None,
    builder: Any,
    require_success: bool = False,
) -> tuple[tuple[str, ...], dict[str, str]]:
    """Sign and send one event through the connected DVM client."""
    if client is None:
        return (), {}

    output = await client.send_event_builder(builder)
    successful_relays, failed_relays = normalize_send_output(output)

    if require_success and not successful_relays:
        raise OSError("event was not accepted by any relay")

    return successful_relays, failed_relays


async def publish_announcement(
    *,
    client: Any | None,
    logger: Logger,
    context: AnnouncementContext,
) -> None:
    """Publish one NIP-89 handler announcement if a client is connected."""
    if client is None:
        return

    builder = build_announcement_event(
        d_tag=context.d_tag,
        kind=context.kind,
        name=context.name,
        about=context.about,
        read_models=context.read_models,
    )
    successful_relays, failed_relays = await send_event(client=client, builder=builder)
    if successful_relays:
        logger.info(
            "announcement_published",
            kind=31990,
            relays=len(successful_relays),
        )
        return

    logger.warning(
        "announcement_publish_failed",
        kind=31990,
        error="no relays accepted announcement",
        failed_relays=failed_relays,
    )
