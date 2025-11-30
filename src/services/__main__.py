"""
CLI Entry Point for BigBrotr Services.

Usage:
    python -m services <service> [options]

Examples:
    python -m services initializer
    python -m services finder
    python -m services finder --log-level DEBUG
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from core import Brotr, Logger
from core.base_service import BaseService

from .finder import Finder
from .initializer import Initializer
from .monitor import Monitor
from .synchronizer import Synchronizer

# =============================================================================
# Configuration
# =============================================================================

YAML_BASE = Path("yaml")
CORE_CONFIG = YAML_BASE / "core" / "brotr.yaml"

# Service registry: name -> (class, config_path, is_oneshot)
SERVICE_REGISTRY: dict[str, tuple[type[BaseService], Path, bool]] = {
    "initializer": (Initializer, YAML_BASE / "services" / "initializer.yaml", True),
    "finder": (Finder, YAML_BASE / "services" / "finder.yaml", False),
    "monitor": (Monitor, YAML_BASE / "services" / "monitor.yaml", False),
    "synchronizer": (Synchronizer, YAML_BASE / "services" / "synchronizer.yaml", False),
}

logger = Logger("cli")


# =============================================================================
# Service Runner
# =============================================================================


async def run_service(
    service_name: str,
    service_class: type[BaseService],
    brotr: Brotr,
    config_path: Path,
    is_oneshot: bool,
) -> int:
    """
    Generic service runner.

    Args:
        service_name: Name of the service (for logging)
        service_class: Service class to instantiate
        brotr: Brotr instance
        config_path: Path to service config file
        is_oneshot: If True, run once; if False, run continuously

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    # Create service instance
    if config_path.exists():
        service = service_class.from_yaml(str(config_path), brotr=brotr)
    else:
        logger.warning("config_not_found", path=str(config_path))
        service = service_class(brotr=brotr)

    # One-shot services (like initializer) run once and exit
    if is_oneshot:
        try:
            await service.run()
            logger.info(f"{service_name}_completed")
            return 0
        except Exception as e:
            logger.error(f"{service_name}_failed", error=str(e))
            return 1

    # Continuous services need signal handling
    def handle_signal(sig: int, _frame: object) -> None:
        sig_name = signal.Signals(sig).name
        logger.info("shutdown_signal", signal=sig_name)
        service.request_shutdown()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        async with service:
            await service.run_forever(interval=service.config.interval)
        return 0
    except Exception as e:
        logger.error(f"{service_name}_failed", error=str(e))
        return 1


# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
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

    return parser.parse_args()


def setup_logging(level: str) -> None:
    """Configure logging."""
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_brotr(config_path: Path) -> Brotr:
    """Load Brotr from config file."""
    if config_path.exists():
        return Brotr.from_yaml(str(config_path))

    logger.warning("brotr_config_not_found", path=str(config_path))
    return Brotr()


async def main() -> int:
    """Main entry point."""
    args = parse_args()
    setup_logging(args.log_level)

    # Get service info from registry
    service_class, default_config_path, is_oneshot = SERVICE_REGISTRY[args.service]
    config_path = args.config if args.config else default_config_path

    # Load brotr
    brotr = load_brotr(args.brotr_config)

    # Run service
    try:
        async with brotr.pool:
            return await run_service(
                service_name=args.service,
                service_class=service_class,
                brotr=brotr,
                config_path=config_path,
                is_oneshot=is_oneshot,
            )
    except ConnectionError as e:
        logger.error("connection_failed", error=str(e))
        return 1
    except KeyboardInterrupt:
        logger.info("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
