"""Shared constants for BigBrotr services.

All service-level enumerations live here. Add new constants as members
of existing enums rather than creating standalone string literals.
"""

from enum import StrEnum


class ServiceName(StrEnum):
    """Canonical service identifiers used in logging, metrics, and persistence."""

    SEEDER = "seeder"
    FINDER = "finder"
    VALIDATOR = "validator"
    MONITOR = "monitor"
    SYNCHRONIZER = "synchronizer"


class DataType(StrEnum):
    """Service data type identifiers for the ``service_data`` table."""

    CANDIDATE = "candidate"
    CURSOR = "cursor"
    CHECKPOINT = "checkpoint"
