"""Shared infrastructure for the BigBrotr service layer.

Provides the common building blocks used across the runtime services:
configuration models, mixins, paging helpers, read-core infrastructure, and
shared state/query utilities.

Attributes:
    configs: Per-network Pydantic configuration models plus shared
        public-adapter config contracts
        ([ClearnetConfig][bigbrotr.services.common.configs.ClearnetConfig],
        [TorConfig][bigbrotr.services.common.configs.TorConfig],
        [I2pConfig][bigbrotr.services.common.configs.I2pConfig],
        [LokiConfig][bigbrotr.services.common.configs.LokiConfig],
        [PublicReadAdapterConfig][bigbrotr.services.common.configs.PublicReadAdapterConfig])
        with sensible defaults for timeouts, proxy URLs, max concurrent tasks,
        and public-surface exposure policy validation.
    mixins: [NetworkSemaphoresMixin][bigbrotr.services.common.mixins.NetworkSemaphoresMixin]
        for per-network concurrency control.
    paging: Keyset-pagination helpers for bounded page scans in service
        query modules.
    read_models: Shared read core, readable-resource registry, and
        stable transport-query helpers used by the public adapters.
    discovery_queries: Seeder/Finder candidate-registration helpers.

See Also:
    [BaseService][bigbrotr.core.base_service.BaseService]: Abstract base
        class that all services extend.
    [Brotr][bigbrotr.core.brotr.Brotr]: Database facade consumed by all
        query functions in this package.
"""
