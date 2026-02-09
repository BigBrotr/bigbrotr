"""Shared constants for BigBrotr services.

Service-level enumerations and re-exports of model-layer types.
``ServiceState``, ``ServiceStateKey``, ``StateType``, ``EventKind``,
and ``EVENT_KIND_MAX`` are defined in ``bigbrotr.models.service_state``
and re-exported here for backward compatibility.
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
    """Canonical service identifiers used in logging, metrics, and persistence."""

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
