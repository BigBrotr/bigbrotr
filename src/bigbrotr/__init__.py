r"""BigBrotr -- Modular Nostr data archiving and monitoring system.

Eight independent async services discover, monitor, and archive data from
the Nostr relay network, communicating exclusively through a shared
PostgreSQL database.

Architecture follows a **diamond DAG** dependency structure where imports
flow strictly downward:

```text
              services         Business logic and orchestration
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
    services: Business logic. Eight independent services.

Note:
    For lightweight usage, import directly from subpackages::

        from bigbrotr.models import Relay
        from bigbrotr.core import Brotr

    Top-level imports (``from bigbrotr import Relay``) use lazy loading
    and resolve on first access.
"""

import importlib
from importlib.metadata import version as _get_version


__version__ = _get_version("bigbrotr")

__all__ = [
    "Api",
    "ApiConfig",
    "BaseService",
    "Brotr",
    "BrotrConfig",
    "ConfigT",
    "Dvm",
    "DvmConfig",
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
    "Refresher",
    "RefresherConfig",
    "Relay",
    "RelayMetadata",
    "Seeder",
    "SeederConfig",
    "Synchronizer",
    "SynchronizerConfig",
    "Validator",
    "ValidatorConfig",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "BaseService": ("bigbrotr.core", "BaseService"),
    "Brotr": ("bigbrotr.core", "Brotr"),
    "BrotrConfig": ("bigbrotr.core", "BrotrConfig"),
    "ConfigT": ("bigbrotr.core", "ConfigT"),
    "Logger": ("bigbrotr.core", "Logger"),
    "Pool": ("bigbrotr.core", "Pool"),
    "PoolConfig": ("bigbrotr.core", "PoolConfig"),
    "Event": ("bigbrotr.models", "Event"),
    "EventRelay": ("bigbrotr.models", "EventRelay"),
    "Metadata": ("bigbrotr.models", "Metadata"),
    "MetadataType": ("bigbrotr.models", "MetadataType"),
    "NetworkType": ("bigbrotr.models", "NetworkType"),
    "Relay": ("bigbrotr.models", "Relay"),
    "RelayMetadata": ("bigbrotr.models", "RelayMetadata"),
    "Nip11": ("bigbrotr.nips", "Nip11"),
    "Nip66": ("bigbrotr.nips", "Nip66"),
    "Api": ("bigbrotr.services", "Api"),
    "ApiConfig": ("bigbrotr.services", "ApiConfig"),
    "Dvm": ("bigbrotr.services", "Dvm"),
    "DvmConfig": ("bigbrotr.services", "DvmConfig"),
    "Finder": ("bigbrotr.services", "Finder"),
    "FinderConfig": ("bigbrotr.services", "FinderConfig"),
    "Monitor": ("bigbrotr.services", "Monitor"),
    "MonitorConfig": ("bigbrotr.services", "MonitorConfig"),
    "Refresher": ("bigbrotr.services", "Refresher"),
    "RefresherConfig": ("bigbrotr.services", "RefresherConfig"),
    "Seeder": ("bigbrotr.services", "Seeder"),
    "SeederConfig": ("bigbrotr.services", "SeederConfig"),
    "Synchronizer": ("bigbrotr.services", "Synchronizer"),
    "SynchronizerConfig": ("bigbrotr.services", "SynchronizerConfig"),
    "Validator": ("bigbrotr.services", "Validator"),
    "ValidatorConfig": ("bigbrotr.services", "ValidatorConfig"),
}


def __getattr__(name: str) -> object:
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(module_path)
        value = getattr(module, attr_name)
        globals()[name] = value  # Cache for subsequent access
        return value
    raise AttributeError(f"module 'bigbrotr' has no attribute {name!r}")


def __dir__() -> list[str]:
    return __all__
