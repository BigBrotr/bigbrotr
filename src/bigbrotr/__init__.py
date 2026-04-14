r"""BigBrotr -- Modular Nostr network observatory.

Ten independent async services discover relays, validate connectivity,
perform NIP-11/NIP-66 health checks, archive events, refresh analytics views,
sync private ranking state, and expose data via REST API and NIP-90 Data
Vending Machine — across clearnet, Tor, I2P, and Lokinet. All services
communicate through a shared PostgreSQL database, while the ranker also keeps
private DuckDB state.

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
    services: Business logic. Ten independent services.

Note:
    For lightweight usage, import directly from subpackages::

        from bigbrotr.models import Relay
        from bigbrotr.core import Brotr

    Top-level imports (``from bigbrotr import Relay``) use lazy loading
    and resolve on first access.
"""

import importlib
import tomllib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _get_version
from pathlib import Path


def _source_tree_version(pyproject_path: Path | None = None) -> str | None:
    """Return the version declared in pyproject.toml when running from a source tree."""
    if pyproject_path is None:
        pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"

    if not pyproject_path.is_file():
        return None

    try:
        pyproject = tomllib.loads(pyproject_path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None

    project = pyproject.get("project")
    if not isinstance(project, dict):
        return None

    version = project.get("version")
    return version if isinstance(version, str) and version else None


def _resolve_version(pyproject_path: Path | None = None) -> str:
    """Resolve the package version without depending solely on runtime metadata."""
    source_version = _source_tree_version(pyproject_path)
    if source_version is not None:
        return source_version

    try:
        return _get_version("bigbrotr")
    except PackageNotFoundError:
        return "0+unknown"


__version__ = _resolve_version()

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
    "Ranker",
    "RankerConfig",
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
    "Ranker": ("bigbrotr.services", "Ranker"),
    "RankerConfig": ("bigbrotr.services", "RankerConfig"),
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
