"""Built-in service registry for CLI and deployment wiring."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple


if TYPE_CHECKING:
    from bigbrotr.core.base_service import BaseService


CONFIG_BASE = Path("config")


class ServiceEntry(NamedTuple):
    """Registry entry mapping a service id to a lazy class reference and config path."""

    service_module: str
    service_class_name: str
    config_path: Path

    def load_class(self) -> type[BaseService[Any]]:
        """Import and return the configured service class."""
        module = importlib.import_module(self.service_module)
        loaded = getattr(module, self.service_class_name)
        if not isinstance(loaded, type):
            raise TypeError(f"{self.service_module}.{self.service_class_name} is not a class")
        return loaded


SERVICE_REGISTRY: dict[str, ServiceEntry] = {
    "seeder": ServiceEntry(
        service_module="bigbrotr.services.seeder",
        service_class_name="Seeder",
        config_path=CONFIG_BASE / "services" / "seeder.yaml",
    ),
    "finder": ServiceEntry(
        service_module="bigbrotr.services.finder",
        service_class_name="Finder",
        config_path=CONFIG_BASE / "services" / "finder.yaml",
    ),
    "validator": ServiceEntry(
        service_module="bigbrotr.services.validator",
        service_class_name="Validator",
        config_path=CONFIG_BASE / "services" / "validator.yaml",
    ),
    "monitor": ServiceEntry(
        service_module="bigbrotr.services.monitor",
        service_class_name="Monitor",
        config_path=CONFIG_BASE / "services" / "monitor.yaml",
    ),
    "refresher": ServiceEntry(
        service_module="bigbrotr.services.refresher",
        service_class_name="Refresher",
        config_path=CONFIG_BASE / "services" / "refresher.yaml",
    ),
    "ranker": ServiceEntry(
        service_module="bigbrotr.services.ranker",
        service_class_name="Ranker",
        config_path=CONFIG_BASE / "services" / "ranker.yaml",
    ),
    "synchronizer": ServiceEntry(
        service_module="bigbrotr.services.synchronizer",
        service_class_name="Synchronizer",
        config_path=CONFIG_BASE / "services" / "synchronizer.yaml",
    ),
    "api": ServiceEntry(
        service_module="bigbrotr.services.api",
        service_class_name="Api",
        config_path=CONFIG_BASE / "services" / "api.yaml",
    ),
    "dvm": ServiceEntry(
        service_module="bigbrotr.services.dvm",
        service_class_name="Dvm",
        config_path=CONFIG_BASE / "services" / "dvm.yaml",
    ),
    "assertor": ServiceEntry(
        service_module="bigbrotr.services.assertor",
        service_class_name="Assertor",
        config_path=CONFIG_BASE / "services" / "assertor.yaml",
    ),
}
