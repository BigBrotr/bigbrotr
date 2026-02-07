"""
BigBrotr - Modular Nostr data archiving and monitoring system.

Provides relay discovery, health monitoring (NIP-11/NIP-66), and event
synchronization with multi-network support (clearnet, Tor, I2P, Lokinet).

Architecture layers (bottom to top):
    models:   Data types (Relay, Event, EventRelay, Metadata, Nip11, Nip66)
    utils:    Shared utilities (NetworkConfig, KeysConfig, YAML loading, transport)
    core:     Foundation (Pool, Brotr, BaseService, Logger, MetricsServer)
    services: Implementations (Seeder, Finder, Validator, Monitor, Synchronizer)

Example:
    from src import Brotr, Pool, Finder

    pool = Pool.from_yaml("config.yaml")
    brotr = Brotr(pool=pool)

    async with brotr:
        finder = Finder(brotr=brotr)
        await finder.run()
"""

__version__ = "3.0.3"

# Core layer: connection pooling, database interface, base service, logging
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

# Models layer: domain types and database-mapped dataclasses
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

# Services layer: long-running service implementations with configurations
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
