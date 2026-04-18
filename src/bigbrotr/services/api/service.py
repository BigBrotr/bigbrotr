"""REST API service for public readable-resource exposure via FastAPI.

The API adapter is built on the shared
[ReadCore][bigbrotr.services.common.read_models.ReadCore]. It exposes enabled
readable resources over HTTP while preserving the stable historical
``read_model`` transport contract under ``/read-models``.

The HTTP server runs as a background ``asyncio.Task`` alongside the
standard ``run_forever()`` cycle.  Each ``run()`` cycle logs request
statistics and updates Prometheus metrics.

Note:
    Rate limiting is not enforced at the application level — it is
    expected to be handled by the reverse proxy (e.g., Cloudflare,
    Nginx).  The API is strictly read-only: only GET methods are
        registered, and all queries are executed through the shared read core
        and its catalog-backed validation layer.

See Also:
    [ApiConfig][bigbrotr.services.api.ApiConfig]: Configuration model
        for HTTP settings, pagination, CORS, and exposure policy.
    [ReadCore][bigbrotr.services.common.read_models.ReadCore]: Shared
        protocol-agnostic read core used by the API and DVM adapters.
    [BaseService][bigbrotr.core.base_service.BaseService]: Abstract
        base class providing lifecycle and metrics.

Examples:
    ```python
    from bigbrotr.core import Brotr
    from bigbrotr.services import Api

    brotr = Brotr.from_yaml("deployments/bigbrotr/config/brotr.yaml")
    api = Api.from_yaml("deployments/bigbrotr/config/services/api.yaml", brotr=brotr)

    async with brotr:
        async with api:
            await api.run_forever()
    ```
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING, Any, ClassVar

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName
from bigbrotr.services.common.read_models import ReadCore

from .configs import ApiConfig
from .routes import (
    register_readable_resource_data_routes,
    register_readable_resource_routes,
)


if TYPE_CHECKING:
    from types import TracebackType

    from bigbrotr.core.brotr import Brotr

_HTTP_ERROR_THRESHOLD = 400


class Api(BaseService[ApiConfig]):
    """HTTP adapter exposing BigBrotr public readable resources.

    The public transport still speaks in terms of ``read models`` for backward
    compatibility, but the runtime contract is now the shared read core plus
    per-adapter exposure policy.

    Lifecycle:
        1. ``__aenter__``: discover schema, build FastAPI app, start uvicorn.
        2. ``run()``: log statistics and update Prometheus gauges.
        3. ``__aexit__``: cancel the HTTP server task.

    See Also:
        [ApiConfig][bigbrotr.services.api.ApiConfig]: Configuration model for
            this adapter.
        [Dvm][bigbrotr.services.dvm.Dvm]: Sibling service that exposes
            the same readable-resource data via Nostr NIP-90.
    """

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.API
    CONFIG_CLASS: ClassVar[type[ApiConfig]] = ApiConfig

    def __init__(self, brotr: Brotr, config: ApiConfig | None = None) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: ApiConfig
        self._read_core = ReadCore(policy_source=lambda: self._config.exposure_policy)
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task[None] | None = None
        self._requests_total = 0
        self._requests_failed = 0

    async def __aenter__(self) -> Api:
        await super().__aenter__()
        await self._read_core.discover(self._brotr, logger=self._logger)

        app = self._build_app()
        resource_count = len(self._read_core.enabled_resource_ids("api"))
        self._logger.info("endpoints_registered", count=resource_count)
        self.set_gauge("readable_resources_exposed", resource_count)

        config = uvicorn.Config(
            app,
            host=self._config.host,
            port=self._config.port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(self._server.serve())
        startup_complete = False
        try:
            while not self._server.started:
                self._raise_if_server_task_stopped()
                await asyncio.sleep(0)
            startup_complete = True
        finally:
            if not startup_complete:
                await self._stop_server_task()
        self._logger.info(
            "http_server_started",
            host=self._config.host,
            port=self._config.port,
        )

        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        await self._stop_server_task()
        self._logger.info("http_server_stopped")
        await super().__aexit__(_exc_type, _exc_val, _exc_tb)

    async def cleanup(self) -> int:
        """No-op: Api does not use service state."""
        return 0

    async def run(self) -> None:
        """Log request stats and update Prometheus counters.

        Detects a crashed HTTP server task and raises ``RuntimeError``
        to trigger the ``run_forever()`` failure counter.  Per-cycle
        request counters are snapshotted and reset atomically.
        """
        self._raise_if_server_task_stopped()

        # Snapshot and reset per-cycle counters
        total = self._requests_total
        failed = self._requests_failed
        self._requests_total = 0
        self._requests_failed = 0

        readable_resources_exposed = len(self._read_core.enabled_resource_ids("api"))
        self._logger.info(
            "cycle_stats",
            requests_total=total,
            requests_failed=failed,
            readable_resources_exposed=readable_resources_exposed,
        )
        self.inc_counter("requests_total", total)
        self.inc_counter("requests_failed", failed)
        self.set_gauge("readable_resources_exposed", readable_resources_exposed)

    # ── App construction ──────────────────────────────────────────

    def _build_app(self) -> FastAPI:
        """Construct the FastAPI application with auto-generated public routes.

        Delegates to sub-methods for each route group:
        middleware, health, discovery, and readable-resource data routes.
        """
        app = FastAPI(title=self._config.title)

        self._add_middleware(app)
        self._add_health_route(app)
        self._add_resource_discovery_routes(app)
        self._add_resource_data_routes(app)

        return app

    def _add_middleware(self, app: FastAPI) -> None:
        """Register CORS and request-logging middleware."""
        if self._config.cors_origins:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=self._config.cors_origins,
                allow_methods=["GET"],
                allow_headers=["*"],
            )

        @app.middleware("http")
        async def log_requests(request: Request, call_next: Any) -> Response:
            start = time.monotonic()
            self._logger.info(
                "request_received",
                method=request.method,
                path=request.url.path,
                params=str(request.query_params),
            )
            try:
                response: Response = await call_next(request)
            except Exception as exc:  # HTTP request error boundary
                self._logger.error(
                    "unhandled_error",
                    error=str(exc),
                    path=request.url.path,
                )
                response = JSONResponse(
                    {"error": "Internal server error"},
                    status_code=500,
                )
            duration_ms = (time.monotonic() - start) * 1000
            self._requests_total += 1
            if response.status_code >= _HTTP_ERROR_THRESHOLD:
                self._requests_failed += 1
                self._logger.warning(
                    "request_failed",
                    method=request.method,
                    path=request.url.path,
                    status=response.status_code,
                    duration_ms=round(duration_ms, 1),
                )
            else:
                self._logger.info(
                    "request_completed",
                    method=request.method,
                    path=request.url.path,
                    status=response.status_code,
                    duration_ms=round(duration_ms, 1),
                )
            return response

    def _add_health_route(self, app: FastAPI) -> None:
        """Register the ``/health`` endpoint."""

        @app.get("/health")
        async def health() -> dict[str, str]:
            return {"status": "ok"}

    def _add_resource_discovery_routes(self, app: FastAPI) -> None:
        """Register discovery endpoints for the public readable-resource surface."""
        register_readable_resource_routes(
            app,
            read_core=self._read_core,
            route_prefix=self._config.route_prefix,
        )

    def _add_resource_data_routes(self, app: FastAPI) -> None:
        """Register list and detail routes for enabled public readable resources."""
        register_readable_resource_data_routes(
            app,
            brotr=self._brotr,
            read_core=self._read_core,
            route_prefix=self._config.route_prefix,
            default_page_size=self._config.default_page_size,
            max_page_size=self._config.max_page_size,
            request_timeout=self._config.request_timeout,
        )

    # ── Server lifecycle ──────────────────────────────────────────

    async def _stop_server_task(self) -> None:
        """Cancel the HTTP server task and clear local server state."""
        task = self._server_task
        self._server_task = None

        if task is not None:
            if task.done():
                if not task.cancelled():
                    task.exception()
            else:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._server = None

    def _raise_if_server_task_stopped(self) -> None:
        """Raise when the HTTP server task has exited unexpectedly."""
        if self._server_task is None or not self._server_task.done():
            return

        exc: BaseException | None = None
        if not self._server_task.cancelled():
            try:
                exc = self._server_task.exception()
            except BaseException as task_exc:
                exc = task_exc

        self._logger.error("http_server_crashed", error=str(exc) if exc else "cancelled")
        raise RuntimeError("HTTP server task has stopped unexpectedly") from exc
