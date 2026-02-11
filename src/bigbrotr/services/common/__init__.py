"""Shared infrastructure for all BigBrotr services.

Provides the foundational building blocks used across all five pipeline
services: configuration models, constants, mixins, and centralized SQL
query functions.

Attributes:
    configs: Per-network Pydantic configuration models
        ([ClearnetConfig][bigbrotr.services.common.configs.ClearnetConfig],
        [TorConfig][bigbrotr.services.common.configs.TorConfig],
        [I2pConfig][bigbrotr.services.common.configs.I2pConfig],
        [LokiConfig][bigbrotr.services.common.configs.LokiConfig]) with
        sensible defaults for timeouts, proxy URLs, and max concurrent tasks.
    constants: [ServiceName][bigbrotr.services.common.constants.ServiceName]
        StrEnum identifying pipeline services, plus re-exports of model-layer
        types ([ServiceState][bigbrotr.models.service_state.ServiceState],
        [StateType][bigbrotr.models.service_state.StateType],
        [EventKind][bigbrotr.models.service_state.EventKind]).
    mixins: [BatchProgress][bigbrotr.services.common.mixins.BatchProgress]
        dataclass for tracking batch processing cycles and
        [NetworkSemaphoreMixin][bigbrotr.services.common.mixins.NetworkSemaphoreMixin]
        for per-network concurrency control.
    queries: 13 domain-specific SQL query functions centralized in one module
        to avoid scattering inline SQL across services.

See Also:
    [BaseService][bigbrotr.core.base_service.BaseService]: Abstract base
        class that all services extend.
    [Brotr][bigbrotr.core.brotr.Brotr]: Database facade consumed by all
        query functions in this package.
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
