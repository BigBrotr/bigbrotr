"""CLI entry point for BigBrotr services.

Provides a unified command-line interface to run any BigBrotr service.
Services can run in one-shot mode (``--once``) or continuously with a
Prometheus metrics server.

Examples:
    ```bash
    python -m bigbrotr <service> [options]
    python -m bigbrotr seeder --once
    python -m bigbrotr finder --log-level DEBUG
    python -m bigbrotr monitor --config config/services/monitor.yaml
    ```
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Any, NamedTuple

from bigbrotr.core import Brotr, start_metrics_server
from bigbrotr.core.base_service import BaseService
from bigbrotr.core.logger import Logger, StructuredFormatter
from bigbrotr.core.yaml import load_yaml
from bigbrotr.models.constants import ServiceName
from bigbrotr.services.api import Api
from bigbrotr.services.dvm import Dvm
from bigbrotr.services.finder import Finder
from bigbrotr.services.monitor import Monitor
from bigbrotr.services.refresher import Refresher
from bigbrotr.services.seeder import Seeder
from bigbrotr.services.synchronizer import Synchronizer
from bigbrotr.services.validator import Validator


CONFIG_BASE = Path("config")
CORE_CONFIG = CONFIG_BASE / "brotr.yaml"


class ServiceEntry(NamedTuple):
    """Registry entry mapping a service to its class and default config path."""

    cls: type[BaseService[Any]]
    config_path: Path


SERVICE_REGISTRY: dict[str, ServiceEntry] = {
    ServiceName.SEEDER: ServiceEntry(Seeder, CONFIG_BASE / "services" / "seeder.yaml"),
    ServiceName.FINDER: ServiceEntry(Finder, CONFIG_BASE / "services" / "finder.yaml"),
    ServiceName.VALIDATOR: ServiceEntry(Validator, CONFIG_BASE / "services" / "validator.yaml"),
    ServiceName.MONITOR: ServiceEntry(Monitor, CONFIG_BASE / "services" / "monitor.yaml"),
    ServiceName.REFRESHER: ServiceEntry(Refresher, CONFIG_BASE / "services" / "refresher.yaml"),
    ServiceName.SYNCHRONIZER: ServiceEntry(
        Synchronizer, CONFIG_BASE / "services" / "synchronizer.yaml"
    ),
    ServiceName.API: ServiceEntry(Api, CONFIG_BASE / "services" / "api.yaml"),
    ServiceName.DVM: ServiceEntry(Dvm, CONFIG_BASE / "services" / "dvm.yaml"),
}

logger = Logger("cli")


async def run_service(
    service_name: str,
    service_class: type[BaseService[Any]],
    brotr: Brotr,
    service_dict: dict[str, Any],
    *,
    once: bool,
) -> int:
    """Run a service in one-shot or continuous mode.

    In one-shot mode, the service runs a single cycle and exits.
    In continuous mode, a Prometheus metrics server is started and the
    service runs indefinitely until a shutdown signal is received.

    Args:
        service_name: Service identifier used for logging.
        service_class: The BaseService subclass to instantiate.
        brotr: Initialized Brotr database interface.
        service_dict: Parsed service configuration (without ``pool`` key).
        once: If True, run a single cycle and exit. If False, run continuously.

    Returns:
        Exit code: 0 for success, 1 for failure.
    """
    if service_dict:
        service = service_class.from_dict(service_dict, brotr=brotr)
    else:
        service = service_class(brotr=brotr)

    # One-shot mode: single cycle, no metrics server
    if once:
        try:
            async with service:
                await service.run()
            logger.info(f"{service_name}_completed")
            return 0
        except Exception as e:  # Intentionally broad: CLI error boundary for one-shot mode
            logger.error(f"{service_name}_failed", error=str(e))
            return 1

    # Continuous mode: metrics server + indefinite operation
    metrics_config = service.config.metrics
    metrics_server = await start_metrics_server(metrics_config)

    if metrics_config.enabled:
        logger.info(
            "metrics_server_started",
            host=metrics_config.host,
            port=metrics_config.port,
            path=metrics_config.path,
        )

    # Signal handling for graceful shutdown
    def handle_signal(sig: signal.Signals) -> None:
        logger.info("shutdown_signal", signal=sig.name)
        service.request_shutdown()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal, sig)

    try:
        async with service:
            await service.run_forever()
        return 0
    except Exception as e:  # Intentionally broad: CLI error boundary for continuous mode
        logger.error(f"{service_name}_failed", error=str(e))
        return 1
    finally:
        await metrics_server.stop()
        if metrics_config.enabled:
            logger.info("metrics_server_stopped")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the service runner."""
    parser = argparse.ArgumentParser(
        prog="bigbrotr",
        description="BigBrotr Service Runner",
    )

    parser.add_argument(
        "service",
        choices=list(SERVICE_REGISTRY.keys()),
        help="Service to run",
    )

    parser.add_argument(
        "--config",
        type=Path,
        help="Service config path (default: config/services/<service>.yaml)",
    )

    parser.add_argument(
        "--brotr-config",
        type=Path,
        default=CORE_CONFIG,
        help=f"Brotr config path (default: {CORE_CONFIG})",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Log level (default: INFO)",
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (default: run continuously)",
    )

    return parser.parse_args()


def setup_logging(level: str) -> None:
    """Configure the root logger with structured formatting.

    Installs a ``StructuredFormatter`` on the root handler so that all
    log output -- from both ``Logger`` (with ``structured_kv`` extra) and
    plain ``logging.getLogger()`` calls in models/utils -- is unified as
    ``level name message key=value ...``.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    logging.root.addHandler(handler)
    logging.root.setLevel(getattr(logging, level))


def _load_yaml_dict(path: Path) -> dict[str, Any]:
    """Load a YAML file as a dict, returning ``{}`` if the file does not exist."""
    if not path.exists():
        logger.warning("config_not_found", path=str(path))
        return {}
    return load_yaml(str(path))


def _apply_pool_overrides(
    brotr_dict: dict[str, Any],
    pool_overrides: dict[str, Any] | None,
    service_name: str,
) -> None:
    """Merge per-service pool overrides into the shared brotr configuration.

    Applies ``user``, ``password_env`` to ``pool.database``, ``min_size`` and
    ``max_size`` to ``pool.limits``, and auto-sets ``application_name`` to the
    service name (unless explicitly provided in overrides).
    """
    pool = brotr_dict.setdefault("pool", {})

    # Auto-set application_name to the service name
    server_settings = pool.setdefault("server_settings", {})
    if "application_name" not in server_settings:
        server_settings["application_name"] = service_name

    if not pool_overrides:
        return

    # Explicit application_name in overrides takes precedence
    if "application_name" in pool_overrides:
        server_settings["application_name"] = pool_overrides["application_name"]

    # Database-level overrides (user, password_env)
    db_keys = ("user", "password_env")
    db_overrides = {k: pool_overrides[k] for k in db_keys if k in pool_overrides}
    if db_overrides:
        pool.setdefault("database", {}).update(db_overrides)

    # Pool limits overrides (min_size, max_size)
    limits_keys = ("min_size", "max_size")
    limits_overrides = {k: pool_overrides[k] for k in limits_keys if k in pool_overrides}
    if limits_overrides:
        pool.setdefault("limits", {}).update(limits_overrides)


async def main() -> int:
    """Main entry point: parse args, initialize Brotr, and run the service."""
    args = parse_args()
    setup_logging(args.log_level)

    entry = SERVICE_REGISTRY[args.service]
    config_path = args.config or entry.config_path

    brotr_dict = _load_yaml_dict(args.brotr_config)
    service_dict = _load_yaml_dict(config_path)
    pool_overrides = service_dict.pop("pool", None)
    _apply_pool_overrides(brotr_dict, pool_overrides, args.service)

    brotr = Brotr.from_dict(brotr_dict) if brotr_dict else Brotr()

    try:
        async with brotr:
            return await run_service(
                service_name=args.service,
                service_class=entry.cls,
                brotr=brotr,
                service_dict=service_dict,
                once=args.once,
            )
    except ConnectionError as e:
        logger.error("connection_failed", error=str(e))
        return 1
    except KeyboardInterrupt:
        logger.info("interrupted")
        return 130


def cli() -> None:
    """Synchronous entry point for console_scripts."""
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    cli()
