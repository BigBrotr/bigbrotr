"""HTTP utilities for BigBrotr.

Provides bounded JSON reading for HTTP responses and bounded file downloads
to prevent memory exhaustion from oversized payloads.

Note:
    This module sits in the ``utils`` layer and depends only on stdlib and
    third-party libraries (``aiohttp``). It is importable from both ``nips``
    and ``services`` without violating the diamond DAG.

See Also:
    :func:`bigbrotr.nips.nip11.info.Nip11InfoMetadata._info`:
        NIP-11 info fetch that uses :func:`read_bounded_json`.
    :class:`bigbrotr.services.finder.Finder`:
        Finder API fetch that uses :func:`read_bounded_json`.
"""

from __future__ import annotations

import json
import urllib.request
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from pathlib import Path

    import aiohttp


def download_bounded_file(url: str, dest: Path, max_size: int, timeout: float = 60.0) -> None:
    """Download a file with size enforcement.

    Reads up to ``max_size + 1`` bytes from the URL. If the body exceeds
    ``max_size``, raises :class:`ValueError` *before* writing, preventing
    disk exhaustion from oversized payloads. Creates parent directories
    if they do not exist.

    Args:
        url: Download URL.
        dest: Local path to save the file.
        max_size: Maximum allowed file size in bytes.
        timeout: Socket timeout in seconds for the HTTP request.

    Raises:
        urllib.error.URLError: If download fails or times out.
        ValueError: If the downloaded file exceeds *max_size*.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url)  # noqa: S310
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        data = response.read(max_size + 1)
        if len(data) > max_size:
            raise ValueError(f"Download too large: >{max_size} bytes")
        dest.write_bytes(data)


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
