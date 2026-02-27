"""Shared domain types for BigBrotr services.

Lightweight dataclasses produced by query functions and consumed by
services.  Keeping them in their own module avoids circular imports
between ``queries`` and individual service packages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Mapping

    from bigbrotr.models.relay import Relay


@dataclass(frozen=True, slots=True)
class Candidate:
    """Relay candidate pending validation.

    Wraps a [Relay][bigbrotr.models.relay.Relay] object with its
    ``service_state`` metadata, providing convenient access to validation
    state (e.g., failure count).

    Attributes:
        relay: [Relay][bigbrotr.models.relay.Relay] object with URL and
            network information.
        data: Metadata from the ``service_state`` table (``network``,
            ``failures``, etc.).

    See Also:
        [fetch_candidates][bigbrotr.services.common.queries.fetch_candidates]:
            Query that produces candidates.
    """

    relay: Relay
    data: Mapping[str, Any]

    @property
    def failures(self) -> int:
        """Return the number of failed validation attempts for this candidate."""
        return int(self.data.get("failures", 0))
