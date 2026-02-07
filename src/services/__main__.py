"""CLI entry point for BigBrotr services.

Provides a unified command-line interface to run any BigBrotr service.
Services can run in one-shot mode (``--once``) or continuously with a
Prometheus metrics server.

Usage::

    python -m services <service> [options]

Examples::

    python -m services seeder --once
    python -m services finder --log-level DEBUG
    python -m services monitor --config yaml/services/monitor.yaml
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Any

from core import Brotr, start_metrics_server
from core.logger import Logger
from core.service import BaseService

from .finder import Finder
from .monitor import Monitor
from .seeder import Seeder
from .synchronizer import Synchronizer
from .validator import Validator


# =============================================================================
# Configuration
# =============================================================================

YAML_BASE = Path("yaml")
CORE_CONFIG = YAML_BASE / "core" / "brotr.yaml"

# Service registry: name -> (class, config_path)
SERVICE_REGISTRY: dict[str, tuple[type[BaseService[Any]], Path]] = {
    "seeder": (Seeder, YAML_BASE / "services" / "seeder.yaml"),
    "finder": (Finder, YAML_BASE / "services" / "finder.yaml"),
    "validator": (Validator, YAML_BASE / "services" / "validator.yaml"),
    "monitor": (Monitor, YAML_BASE / "services" / "monitor.yaml"),
    "synchronizer": (Synchronizer, YAML_BASE / "services" / "synchronizer.yaml"),
}

logger = Logger("cli")


# =============================================================================
# Service Runner
# =============================================================================


async def run_service(
    service_name: str,
    service_class: type[BaseService[Any]],
    brotr: Brotr,
    config_path: Path,
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
        config_path: Path to the service's YAML configuration file.
        once: If True, run a single cycle and exit. If False, run continuously.

    Returns:
        Exit code: 0 for success, 1 for failure.
    """
    if config_path.exists():
        service = service_class.from_yaml(str(config_path), brotr=brotr)
    else:
        logger.warning("config_not_found", path=str(config_path))
        service = service_class(brotr=brotr)

    # One-shot mode: single cycle, no metrics server
    if once:
        try:
            await service.run()
            logger.info(f"{service_name}_completed")
            return 0
        except Exception as e:
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
    def handle_signal(sig: int, _frame: object) -> None:
        sig_name = signal.Signals(sig).name
        logger.info("shutdown_signal", signal=sig_name)
        service.request_shutdown()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        async with service:
            await service.run_forever()
        return 0
    except Exception as e:
        logger.error(f"{service_name}_failed", error=str(e))
        return 1
    finally:
        await metrics_server.stop()
        if metrics_config.enabled:
            logger.info("metrics_server_stopped")


# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the service runner."""
    parser = argparse.ArgumentParser(
        prog="python -m services",
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
        help="Service config path (default: yaml/services/<service>.yaml)",
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
    """Configure the root logger with the specified level and format."""
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_brotr(config_path: Path) -> Brotr:
    """Load and return a Brotr instance from a YAML config file."""
    if config_path.exists():
        return Brotr.from_yaml(str(config_path))

    logger.warning("brotr_config_not_found", path=str(config_path))
    return Brotr()


async def main() -> int:
    """Main entry point: parse args, initialize Brotr, and run the service."""
    args = parse_args()
    setup_logging(args.log_level)

    service_class, default_config_path = SERVICE_REGISTRY[args.service]
    config_path = args.config if args.config else default_config_path
    brotr = load_brotr(args.brotr_config)

    try:
        async with brotr:
            return await run_service(
                service_name=args.service,
                service_class=service_class,
                brotr=brotr,
                config_path=config_path,
                once=args.once,
            )
    except ConnectionError as e:
        logger.error("connection_failed", error=str(e))
        return 1
    except KeyboardInterrupt:
        logger.info("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
