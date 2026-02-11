"""Service state types for database persistence.

Pure data containers representing rows and keys in the ``service_state``
table. These live in the models layer because they have zero I/O, zero
package dependencies, and are used by both ``bigbrotr.core.brotr`` and
``bigbrotr.services``.

Note:
    These types were moved from ``services/common/constants`` to
    ``models/service_state`` to comply with the diamond DAG architecture.
    The models layer has no dependencies on other BigBrotr packages, so
    placing shared types here avoids import cycles.

See Also:
    [bigbrotr.core.brotr][]: The database facade that consumes
        [ServiceState][bigbrotr.models.service_state.ServiceState] and
        [ServiceStateKey][bigbrotr.models.service_state.ServiceStateKey] via
        ``upsert_service_state()`` and ``get_service_state()`` methods.
    [bigbrotr.services][]: Pipeline services that persist and restore
        processing cursors using these types.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Any, NamedTuple


class EventKind(IntEnum):
    """Well-known Nostr event kinds used across services.

    Each member corresponds to a NIP-defined event kind that BigBrotr
    processes or publishes.

    Attributes:
        RECOMMEND_RELAY: Kind 2 -- legacy relay recommendation (NIP-01, deprecated).
        CONTACTS: Kind 3 -- contact list with relay hints (NIP-02).
        RELAY_LIST: Kind 10002 -- NIP-65 relay list metadata.
        NIP66_TEST: Kind 22456 -- ephemeral NIP-66 relay test event.
        MONITOR_ANNOUNCEMENT: Kind 10166 -- NIP-66 monitor announcement
            (replaceable, published by the
            [Monitor][bigbrotr.services.monitor.Monitor] service).
        RELAY_DISCOVERY: Kind 30166 -- NIP-66 relay discovery event
            (parameterized replaceable, published by the
            [Monitor][bigbrotr.services.monitor.Monitor] service).

    See Also:
        [Event][bigbrotr.models.event.Event]: The event wrapper that carries
            these kinds.
        ``EVENT_KIND_MAX``: Maximum
            valid event kind value (65535).
    """

    RECOMMEND_RELAY = 2
    CONTACTS = 3
    RELAY_LIST = 10_002
    NIP66_TEST = 22_456
    MONITOR_ANNOUNCEMENT = 10_166
    RELAY_DISCOVERY = 30_166


EVENT_KIND_MAX = 65_535


class StateType(StrEnum):
    """Service state type identifiers for the ``service_state`` table.

    Used as the ``state_type`` discriminator in
    [ServiceState][bigbrotr.models.service_state.ServiceState] rows to
    distinguish between different kinds of persisted state.

    Attributes:
        CANDIDATE: A candidate URL discovered but not yet validated.
        CURSOR: A processing cursor marking the last-processed position
            in an ordered data source (e.g., event timestamp, relay index).
        CHECKPOINT: A checkpoint marking a milestone in a long-running
            operation (e.g., synchronization progress).

    See Also:
        [ServiceState][bigbrotr.models.service_state.ServiceState]: The row
            model that carries this type.
        [ServiceStateKey][bigbrotr.models.service_state.ServiceStateKey]:
            Composite key that includes ``state_type``.
    """

    CANDIDATE = "candidate"
    CURSOR = "cursor"
    CHECKPOINT = "checkpoint"


@dataclass(frozen=True, slots=True)
class ServiceState:
    """A single row in the ``service_state`` table.

    Used as input to ``Brotr.upsert_service_state()`` and as return type
    from ``Brotr.get_service_state()``.

    Attributes:
        service_name: Name of the pipeline service (e.g., ``"synchronizer"``,
            ``"finder"``).
        state_type: Discriminator string (see
            [StateType][bigbrotr.models.service_state.StateType]).
        state_key: Application-defined key within the service and type
            (e.g., a relay URL for cursor state).
        payload: Arbitrary JSON-compatible dictionary with service-specific data.
        updated_at: Unix timestamp of the last state update.

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

    Note:
        The composite primary key ``(service_name, state_type, state_key)``
        is represented by
        [ServiceStateKey][bigbrotr.models.service_state.ServiceStateKey] for
        delete operations.

    See Also:
        [ServiceStateKey][bigbrotr.models.service_state.ServiceStateKey]:
            Composite primary key for delete operations.
        [StateType][bigbrotr.models.service_state.StateType]: Enum of valid
            ``state_type`` values.
        [EventKind][bigbrotr.models.service_state.EventKind]: Well-known Nostr
            event kinds referenced in service state payloads.
    """

    service_name: str
    state_type: str
    state_key: str
    payload: dict[str, Any]
    updated_at: int


class ServiceStateKey(NamedTuple):
    """Composite primary key for the ``service_state`` table.

    Used as input to ``Brotr.delete_service_state()`` to identify and
    remove a specific state row.

    Attributes:
        service_name: Name of the pipeline service.
        state_type: Discriminator string (see
            [StateType][bigbrotr.models.service_state.StateType]).
        state_key: Application-defined key within the service and type.

    See Also:
        [ServiceState][bigbrotr.models.service_state.ServiceState]: The full
            row model that this key identifies.
    """

    service_name: str
    state_type: str
    state_key: str
