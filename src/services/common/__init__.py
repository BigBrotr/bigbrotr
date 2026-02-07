"""Shared infrastructure for all BigBrotr services.

This package provides three stable modules:

- **constants**: ``ServiceName`` and ``DataType`` enumerations.
- **mixins**: ``BatchProgressMixin`` and ``NetworkSemaphoreMixin``.
- **queries**: Domain-specific SQL query functions.

Future additions go *into* existing modules rather than creating new files.
"""

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
    "DataType",
    "NetworkSemaphoreMixin",
    "ServiceName",
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
