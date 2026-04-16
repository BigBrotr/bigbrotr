"""Relay-validation helpers built on top of the public protocol facade."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from nostr_sdk import Filter, Kind, KindStandard


if TYPE_CHECKING:
    import logging
    from collections.abc import Awaitable, Callable
    from contextlib import AbstractContextManager

    from nostr_sdk import Client

    from bigbrotr.models.relay import Relay


@dataclass(frozen=True, slots=True)
class RelayValidationContext:
    """Runtime dependencies used to validate one relay."""

    connect_relay: Callable[..., Awaitable[Client]]
    shutdown_client: Callable[[Client], Awaitable[None]]
    suppress_stderr: Callable[[], AbstractContextManager[object]]
    logger: logging.Logger


@dataclass(frozen=True, slots=True)
class RelayValidationOptions:
    """Policy and timeout settings used while validating one relay."""

    connect_timeout: float
    proxy_url: str | None = None
    overall_timeout: float | None = None
    allow_insecure: bool = False


async def validate_relay_protocol(
    relay: Relay,
    context: RelayValidationContext,
    options: RelayValidationOptions,
) -> bool:
    """Check whether one relay speaks Nostr by completing a basic fetch flow."""
    effective_overall = (
        options.overall_timeout
        if options.overall_timeout is not None
        else options.connect_timeout * 4
    )

    context.logger.debug(
        "validation_started relay=%s timeout_s=%s",
        relay.url,
        options.connect_timeout,
    )

    with context.suppress_stderr():
        client = None
        try:
            async with asyncio.timeout(effective_overall):
                client = await context.connect_relay(
                    relay=relay,
                    proxy_url=options.proxy_url,
                    timeout=options.connect_timeout,
                    allow_insecure=options.allow_insecure,
                )

                req_filter = Filter().kind(Kind.from_std(KindStandard.TEXT_NOTE)).limit(1)
                await client.fetch_events(req_filter, timedelta(seconds=options.connect_timeout))
                context.logger.debug("validation_success relay=%s reason=%s", relay.url, "eose")
                return True

        except TimeoutError:
            context.logger.debug("validation_timeout relay=%s", relay.url)
            return False

        except OSError as exc:
            error_msg = str(exc).lower()
            if "auth-required" in error_msg:
                context.logger.debug(
                    "validation_success relay=%s reason=%s",
                    relay.url,
                    "auth-required",
                )
                return True
            context.logger.debug("validation_failed relay=%s error=%s", relay.url, str(exc))
            return False

        finally:
            if client is not None:
                try:
                    await asyncio.wait_for(
                        context.shutdown_client(client),
                        timeout=options.connect_timeout,
                    )
                except (OSError, RuntimeError, TimeoutError) as exc:
                    context.logger.debug("client_shutdown_error error=%s", exc)
