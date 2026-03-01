"""Shared fixtures and helpers for services.finder test package."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock


def _mock_api_response(data: Any) -> MagicMock:
    """Build a mock aiohttp response returning *data* as bounded JSON body."""
    body = json.dumps(data).encode()
    content = MagicMock()
    content.read = AsyncMock(side_effect=[body, b""])

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.content = content
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)
    return resp
