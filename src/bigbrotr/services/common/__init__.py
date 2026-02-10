"""Shared infrastructure for all BigBrotr services.

Attributes:
    configs: Per-network Pydantic configuration models (`ClearnetConfig`,
        `TorConfig`, `I2pConfig`, `LokiConfig`) with sensible defaults
        for timeouts, proxy URLs, and max concurrent tasks.
    constants: `ServiceName` and `DataType` StrEnums identifying pipeline
        services and data categories.
    mixins: `BatchProgress` dataclass for tracking batch processing cycles
        and `NetworkSemaphoreMixin` for per-network concurrency control.
    queries: 13 domain-specific SQL query functions centralized in one module
        to avoid scattering inline SQL across services.
"""

from .configs import (
    ClearnetConfig,
    I2pConfig,
    LokiConfig,
    NetworkConfig,
    NetworkTypeConfig,
    TorConfig,
)
from .constants import (
    EVENT_KIND_MAX,
    EventKind,
    ServiceName,
    ServiceState,
    ServiceStateKey,
    StateType,
)
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
    "EVENT_KIND_MAX",
    "BatchProgress",
    "BatchProgressMixin",
    "ClearnetConfig",
    "EventKind",
    "I2pConfig",
    "LokiConfig",
    "NetworkConfig",
    "NetworkSemaphoreMixin",
    "NetworkTypeConfig",
    "ServiceName",
    "ServiceState",
    "ServiceStateKey",
    "StateType",
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
