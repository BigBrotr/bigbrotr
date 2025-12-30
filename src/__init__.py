"""
BigBrotr - A modular Nostr data archiving and monitoring system.

Three-layer architecture:
    models: First-class types (Relay, Event, EventRelay, Nip11, Nip66, etc.)
    core: Foundation components (Pool, Brotr, BaseService, Logger)
    services: Service implementations (Initializer, Finder, Validator, Monitor, Synchronizer)

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
from .models import (
    Event,
    EventRelay,
    Keys,
    Nip11,
    Nip66,
    Relay,
    RelayMetadata,
)

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

# Services
from .services import (
    Finder,
    FinderConfig,
    Initializer,
    InitializerConfig,
    InitializerError,
    Monitor,
    MonitorConfig,
    Synchronizer,
    SynchronizerConfig,
    Validator,
    ValidatorConfig,
)

__all__ = [
    # Models
    "Event",
    "EventRelay",
    "Keys",
    "Nip11",
    "Nip66",
    "Relay",
    "RelayMetadata",
    # Core - Base
    "BaseService",
    "ConfigT",
    "Logger",
    # Core - Pool
    "DatabaseConfig",
    "Pool",
    "PoolConfig",
    "PoolLimitsConfig",
    "PoolTimeoutsConfig",
    "RetryConfig",
    "ServerSettingsConfig",
    # Core - Brotr
    "BatchConfig",
    "Brotr",
    "BrotrConfig",
    "BrotrTimeoutsConfig",
    # Services
    "Finder",
    "FinderConfig",
    "Initializer",
    "InitializerConfig",
    "InitializerError",
    "Monitor",
    "MonitorConfig",
    "Synchronizer",
    "SynchronizerConfig",
    "Validator",
    "ValidatorConfig",
]
