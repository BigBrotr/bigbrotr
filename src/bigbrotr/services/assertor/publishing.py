"""Shared publish flows for the Assertor service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar

import asyncpg

from bigbrotr.models.constants import EventKind
from bigbrotr.services.assertor.utils import PROVIDER_PROFILE_SUBJECT_ID


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nostr_sdk import Client, EventBuilder

    from bigbrotr.core.logger import Logger

    from .configs import AssertorConfig


class TaggedAssertion(Protocol):
    """Assertion payload that can produce a stable NIP-85 content hash."""

    def tags_hash(self) -> str: ...


AssertionT = TypeVar("AssertionT", bound=TaggedAssertion)


@dataclass(frozen=True, slots=True)
class PublishPlan(Generic[AssertionT]):
    """One assertion publish flow bound to a specific NIP-85 subject kind."""

    kind: int
    fetch_rows: Callable[[int], Awaitable[list[dict[str, Any]]]]
    assertion_from_row: Callable[[dict[str, Any]], AssertionT]
    subject_getter: Callable[[AssertionT], str]
    builder_from_assertion: Callable[[AssertionT], EventBuilder]
    error_event_name: str
    error_subject_field: str


@dataclass(frozen=True, slots=True)
class PublishRuntime:
    """Shared runtime dependencies for assertion publish flows."""

    algorithm_id: str
    batch_size: int
    client: Client
    logger: Logger
    mark_seen_state_key: Callable[[str], None]
    is_unchanged: Callable[[str, str], Awaitable[bool]]
    save_hash: Callable[[str, str], Awaitable[None]]
    publish_events: Callable[[list[EventBuilder], list[Client]], Awaitable[int]]
    build_state_key: Callable[..., str]


@dataclass(frozen=True, slots=True)
class ProviderProfileRuntime:
    """Dependencies for provider-profile publish coordination."""

    config: AssertorConfig
    client: Client
    logger: Logger
    mark_seen_state_key: Callable[[str], None]
    is_unchanged: Callable[[str, str], Awaitable[bool]]
    save_hash: Callable[[str, str], Awaitable[None]]
    publish_events: Callable[[list[EventBuilder], list[Client]], Awaitable[int]]
    build_state_key: Callable[..., str]
    build_profile_event: Callable[..., EventBuilder]
    provider_profile_content: Callable[..., dict[str, Any]]
    content_hash: Callable[[dict[str, Any]], str]


async def publish_assertion_rows(
    plan: PublishPlan[AssertionT],
    runtime: PublishRuntime,
) -> tuple[int, int, int]:
    """Publish one assertion subject type using the shared change-detection flow."""
    published = 0
    skipped = 0
    failed = 0
    offset = 0

    while True:
        rows = await plan.fetch_rows(offset)
        if not rows:
            break

        for row in rows:
            assertion = plan.assertion_from_row(row)
            subject_id = plan.subject_getter(assertion)
            state_key = runtime.build_state_key(
                algorithm_id=runtime.algorithm_id,
                kind=plan.kind,
                subject_id=subject_id,
            )
            runtime.mark_seen_state_key(state_key)
            current_hash = assertion.tags_hash()

            if await runtime.is_unchanged(state_key, current_hash):
                skipped += 1
                continue

            try:
                builder = plan.builder_from_assertion(assertion)
                sent = await runtime.publish_events([builder], [runtime.client])
                if sent > 0:
                    await runtime.save_hash(state_key, current_hash)
                    published += 1
                else:
                    failed += 1
            except (asyncpg.PostgresError, OSError) as exc:
                failed += 1
                runtime.logger.error(
                    plan.error_event_name,
                    **{
                        plan.error_subject_field: subject_id,
                        "algorithm_id": runtime.algorithm_id,
                        "error": str(exc),
                    },
                )

        if len(rows) < runtime.batch_size:
            break
        offset += runtime.batch_size

    return published, skipped, failed


async def publish_provider_profile(runtime: ProviderProfileRuntime) -> tuple[int, int, int]:
    """Publish the optional Kind 0 provider profile when its content changes."""
    state_key = runtime.build_state_key(
        algorithm_id=runtime.config.algorithm_id,
        kind=EventKind.SET_METADATA,
        subject_id=PROVIDER_PROFILE_SUBJECT_ID,
    )
    runtime.mark_seen_state_key(state_key)

    kind0 = runtime.config.provider_profile.kind0_content
    content = runtime.provider_profile_content(
        algorithm_id=runtime.config.algorithm_id,
        kind0_content=kind0,
    )
    current_hash = runtime.content_hash(content)
    if await runtime.is_unchanged(state_key, current_hash):
        return 0, 1, 0

    base_profile_fields = {
        "name",
        "about",
        "website",
        "picture",
        "nip05",
        "banner",
        "lud16",
    }
    extra_fields = {key: value for key, value in content.items() if key not in base_profile_fields}

    try:
        builder = runtime.build_profile_event(
            name=kind0.name,
            about=kind0.about,
            picture=kind0.picture,
            nip05=kind0.nip05,
            website=kind0.website,
            banner=kind0.banner,
            lud16=kind0.lud16,
            extra_fields=extra_fields,
        )
        sent = await runtime.publish_events([builder], [runtime.client])
        if sent > 0:
            await runtime.save_hash(state_key, current_hash)
            runtime.logger.info(
                "provider_profile_published",
                algorithm_id=runtime.config.algorithm_id,
                relays=sent,
            )
            return 1, 0, 0

        runtime.logger.warning(
            "provider_profile_publish_failed",
            algorithm_id=runtime.config.algorithm_id,
            error="no relays reachable",
        )
        return 0, 0, 1
    except (asyncpg.PostgresError, OSError) as exc:
        runtime.logger.error(
            "provider_profile_publish_failed",
            algorithm_id=runtime.config.algorithm_id,
            error=str(exc),
        )
        return 0, 0, 1
