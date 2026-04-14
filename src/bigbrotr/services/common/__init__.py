"""Shared infrastructure for all BigBrotr services.

Provides the foundational building blocks used across all eight
services: configuration models, mixins, and centralized SQL query functions.

Attributes:
    configs: Per-network Pydantic configuration models
        ([ClearnetConfig][bigbrotr.services.common.configs.ClearnetConfig],
        [TorConfig][bigbrotr.services.common.configs.TorConfig],
        [I2pConfig][bigbrotr.services.common.configs.I2pConfig],
        [LokiConfig][bigbrotr.services.common.configs.LokiConfig]) with
        sensible defaults for timeouts, proxy URLs, and max concurrent tasks.
    mixins: [NetworkSemaphoresMixin][bigbrotr.services.common.mixins.NetworkSemaphoresMixin]
        for per-network concurrency control, and
        [GeoReaders][bigbrotr.services.common.mixins.GeoReaders] for GeoIP
        database reader lifecycle management.
    artifact_store: Typed persistence boundary for metadata-backed artifacts
        on ``metadata`` and ``relay_metadata`` tables.
    read_models: Static registry of built-in read models currently exposed by
        API and DVM compatibility surfaces.
    queries: Batch insert and service-state upsert helpers.

See Also:
    [BaseService][bigbrotr.core.base_service.BaseService]: Abstract base
        class that all services extend.
    [Brotr][bigbrotr.core.brotr.Brotr]: Database facade consumed by all
        query functions in this package.
"""
