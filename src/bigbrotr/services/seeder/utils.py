"""Seeder service utility functions.

Pure helpers that do not require service instance state.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bigbrotr.services.common.utils import parse_relay_url


if TYPE_CHECKING:
    from pathlib import Path

    from bigbrotr.models import Relay

_logger = logging.getLogger(__name__)


def parse_seed_file(path: Path) -> list[Relay]:
    """Parse a seed file and validate relay URLs.

    Each line is passed to
    [parse_relay_url][bigbrotr.services.common.utils.parse_relay_url]
    for URL validation and network detection. Lines starting with ``#`` are
    treated as comments and skipped.

    Args:
        path: Path to the seed file (one URL per line).

    Returns:
        List of validated [Relay][bigbrotr.models.relay.Relay] objects.
    """
    relays: list[Relay] = []

    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                url = line.strip()
                if not url or url.startswith("#"):
                    continue
                relay = parse_relay_url(url)
                if relay:
                    relays.append(relay)
                else:
                    _logger.warning("relay_parse_failed: %s", url)
    except FileNotFoundError:
        _logger.warning("file_not_found: %s", path)

    return relays
