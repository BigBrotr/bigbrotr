"""Shared infrastructure for all BigBrotr services.

This package provides four stable modules:

- **configs**: ``NetworkConfig`` and per-network configuration models.
- **constants**: ``ServiceName`` and ``DataType`` enumerations.
- **mixins**: ``BatchProgressMixin`` and ``NetworkSemaphoreMixin``.
- **queries**: Domain-specific SQL query functions.
"""

from .configs import (
    ClearnetConfig,
    I2pConfig,
    LokiConfig,
    NetworkConfig,
    NetworkTypeConfig,
    TorConfig,
)
from .constants import DataType, ServiceName
from .mixins import BatchProgress, BatchProgressMixin, NetworkSemaphoreMixin
from .queries import (
    count_candidates,
    count_relays_due_for_check,
    delete_exhausted_candidates,
    delete_stale_candidates,
    fetch_candidate_chunk,
    fetch_relays_due_for_check,
    filter_new_relay_urls,
    get_all_relay_urls,
    get_all_relays,
    get_all_service_cursors,
    get_events_with_relay_urls,
    promote_candidates,
    upsert_candidates,
)


__all__ = [
    "BatchProgress",
    "BatchProgressMixin",
    "ClearnetConfig",
    "DataType",
    "I2pConfig",
    "LokiConfig",
    "NetworkConfig",
    "NetworkSemaphoreMixin",
    "NetworkTypeConfig",
    "ServiceName",
    "TorConfig",
    "count_candidates",
    "count_relays_due_for_check",
    "delete_exhausted_candidates",
    "delete_stale_candidates",
    "fetch_candidate_chunk",
    "fetch_relays_due_for_check",
    "filter_new_relay_urls",
    "get_all_relay_urls",
    "get_all_relays",
    "get_all_service_cursors",
    "get_events_with_relay_urls",
    "promote_candidates",
    "upsert_candidates",
]
