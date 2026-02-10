"""Service state types for database persistence.

Pure data containers representing rows and keys in the ``service_state``
table. These live in the models layer because they have zero I/O, zero
package dependencies, and are used by both ``core.brotr`` and ``services``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Any, NamedTuple


class EventKind(IntEnum):
    """Well-known Nostr event kinds used across services."""

    RECOMMEND_RELAY = 2
    CONTACTS = 3
    RELAY_LIST = 10_002
    NIP66_TEST = 22_456
    MONITOR_ANNOUNCEMENT = 10_166
    RELAY_DISCOVERY = 30_166


EVENT_KIND_MAX = 65_535


class StateType(StrEnum):
    """Service state type identifiers for the ``service_state`` table."""

    CANDIDATE = "candidate"
    CURSOR = "cursor"
    CHECKPOINT = "checkpoint"


@dataclass(frozen=True, slots=True)
class ServiceState:
    """A single row in the ``service_state`` table.

    Used as input to ``Brotr.upsert_service_state()`` and as return type
    from ``Brotr.get_service_state()``.

    Examples:
        ```python
        state = ServiceState(
            service_name="synchronizer",
            state_type="cursor",
            state_key="wss://relay.damus.io",
            payload={"last_seen": 1700000000},
            updated_at=1700000001,
        )
        state.service_name  # 'synchronizer'
        ```
    """

    service_name: str
    state_type: str
    state_key: str
    payload: dict[str, Any]
    updated_at: int


class ServiceStateKey(NamedTuple):
    """Composite primary key for the ``service_state`` table.

    Used as input to ``Brotr.delete_service_state()``.
    """

    service_name: str
    state_type: str
    state_key: str
