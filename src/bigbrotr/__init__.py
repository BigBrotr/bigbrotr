r"""BigBrotr -- Modular Nostr data archiving and monitoring system.

Five async services form a processing pipeline that discovers, monitors,
and archives data from the Nostr relay network:

```text
Seeder (one-shot) -> Finder -> Validator -> Monitor -> Synchronizer
```

Architecture follows a **diamond DAG** dependency structure where imports
flow strictly downward:

```text
              services         Business logic and pipeline orchestration
             /   |   \
          core  nips  utils    Infrastructure, protocol, and helpers
             \   |   /
              models           Pure frozen dataclasses (zero I/O)
```

Attributes:
    models: Pure frozen dataclasses. Zero I/O, depends only on stdlib.
    core: Connection pool, database facade, base service, exceptions,
        logging, metrics.
    nips: NIP-11 relay information, NIP-66 relay monitoring. Has I/O.
    utils: DNS resolution, Nostr key management, WebSocket/HTTP transport.
    services: Business logic. The five-service pipeline.
"""

__version__ = "5.0.1"

from bigbrotr.core import (
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
    PoolRetryConfig,
    PoolTimeoutsConfig,
    ServerSettingsConfig,
)
from bigbrotr.models import (
    Event,
    EventRelay,
    Metadata,
    MetadataType,
    NetworkType,
    Relay,
    RelayMetadata,
)
from bigbrotr.nips import Nip11, Nip66
from bigbrotr.services import (
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
    "PoolRetryConfig",
    "PoolTimeoutsConfig",
    "Relay",
    "RelayMetadata",
    "Seeder",
    "SeederConfig",
    "ServerSettingsConfig",
    "Synchronizer",
    "SynchronizerConfig",
    "Validator",
    "ValidatorConfig",
]
