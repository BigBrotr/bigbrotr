"""
BigBrotr - A modular Nostr data archiving and monitoring system.

Three-layer architecture:
    models: First-class types (Relay, Event, EventRelay, Nip11, Nip66, etc.)
    core: Foundation components (Pool, Brotr, BaseService, Logger)
    services: Service implementations (Seeder, Finder, Validator, Monitor, Synchronizer)

Example:
    from src import Brotr, Pool, Finder

    pool = Pool.from_yaml("config.yaml")
    brotr = Brotr(pool=pool)

    async with brotr:
        finder = Finder(brotr=brotr)
        await finder.run()
"""

__version__ = "2.0.0"

# Models
# Core
from .core import (
    BaseService,
    BatchConfig,
    Brotr,
    BrotrConfig,
    BrotrTimeoutsConfig,
    ConfigT,
    DatabaseConfig,
    Logger,
    Pool,
    PoolConfig,
    PoolLimitsConfig,
    PoolTimeoutsConfig,
    RetryConfig,
    ServerSettingsConfig,
)
from .models import (
    Event,
    EventRelay,
    Metadata,
    MetadataType,
    NetworkType,
    Nip11,
    Nip66,
    Relay,
    RelayMetadata,
)

# Services
from .services import (
    Finder,
    FinderConfig,
    Monitor,
    MonitorConfig,
    Seeder,
    SeederConfig,
    Synchronizer,
    SynchronizerConfig,
    Validator,
    ValidatorConfig,
)


__all__ = [
    "BaseService",
    "BatchConfig",
    "Brotr",
    "BrotrConfig",
    "BrotrTimeoutsConfig",
    "ConfigT",
    "DatabaseConfig",
    "Event",
    "EventRelay",
    "Finder",
    "FinderConfig",
    "Logger",
    "Metadata",
    "MetadataType",
    "Monitor",
    "MonitorConfig",
    "NetworkType",
    "Nip11",
    "Nip66",
    "Pool",
    "PoolConfig",
    "PoolLimitsConfig",
    "PoolTimeoutsConfig",
    "Relay",
    "RelayMetadata",
    "RetryConfig",
    "Seeder",
    "SeederConfig",
    "ServerSettingsConfig",
    "Synchronizer",
    "SynchronizerConfig",
    "Validator",
    "ValidatorConfig",
]
