"""Shared infrastructure for all BigBrotr services.

Provides the foundational building blocks used across all five pipeline
services: configuration models, mixins, and centralized SQL query functions.

Attributes:
    configs: Per-network Pydantic configuration models
        ([ClearnetConfig][bigbrotr.services.common.configs.ClearnetConfig],
        [TorConfig][bigbrotr.services.common.configs.TorConfig],
        [I2pConfig][bigbrotr.services.common.configs.I2pConfig],
        [LokiConfig][bigbrotr.services.common.configs.LokiConfig]) with
        sensible defaults for timeouts, proxy URLs, and max concurrent tasks.
    mixins: [BatchProgress][bigbrotr.services.common.mixins.BatchProgress]
        dataclass for tracking batch processing cycles and
        [NetworkSemaphoresMixin][bigbrotr.services.common.mixins.NetworkSemaphoresMixin]
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
from .mixins import (
    BatchProgress,
    BatchProgressMixin,
    GeoReaderMixin,
    NetworkSemaphores,
    NetworkSemaphoresMixin,
    NostrPublisherMixin,
)
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
    insert_candidates,
    promote_candidates,
)
from .utils import parse_delete_result, validate_relay_url


__all__ = [
    "BatchProgress",
    "BatchProgressMixin",
    "ClearnetConfig",
    "GeoReaderMixin",
    "I2pConfig",
    "LokiConfig",
    "NetworkConfig",
    "NetworkSemaphores",
    "NetworkSemaphoresMixin",
    "NetworkTypeConfig",
    "NostrPublisherMixin",
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
    "insert_candidates",
    "parse_delete_result",
    "promote_candidates",
    "validate_relay_url",
]
