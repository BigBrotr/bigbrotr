"""REST API service for read-only read-model exposure via FastAPI.

Registers paginated endpoints for all enabled public read models.
[ReadModelPolicy][bigbrotr.services.common.configs.ReadModelPolicy] remains the
shared access-policy model, but the public HTTP contract is expressed in
terms of named read models rather than raw database tables.

The HTTP server runs as a background ``asyncio.Task`` alongside the
standard ``run_forever()`` cycle.  Each ``run()`` cycle logs request
statistics and updates Prometheus metrics.

Note:
    Rate limiting is not enforced at the application level — it is
    expected to be handled by the reverse proxy (e.g., Cloudflare,
    Nginx).  The API is strictly read-only: only GET methods are
    registered, and all queries are executed through the
    [Catalog][bigbrotr.services.common.catalog.Catalog] safe query
    builder.

See Also:
    [ApiConfig][bigbrotr.services.api.ApiConfig]: Configuration model
        for HTTP settings, pagination, and CORS.
    [Catalog][bigbrotr.services.common.catalog.Catalog]: Schema
        introspection and query builder shared with the DVM service.
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
from bigbrotr.services.common.catalog import CatalogError
from bigbrotr.services.common.read_models import (
    ReadModelEntry,
    ReadModelQueryError,
    ReadModelSurface,
    build_read_model_meta,
    read_model_query_from_http_params,
)

from .configs import ApiConfig


if TYPE_CHECKING:
    from types import TracebackType

    from bigbrotr.core.brotr import Brotr

_HTTP_ERROR_THRESHOLD = 400


class Api(BaseService[ApiConfig]):
    """REST API service exposing BigBrotr read models over HTTP.

    Registers paginated GET endpoints for each enabled public read
    model discovered through the shared
    [Catalog][bigbrotr.services.common.catalog.Catalog].

    Lifecycle:
        1. ``__aenter__``: discover schema, build FastAPI app, start uvicorn.
        2. ``run()``: log statistics and update Prometheus gauges.
        3. ``__aexit__``: cancel the HTTP server task.

    See Also:
        [ApiConfig][bigbrotr.services.api.ApiConfig]: Configuration
            model for this service.
        [Dvm][bigbrotr.services.dvm.Dvm]: Sibling service that exposes
            the same Catalog data via Nostr NIP-90.
    """

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.API
    CONFIG_CLASS: ClassVar[type[ApiConfig]] = ApiConfig

    def __init__(self, brotr: Brotr, config: ApiConfig | None = None) -> None:
        super().__init__(brotr=brotr, config=config)
        self._config: ApiConfig
        self._read_models = ReadModelSurface(policy_source=lambda: self._config.read_models)
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task[None] | None = None
        self._requests_total = 0
        self._requests_failed = 0

    async def __aenter__(self) -> Api:
        await super().__aenter__()
        await self._read_models.discover(self._brotr, logger=self._logger)

        app = self._build_app()
        read_model_count = len(self._enabled_read_model_names())
        self._logger.info("endpoints_registered", count=read_model_count)
        self.set_gauge("read_models_exposed", read_model_count)

        self._server = self._build_server(app)
        self._server_task = asyncio.create_task(self._run_server(self._server))
        startup_complete = False
        try:
            await self._wait_for_server_startup(self._server)
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

        read_models_exposed = len(self._enabled_read_model_names())
        self._logger.info(
            "cycle_stats",
            requests_total=total,
            requests_failed=failed,
            read_models_exposed=read_models_exposed,
        )
        self.inc_counter("requests_total", total)
        self.inc_counter("requests_failed", failed)
        self.set_gauge("read_models_exposed", read_models_exposed)

    # ── App construction ──────────────────────────────────────────

    def _build_app(self) -> FastAPI:
        """Construct the FastAPI application with auto-generated routes.

        Delegates to sub-methods for each route group:
        middleware, health, read-model discovery, and read-model data routes.
        """
        app = FastAPI(title=self._config.title)

        self._add_middleware(app)
        self._add_health_route(app)
        self._add_read_model_routes(app)
        self._add_read_model_data_routes(app)

        return app

    def _enabled_read_model_names(self) -> list[str]:
        """Return enabled API read models that are present in the discovered catalog."""
        return self._read_models.enabled_names("api")

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

    def _add_read_model_routes(self, app: FastAPI) -> None:
        """Register read-model discovery endpoints."""
        prefix = self._config.route_prefix

        @app.get(f"{prefix}/read-models")
        async def list_read_models() -> JSONResponse:
            return JSONResponse(
                {
                    "data": self._read_models.build_summaries(
                        "api",
                        route_prefix=self._config.route_prefix,
                    )
                }
            )

        @app.get(f"{prefix}/read-models/{{read_model_id}}")
        async def get_read_model(read_model_id: str) -> JSONResponse:
            detail = self._read_models.build_detail(
                "api",
                read_model_id,
                route_prefix=self._config.route_prefix,
            )
            if detail is None:
                return JSONResponse(
                    {"error": f"read model not found: {read_model_id}"},
                    status_code=404,
                )
            return JSONResponse({"data": detail})

    def _add_read_model_data_routes(self, app: FastAPI) -> None:
        """Register list and detail data routes for enabled read models."""
        for read_model_id, read_model in self._read_models.enabled_entries("api").items():
            self._register_read_model_data_routes(app, read_model_id, read_model)

    def _register_read_model_data_routes(
        self,
        app: FastAPI,
        read_model_id: str,
        read_model: ReadModelEntry,
    ) -> None:
        """Register list and detail routes for one public read model.

        Each call creates a new scope, so closures safely capture
        ``read_model_id`` and ``pk_cols`` without the loop-variable gotcha.
        """
        schema = read_model.schema(self._read_models.catalog)
        pk_cols = schema.primary_key

        async def list_rows(request: Request) -> JSONResponse:
            try:
                query = read_model_query_from_http_params(
                    request.query_params,
                    default_page_size=self._config.default_page_size,
                    max_page_size=self._config.max_page_size,
                )
            except ReadModelQueryError as e:
                return JSONResponse(
                    {"error": e.client_message},
                    status_code=400,
                )

            try:
                result = await asyncio.wait_for(
                    self._read_models.query_entry(self._brotr, read_model, query),
                    timeout=self._config.request_timeout,
                )
            except TimeoutError:
                return JSONResponse({"error": "Query timeout"}, status_code=504)
            except CatalogError as e:
                return JSONResponse({"error": e.client_message}, status_code=400)

            return JSONResponse(
                {
                    "data": result.rows,
                    "meta": build_read_model_meta(result, read_model_id=read_model_id),
                }
            )

        app.get(f"{self._config.route_prefix}/{read_model_id}")(list_rows)

        # PK-based detail route (only for read models with a primary key)
        if not pk_cols:
            return

        if len(pk_cols) == 1:
            pk_col = pk_cols[0]
            pk_path = f"{{{pk_col}:path}}"
        else:
            pk_path = "/".join(f"{{{pk}}}" for pk in pk_cols)

        async def get_row(request: Request) -> JSONResponse:
            pk_values = {col: request.path_params[col] for col in pk_cols}
            try:
                row = await asyncio.wait_for(
                    self._read_models.get_entry_by_pk(self._brotr, read_model, pk_values),
                    timeout=self._config.request_timeout,
                )
            except TimeoutError:
                return JSONResponse({"error": "Query timeout"}, status_code=504)
            except ValueError:
                return JSONResponse(
                    {"error": "Invalid request parameters"},
                    status_code=400,
                )
            except CatalogError as e:
                return JSONResponse({"error": e.client_message}, status_code=400)

            if row is None:
                return JSONResponse({"error": "not found"}, status_code=404)
            return JSONResponse({"data": row})

        app.get(f"{self._config.route_prefix}/{read_model_id}/{pk_path}")(get_row)

    # ── Server lifecycle ──────────────────────────────────────────

    def _build_server(self, app: FastAPI) -> uvicorn.Server:
        """Build the uvicorn server instance for this API service."""
        config = uvicorn.Config(
            app,
            host=self._config.host,
            port=self._config.port,
            log_level="warning",
            access_log=False,
        )
        return uvicorn.Server(config)

    async def _run_server(self, server: uvicorn.Server) -> None:
        """Run uvicorn as an asyncio server."""
        await server.serve()

    async def _wait_for_server_startup(self, server: uvicorn.Server) -> None:
        """Wait until uvicorn reports startup success or the server task fails."""
        while not server.started:
            self._raise_if_server_task_stopped()
            await asyncio.sleep(0)

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
