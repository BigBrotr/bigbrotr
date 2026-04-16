"""Helpers for serving public API read-model routes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import Request  # noqa: TC002
from fastapi.responses import JSONResponse

from bigbrotr.services.common.catalog import CatalogError
from bigbrotr.services.common.read_models import (
    ReadModelEntry,
    ReadModelQueryError,
    ReadModelSurface,
    build_read_model_meta,
    read_model_query_from_http_params,
)


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr


@dataclass(frozen=True, slots=True)
class ApiReadModelHandler:
    """Serve one public API read model through a shared read-model surface."""

    brotr: Brotr
    read_models: ReadModelSurface
    read_model_id: str
    read_model: ReadModelEntry
    default_page_size: int
    max_page_size: int
    request_timeout: float

    @property
    def primary_key_columns(self) -> tuple[str, ...]:
        """Return the primary-key columns for this read model."""
        return self.read_model.schema(self.read_models.catalog).primary_key

    async def list_rows(self, request: Request) -> JSONResponse:
        """Serve the collection route for this read model."""
        try:
            query = read_model_query_from_http_params(
                request.query_params,
                default_page_size=self.default_page_size,
                max_page_size=self.max_page_size,
            )
        except ReadModelQueryError as exc:
            return JSONResponse({"error": exc.client_message}, status_code=400)

        try:
            result = await asyncio.wait_for(
                self.read_models.query_entry(self.brotr, self.read_model, query),
                timeout=self.request_timeout,
            )
        except TimeoutError:
            return JSONResponse({"error": "Query timeout"}, status_code=504)
        except CatalogError as exc:
            return JSONResponse({"error": exc.client_message}, status_code=400)

        return JSONResponse(
            {
                "data": result.rows,
                "meta": build_read_model_meta(result, read_model_id=self.read_model_id),
            }
        )

    async def get_row(self, request: Request) -> JSONResponse:
        """Serve the identity lookup route for this read model."""
        pk_values = {column: request.path_params[column] for column in self.primary_key_columns}
        try:
            row = await asyncio.wait_for(
                self.read_models.get_entry_by_pk(self.brotr, self.read_model, pk_values),
                timeout=self.request_timeout,
            )
        except TimeoutError:
            return JSONResponse({"error": "Query timeout"}, status_code=504)
        except ValueError:
            return JSONResponse({"error": "Invalid request parameters"}, status_code=400)
        except CatalogError as exc:
            return JSONResponse({"error": exc.client_message}, status_code=400)

        if row is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"data": row})
