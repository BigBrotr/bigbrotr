"""HTTP utilities for BigBrotr.

Provides bounded JSON reading for HTTP responses to prevent memory exhaustion
from oversized payloads. Used by both NIP-11 info fetching and Finder API
discovery.

Note:
    This module sits in the ``utils`` layer and depends only on third-party
    libraries (``aiohttp``). It is importable from both ``nips`` and
    ``services`` without violating the diamond DAG.

See Also:
    :func:`bigbrotr.nips.nip11.info.Nip11InfoMetadata._info`:
        NIP-11 info fetch that uses :func:`read_bounded_json`.
    :class:`bigbrotr.services.finder.Finder`:
        Finder API fetch that uses :func:`read_bounded_json`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    import aiohttp


async def read_bounded_json(response: aiohttp.ClientResponse, max_size: int) -> Any:
    """Read and parse a JSON response body with size enforcement.

    Reads up to ``max_size + 1`` bytes from the response stream. If the body
    exceeds ``max_size``, raises :class:`ValueError` *before* attempting JSON
    parsing, preventing memory exhaustion from oversized payloads.

    Args:
        response: An aiohttp response whose body has not yet been consumed.
        max_size: Maximum allowed response body size in bytes.

    Returns:
        The parsed JSON value (dict, list, str, int, float, bool, or None).

    Raises:
        ValueError: If the response body exceeds *max_size*.
        json.JSONDecodeError: If the body is not valid JSON.
    """
    body = await response.content.read(max_size + 1)
    if len(body) > max_size:
        raise ValueError(f"Response body too large: >{max_size} bytes")
    return json.loads(body)
