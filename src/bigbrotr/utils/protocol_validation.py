"""Relay-validation helpers built on top of the public protocol facade."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from nostr_sdk import Filter, Kind, KindStandard, NostrSdkError


if TYPE_CHECKING:
    import logging
    from collections.abc import Awaitable, Callable
    from contextlib import AbstractContextManager

    from nostr_sdk import Client

    from bigbrotr.models.relay import Relay


def _normalize_timeout_budget(timeout: object, field_name: str) -> float:
    """Return one canonical positive finite timeout budget."""
    if isinstance(timeout, bool) or not isinstance(timeout, int | float):
        raise ValueError(f"{field_name} must be a positive finite number")
    normalized = float(timeout)
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError(f"{field_name} must be a positive finite number")
    return normalized


def _normalize_allow_insecure(allow_insecure: object) -> bool:
    """Return one canonical insecure-transport toggle."""
    if not isinstance(allow_insecure, bool):
        raise ValueError("allow_insecure must be a bool")
    return allow_insecure


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

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "connect_timeout",
            _normalize_timeout_budget(self.connect_timeout, "connect_timeout"),
        )
        if self.overall_timeout is not None:
            object.__setattr__(
                self,
                "overall_timeout",
                _normalize_timeout_budget(self.overall_timeout, "overall_timeout"),
            )
        object.__setattr__(
            self,
            "allow_insecure",
            _normalize_allow_insecure(self.allow_insecure),
        )


async def validate_relay_protocol(
    relay: Relay,
    context: RelayValidationContext,
    options: RelayValidationOptions,
) -> bool:
    """Check whether one relay speaks Nostr via a basic connect/fetch attempt.

    A relay counts as valid when the flow either completes a bounded
    ``fetch_events()`` call or reports ``auth-required`` during connection,
    because that still proves the endpoint speaks the Nostr protocol.
    """
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

        except (OSError, NostrSdkError) as exc:
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
                except (OSError, RuntimeError, TimeoutError, NostrSdkError) as exc:
                    context.logger.debug("client_shutdown_error error=%s", exc)
