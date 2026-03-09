"""REST API service for read-only database exposure via FastAPI.

Auto-generates paginated endpoints for all discovered tables, views, and
materialized views.  Per-table access control via
[TableConfig][bigbrotr.services.common.configs.TableConfig] allows
disabling individual endpoints.

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

    brotr = Brotr.from_yaml("config/brotr.yaml")
    api = Api.from_yaml("config/services/api.yaml", brotr=brotr)

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
from bigbrotr.services.common.mixins import CatalogAccessMixin

from .configs import ApiConfig


if TYPE_CHECKING:
    from types import TracebackType

    from bigbrotr.core.brotr import Brotr

_HTTP_ERROR_THRESHOLD = 400


class Api(CatalogAccessMixin, BaseService[ApiConfig]):
    """REST API service exposing the BigBrotr database read-only.

    Auto-generates paginated GET endpoints for each enabled table,
    view, and materialized view discovered by the
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
        self._server_task: asyncio.Task[None] | None = None
        self._requests_total = 0
        self._requests_failed = 0

    async def __aenter__(self) -> Api:
        await super().__aenter__()

        app = self._build_app()
        endpoint_count = sum(1 for name in self._catalog.tables if self._is_table_enabled(name))
        self._logger.info("endpoints_registered", count=endpoint_count)
        self.set_gauge("tables_exposed", endpoint_count)

        self._server_task = asyncio.create_task(self._run_server(app))
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
        if self._server_task is not None:
            self._server_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._server_task
            self._server_task = None
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
        if self._server_task is not None and self._server_task.done():
            exc = self._server_task.exception() if not self._server_task.cancelled() else None
            self._logger.error("http_server_crashed", error=str(exc) if exc else "cancelled")
            raise RuntimeError("HTTP server task has stopped unexpectedly") from exc

        # Snapshot and reset per-cycle counters
        total = self._requests_total
        failed = self._requests_failed
        self._requests_total = 0
        self._requests_failed = 0

        tables_exposed = sum(1 for name in self._catalog.tables if self._is_table_enabled(name))
        self._logger.info(
            "cycle_stats",
            requests_total=total,
            requests_failed=failed,
            tables_exposed=tables_exposed,
        )
        self.inc_counter("requests_total", total)
        self.inc_counter("requests_failed", failed)
        self.set_gauge("tables_exposed", tables_exposed)

    # ── App construction ──────────────────────────────────────────

    def _build_app(self) -> FastAPI:
        """Construct the FastAPI application with auto-generated routes.

        Delegates to sub-methods for each route group:
        middleware, health, schema endpoints, and per-table CRUD routes.
        """
        app = FastAPI(title=self._config.title)

        self._add_middleware(app)
        self._add_health_route(app)
        self._add_schema_routes(app)
        self._add_table_routes(app)

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

    def _add_schema_routes(self, app: FastAPI) -> None:
        """Register schema list and detail endpoints."""
        prefix = self._config.route_prefix

        @app.get(f"{prefix}/schema")
        async def list_schema() -> JSONResponse:
            tables = [
                {
                    "name": schema.name,
                    "is_view": schema.is_view,
                    "columns": len(schema.columns),
                    "has_primary_key": bool(schema.primary_key),
                }
                for name, schema in sorted(self._catalog.tables.items())
                if self._is_table_enabled(name)
            ]
            return JSONResponse({"data": tables})

        @app.get(f"{prefix}/schema/{{table}}")
        async def get_schema(table: str) -> JSONResponse:
            if table not in self._catalog.tables or not self._is_table_enabled(table):
                return JSONResponse(
                    {"error": f"table not found: {table}"},
                    status_code=404,
                )
            schema = self._catalog.tables[table]
            return JSONResponse(
                {
                    "data": {
                        "name": schema.name,
                        "is_view": schema.is_view,
                        "columns": [
                            {
                                "name": c.name,
                                "type": c.pg_type,
                                "nullable": c.nullable,
                            }
                            for c in schema.columns
                        ],
                        "primary_key": list(schema.primary_key),
                    },
                }
            )

    def _add_table_routes(self, app: FastAPI) -> None:
        """Register auto-generated list and detail routes for enabled tables."""
        for table_name in self._catalog.tables:
            if not self._is_table_enabled(table_name):
                continue
            self._register_table_routes(app, table_name)

    def _register_table_routes(self, app: FastAPI, table_name: str) -> None:
        """Register list and detail routes for a single table.

        Each call creates a new scope, so closures safely capture
        ``table_name`` and ``pk_cols`` without the loop-variable gotcha.
        """
        schema = self._catalog.tables[table_name]
        pk_cols = schema.primary_key

        @app.get(f"{self._config.route_prefix}/{table_name}")
        async def list_rows(request: Request) -> JSONResponse:
            params = dict(request.query_params)
            try:
                limit = int(params.pop("limit", self._config.default_page_size))
                offset = int(params.pop("offset", 0))
            except (ValueError, TypeError):
                return JSONResponse(
                    {"error": "Invalid limit or offset"},
                    status_code=400,
                )
            sort = params.pop("sort", None)
            filters = params or None

            try:
                result = await asyncio.wait_for(
                    self._catalog.query(
                        self._brotr,
                        table_name,
                        limit=limit,
                        offset=offset,
                        max_page_size=self._config.max_page_size,
                        filters=filters,
                        sort=sort,
                    ),
                    timeout=self._config.request_timeout,
                )
            except TimeoutError:
                return JSONResponse({"error": "Query timeout"}, status_code=504)
            except CatalogError as e:
                return JSONResponse({"error": e.client_message}, status_code=400)

            return JSONResponse(
                {
                    "data": result.rows,
                    "meta": {
                        "total": result.total,
                        "limit": result.limit,
                        "offset": result.offset,
                        "table": table_name,
                    },
                }
            )

        # PK-based detail route (only for tables with a primary key)
        if pk_cols:
            if len(pk_cols) == 1:
                pk_col = pk_cols[0]
                pk_path = f"{{{pk_col}:path}}"
            else:
                pk_path = "/".join(f"{{{pk}}}" for pk in pk_cols)

            @app.get(f"{self._config.route_prefix}/{table_name}/{pk_path}")
            async def get_row(request: Request) -> JSONResponse:
                pk_values = {col: request.path_params[col] for col in pk_cols}
                try:
                    row = await asyncio.wait_for(
                        self._catalog.get_by_pk(
                            self._brotr,
                            table_name,
                            pk_values,
                        ),
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

    # ── Server lifecycle ──────────────────────────────────────────

    async def _run_server(self, app: FastAPI) -> None:
        """Run uvicorn as an asyncio server."""
        config = uvicorn.Config(
            app,
            host=self._config.host,
            port=self._config.port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        await server.serve()
