"""Helpers for executing DVM NIP-90 job requests."""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import asyncpg

from bigbrotr.services.common.catalog import CatalogError
from bigbrotr.services.common.read_models import ReadModelQueryError

from .utils import (
    JobPreparationContext,
    RejectedJobRequest,
    ResultEventRequest,
    build_error_event,
    build_payment_required_event,
    build_result_event,
    normalize_job_params,
    normalize_requested_resource_id,
    parse_job_params,
    prepare_job_request,
)


if TYPE_CHECKING:
    from collections.abc import Mapping

    from bigbrotr.core.logger import Logger
    from bigbrotr.services.common.catalog_types import QueryResult
    from bigbrotr.services.common.configs import ReadModelPolicy
    from bigbrotr.services.common.read_models import ReadableResourceEntry, ReadCore, ReadModelQuery


_MIN_TAG_LEN = 2


class EventSender(Protocol):
    """Callable that publishes one DVM event through the connected client."""

    async def __call__(
        self,
        builder: Any,
        *,
        require_success: bool = False,
    ) -> tuple[tuple[str, ...], dict[str, str]]: ...


class ReadableResourceQueryExecutor(Protocol):
    """Callable that executes one resolved readable-resource query."""

    async def __call__(
        self,
        resource: ReadableResourceEntry,
        query: ReadModelQuery,
    ) -> QueryResult: ...


@dataclass(frozen=True, slots=True)
class JobExecutionContext:
    """Pure configuration and dependencies needed to execute one DVM job."""

    read_core: ReadCore
    exposure_policy: Mapping[str, ReadModelPolicy]
    default_page_size: int
    max_page_size: int
    request_kind: int


@dataclass(frozen=True, slots=True)
class JobRuntime:
    """Live collaborators required while executing one DVM job."""

    logger: Logger
    send_event: EventSender
    query_resource: ReadableResourceQueryExecutor


@dataclass(frozen=True, slots=True)
class JobRequest:
    """Parsed request data extracted from one DVM event."""

    event_id: str
    customer_pubkey: str
    params: dict[str, Any]
    requested_resource_id: str


async def process_request_event(
    *,
    event: Any,
    pubkey_hex: str,
    processed_ids: set[str],
    runtime: JobRuntime,
    context: JobExecutionContext,
) -> tuple[int, int, int, int]:
    """Process one buffered NIP-90 request event.

    Returns:
        Tuple of (received, processed, failed, payment_required) deltas.
    """
    event_id = event.id().to_hex()

    if event_id in processed_ids:
        return 0, 0, 0, 0

    p_tags = _extract_p_tags(event)
    if p_tags and pubkey_hex not in p_tags:
        return 0, 0, 0, 0

    processed_ids.add(event_id)
    try:
        params = normalize_job_params(parse_job_params(event))
        requested_resource_id = normalize_requested_resource_id(params.get("read_model", ""))

        request = JobRequest(
            event_id=event_id,
            customer_pubkey=event.author().to_hex(),
            params=params,
            requested_resource_id=requested_resource_id,
        )

        runtime.logger.info(
            "job_received",
            event_id=request.event_id,
            requested_read_model_id=requested_resource_id,
            customer=request.customer_pubkey,
        )

        return await handle_job_request(
            request=request,
            runtime=runtime,
            context=context,
        )
    except ReadModelQueryError as exc:
        with contextlib.suppress(OSError, TimeoutError):
            await runtime.send_event(
                build_error_event(event_id, event.author().to_hex(), exc.client_message),
                require_success=True,
            )
        return 1, 0, 1, 0
    except (CatalogError, OSError, TimeoutError, asyncpg.PostgresError) as exc:
        with contextlib.suppress(OSError, TimeoutError):
            await runtime.send_event(
                build_error_event(request.event_id, request.customer_pubkey, str(exc)),
                require_success=True,
            )
        runtime.logger.error("job_failed", event_id=request.event_id, error=str(exc))
        return 1, 0, 1, 0


async def handle_job_request(
    *,
    request: JobRequest,
    runtime: JobRuntime,
    context: JobExecutionContext,
) -> tuple[int, int, int, int]:
    """Execute one validated DVM job request end to end."""
    prepared_job = prepare_job_request(
        request.requested_resource_id,
        request.params,
        context=JobPreparationContext(
            read_core=context.read_core,
            exposure_policy=context.exposure_policy,
            default_page_size=context.default_page_size,
            max_page_size=context.max_page_size,
        ),
    )
    if isinstance(prepared_job, RejectedJobRequest):
        return await _handle_rejected_job(
            prepared_job=prepared_job,
            request=request,
            runtime=runtime,
        )

    resolved_resource_id = prepared_job.resource_id
    start = time.monotonic()
    result = await runtime.query_resource(prepared_job.resource, prepared_job.query)
    duration_ms = (time.monotonic() - start) * 1000

    await runtime.send_event(
        build_result_event(
            ResultEventRequest(
                request_kind=context.request_kind,
                request_event_id=request.event_id,
                customer_pubkey=request.customer_pubkey,
                resource_id=resolved_resource_id,
            ),
            result,
            prepared_job.price,
        ),
        require_success=True,
    )
    runtime.logger.info(
        "job_completed",
        event_id=request.event_id,
        resource_id=resolved_resource_id,
        rows=len(result.rows),
        duration_ms=round(duration_ms, 1),
    )
    return 1, 1, 0, 0


async def _handle_rejected_job(
    *,
    prepared_job: RejectedJobRequest,
    request: JobRequest,
    runtime: JobRuntime,
) -> tuple[int, int, int, int]:
    if prepared_job.required_price is not None:
        await runtime.send_event(
            build_payment_required_event(
                request.event_id,
                request.customer_pubkey,
                prepared_job.required_price,
            ),
            require_success=True,
        )
        runtime.logger.info(
            "job_payment_required",
            event_id=request.event_id,
            price=prepared_job.required_price,
            bid=prepared_job.bid,
        )
        return 1, 0, 0, 1

    error_message = prepared_job.error_message
    if error_message is None:
        raise RuntimeError("dvm job rejection missing client error message")
    await runtime.send_event(
        build_error_event(
            request.event_id,
            request.customer_pubkey,
            error_message,
        ),
        require_success=True,
    )
    return 1, 0, 1, 0


def _extract_p_tags(event: Any) -> list[str]:
    p_tags: list[str] = []
    for tag in event.tags().to_vec():
        values = tag.as_vec()
        if len(values) >= _MIN_TAG_LEN and values[0] == "p":
            p_tags.append(values[1])
    return p_tags
