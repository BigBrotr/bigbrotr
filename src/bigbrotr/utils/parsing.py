"""Tolerant parsing of raw data into validated model instances.

Provides a generic factory-based converter that iterates over a sequence of
raw data, calls a user-supplied factory for each element, and collects only the
successfully parsed results. Invalid entries are logged at WARNING level and
skipped.

The module depends only on [bigbrotr.models][bigbrotr.models] and the standard library,
keeping it safe to import from any layer above ``models``.

Examples:
    ```python
    from bigbrotr.utils.parsing import safe_parse, parse_relay_url

    relays = safe_parse(["wss://relay.example.com", "wss://nos.lol"], parse_relay_url)
    relays = safe_parse(rows, lambda r: Relay(r["url"], discovered_at=r["discovered_at"]))
    ```
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypeVar

from bigbrotr.models import Relay


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

logger = logging.getLogger(__name__)

_P = TypeVar("_P")
_M = TypeVar("_M")


def safe_parse(
    items: Sequence[_P],
    factory: Callable[[_P], _M],
) -> list[_M]:
    """Parse a sequence into model instances, skipping invalid entries.

    Calls ``factory(item)`` for each element.  Items that raise
    ``ValueError``, ``TypeError``, or ``KeyError`` are logged and discarded.
    """
    results: list[_M] = []
    for item in items:
        try:
            results.append(factory(item))
        except (ValueError, TypeError, KeyError):
            logger.warning("parse_failed item=%s", item)
    return results


def parse_relay_url(url: str, *, allow_local: bool = False) -> Relay:
    """Normalize a raw relay URL and construct a Relay.

    Delegates to [Relay.parse][bigbrotr.models.relay.Relay.parse], which
    normalizes the raw input and constructs a canonical
    [Relay][bigbrotr.models.relay.Relay]. Intended as a factory for
    [safe_parse][bigbrotr.utils.parsing.safe_parse] when parsing relay URLs
    from untrusted sources (config files, Nostr events, API responses).

    Args:
        url: Raw relay URL string.
        allow_local: Whether local relay URLs are accepted.

    Returns:
        [Relay][bigbrotr.models.relay.Relay] in canonical form.

    Raises:
        ValueError: If the URL is structurally unrecoverable.
    """
    return Relay.parse(url, allow_local=allow_local)


__all__ = [
    "parse_relay_url",
    "safe_parse",
]
