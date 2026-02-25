"""Shared infrastructure for all BigBrotr services.

Provides the foundational building blocks used across all six pipeline
services: configuration models, mixins, and centralized SQL query functions.

Attributes:
    configs: Per-network Pydantic configuration models
        ([ClearnetConfig][bigbrotr.services.common.configs.ClearnetConfig],
        [TorConfig][bigbrotr.services.common.configs.TorConfig],
        [I2pConfig][bigbrotr.services.common.configs.I2pConfig],
        [LokiConfig][bigbrotr.services.common.configs.LokiConfig]) with
        sensible defaults for timeouts, proxy URLs, and max concurrent tasks.
    mixins: [ChunkProgress][bigbrotr.services.common.mixins.ChunkProgress]
        dataclass for tracking chunk processing cycles,
        [NetworkSemaphoresMixin][bigbrotr.services.common.mixins.NetworkSemaphoresMixin]
        for per-network concurrency control, and
        [GeoReaders][bigbrotr.services.common.mixins.GeoReaders] for GeoIP
        database reader lifecycle management.
    queries: 14 domain-specific SQL query functions centralized in one module
        to avoid scattering inline SQL across services.

See Also:
    [BaseService][bigbrotr.core.base_service.BaseService]: Abstract base
        class that all services extend.
    [Brotr][bigbrotr.core.brotr.Brotr]: Database facade consumed by all
        query functions in this package.
"""
