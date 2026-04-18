"""Route registration helpers for the HTTP readable-resource adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse

from .read_models import ApiReadModelHandler


if TYPE_CHECKING:
    from fastapi import FastAPI

    from bigbrotr.core.brotr import Brotr
    from bigbrotr.services.common.read_models import ReadableResourceEntry, ReadCore


def register_read_model_routes(
    app: FastAPI,
    *,
    read_core: ReadCore,
    route_prefix: str,
) -> None:
    """Register discovery endpoints for the public API resource surface.

    The path stays under ``/read-models`` because that is the stable external
    transport contract, even though the internal contract is now
    readable-resource based.
    """

    @app.get(f"{route_prefix}/read-models")
    async def list_read_models() -> JSONResponse:
        return JSONResponse(
            {"data": read_core.build_resource_summaries("api", route_prefix=route_prefix)}
        )

    @app.get(f"{route_prefix}/read-models/{{read_model_id}}")
    async def get_read_model(read_model_id: str) -> JSONResponse:
        detail = read_core.build_resource_detail("api", read_model_id, route_prefix=route_prefix)
        if detail is None:
            return JSONResponse(
                {"error": f"read model not found: {read_model_id}"},
                status_code=404,
            )
        return JSONResponse({"data": detail})


def register_read_model_data_routes(  # noqa: PLR0913
    app: FastAPI,
    *,
    brotr: Brotr,
    read_core: ReadCore,
    route_prefix: str,
    default_page_size: int,
    max_page_size: int,
    request_timeout: float,
) -> None:
    """Register collection and detail routes for enabled public resources."""
    for read_model_id, read_model in read_core.enabled_resources("api").items():
        _register_read_model_data_routes(
            app,
            brotr=brotr,
            read_core=read_core,
            route_prefix=route_prefix,
            read_model_id=read_model_id,
            read_model=read_model,
            default_page_size=default_page_size,
            max_page_size=max_page_size,
            request_timeout=request_timeout,
        )


def _register_read_model_data_routes(  # noqa: PLR0913
    app: FastAPI,
    *,
    brotr: Brotr,
    read_core: ReadCore,
    route_prefix: str,
    read_model_id: str,
    read_model: ReadableResourceEntry,
    default_page_size: int,
    max_page_size: int,
    request_timeout: float,
) -> None:
    """Register collection and optional detail routes for one resource entry."""
    handler = ApiReadModelHandler(
        brotr=brotr,
        read_core=read_core,
        read_model_id=read_model_id,
        read_model=read_model,
        default_page_size=default_page_size,
        max_page_size=max_page_size,
        request_timeout=request_timeout,
    )
    app.get(f"{route_prefix}/{read_model_id}")(handler.list_rows)

    pk_cols = handler.primary_key_columns
    if not pk_cols:
        return

    app.get(f"{route_prefix}/{read_model_id}/{_primary_key_path(pk_cols)}")(handler.get_row)


def _primary_key_path(pk_columns: tuple[str, ...]) -> str:
    """Build the FastAPI path fragment for one primary-key route."""
    if len(pk_columns) == 1:
        return f"{{{pk_columns[0]}:path}}"
    return "/".join(f"{{{column}}}" for column in pk_columns)
