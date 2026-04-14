"""Built-in service registry for CLI and deployment wiring."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from .api import Api
from .assertor import Assertor
from .dvm import Dvm
from .finder import Finder
from .monitor import Monitor
from .ranker import Ranker
from .refresher import Refresher
from .seeder import Seeder
from .synchronizer import Synchronizer
from .validator import Validator


if TYPE_CHECKING:
    from bigbrotr.core.base_service import BaseService


CONFIG_BASE = Path("config")


class ServiceEntry(NamedTuple):
    """Registry entry mapping a service to its class and default config path."""

    cls: type[BaseService[Any]]
    config_path: Path


def _service_entry(service_class: type[BaseService[Any]]) -> tuple[str, ServiceEntry]:
    """Build a registry entry from a built-in service class."""
    service_name = str(service_class.SERVICE_NAME)
    return service_name, ServiceEntry(
        service_class,
        CONFIG_BASE / "services" / f"{service_name}.yaml",
    )


SERVICE_REGISTRY: dict[str, ServiceEntry] = dict(
    _service_entry(service_class)
    for service_class in (
        Seeder,
        Finder,
        Validator,
        Monitor,
        Refresher,
        Ranker,
        Synchronizer,
        Api,
        Dvm,
        Assertor,
    )
)
