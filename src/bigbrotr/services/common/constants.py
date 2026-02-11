"""Shared constants for BigBrotr services.

Service-level enumerations and re-exports of model-layer types.
[ServiceState][bigbrotr.models.service_state.ServiceState],
[ServiceStateKey][bigbrotr.models.service_state.ServiceStateKey],
[StateType][bigbrotr.models.service_state.StateType],
[EventKind][bigbrotr.models.service_state.EventKind], and
``EVENT_KIND_MAX`` are defined in
[bigbrotr.models.service_state][bigbrotr.models.service_state] and
re-exported here for backward compatibility.

See Also:
    [bigbrotr.models.service_state][bigbrotr.models.service_state]:
        Canonical source of ``ServiceState``, ``StateType``, and
        ``EventKind`` definitions.
    [queries][bigbrotr.services.common.queries]: SQL query functions
        that reference ``ServiceName`` and ``StateType``.
"""

from __future__ import annotations

from enum import StrEnum

from bigbrotr.models.service_state import (
    EVENT_KIND_MAX,
    EventKind,
    ServiceState,
    ServiceStateKey,
    StateType,
)


class ServiceName(StrEnum):
    """Canonical service identifiers used in logging, metrics, and persistence.

    Each member corresponds to one of the five pipeline services. The string
    values are used as the ``service_name`` column in the ``service_state``
    table and as the ``service`` label in Prometheus metrics.

    Attributes:
        SEEDER: One-shot bootstrapping service
            ([Seeder][bigbrotr.services.seeder.Seeder]).
        FINDER: Continuous relay URL discovery service
            ([Finder][bigbrotr.services.finder.Finder]).
        VALIDATOR: WebSocket-based Nostr protocol validation service
            ([Validator][bigbrotr.services.validator.Validator]).
        MONITOR: NIP-11 / NIP-66 health monitoring service
            ([Monitor][bigbrotr.services.monitor.Monitor]).
        SYNCHRONIZER: Cursor-based event collection service
            ([Synchronizer][bigbrotr.services.synchronizer.Synchronizer]).

    See Also:
        [BaseService][bigbrotr.core.base_service.BaseService]: Abstract
            base class that uses ``SERVICE_NAME`` for logging context.
        [queries][bigbrotr.services.common.queries]: SQL functions that
            filter ``service_state`` rows by service name.
    """

    SEEDER = "seeder"
    FINDER = "finder"
    VALIDATOR = "validator"
    MONITOR = "monitor"
    SYNCHRONIZER = "synchronizer"


__all__ = [
    "EVENT_KIND_MAX",
    "EventKind",
    "ServiceName",
    "ServiceState",
    "ServiceStateKey",
    "StateType",
]
