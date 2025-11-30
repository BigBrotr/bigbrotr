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

from .finder import Finder, FinderConfig
from .initializer import Initializer
from .monitor import Monitor, MonitorConfig
from .synchronizer import Synchronizer, SynchronizerConfig
from .priority_synchronizer import PrioritySynchronizer, PrioritySynchronizerConfig


# =============================================================================
# Configuration
# =============================================================================

YAML_BASE = Path("yaml")
CORE_CONFIG = YAML_BASE / "core" / "brotr.yaml"

SERVICE_CONFIGS = {
    "initializer": YAML_BASE / "services" / "initializer.yaml",
    "finder": YAML_BASE / "services" / "finder.yaml",
    "monitor": YAML_BASE / "services" / "monitor.yaml",
    "synchronizer": YAML_BASE / "services" / "synchronizer.yaml",
    "priority_synchronizer": YAML_BASE / "services" / "priority_synchronizer.yaml",
}

logger = Logger("cli")


# =============================================================================
# Service Runners
# =============================================================================


async def run_initializer(brotr: Brotr, config_path: Path) -> int:
    """Run initializer service (one-shot)."""
    if config_path.exists():
        service = Initializer.from_yaml(str(config_path), brotr=brotr)
    else:
        logger.warning("config_not_found", path=str(config_path))
        service = Initializer(brotr=brotr)

    try:
        await service.run()
        logger.info("initializer_completed")
        return 0
    except Exception as e:
        logger.error("initializer_failed", error=str(e))
        return 1


async def run_finder(brotr: Brotr, config_path: Path) -> int:
    """Run finder service (continuous)."""
    if config_path.exists():
        service = Finder.from_yaml(str(config_path), brotr=brotr)
    else:
        logger.warning("config_not_found", path=str(config_path))
        service = Finder(brotr=brotr)

    config: FinderConfig = service.config

    def handle_signal(sig: int, _frame: object) -> None:
        sig_name = signal.Signals(sig).name
        logger.info("shutdown_signal", signal=sig_name)
        service.request_shutdown()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        async with service:
            await service.run_forever(interval=config.discovery_interval)
        return 0
    except Exception as e:
        logger.error("finder_failed", error=str(e))
        return 1


async def run_monitor(brotr: Brotr, config_path: Path) -> int:
    """Run monitor service (continuous)."""
    if config_path.exists():
        service = Monitor.from_yaml(str(config_path), brotr=brotr)
    else:
        logger.warning("config_not_found", path=str(config_path))
        service = Monitor(brotr=brotr)

    config: MonitorConfig = service.config

    def handle_signal(sig: int, _frame: object) -> None:
        sig_name = signal.Signals(sig).name
        logger.info("shutdown_signal", signal=sig_name)
        service.request_shutdown()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        async with service:
            await service.run_forever(interval=config.monitor_interval)
        return 0
    except Exception as e:
        logger.error("monitor_failed", error=str(e))
        return 1


async def run_synchronizer(brotr: Brotr, config_path: Path) -> int:
    """Run synchronizer service (continuous)."""
    if config_path.exists():
        service = Synchronizer.from_yaml(str(config_path), brotr=brotr)
    else:
        logger.warning("config_not_found", path=str(config_path))
        service = Synchronizer(brotr=brotr)

    config: SynchronizerConfig = service.config

    def handle_signal(sig: int, _frame: object) -> None:
        sig_name = signal.Signals(sig).name
        logger.info("shutdown_signal", signal=sig_name)
        service.request_shutdown()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        async with service:
            await service.run_forever(interval=config.sync_interval)
        return 0
    except Exception as e:
        logger.error("synchronizer_failed", error=str(e))
        return 1


async def run_priority_synchronizer(brotr: Brotr, config_path: Path) -> int:
    """Run priority synchronizer service (continuous)."""
    if config_path.exists():
        service = PrioritySynchronizer.from_yaml(str(config_path), brotr=brotr)
    else:
        logger.warning("config_not_found", path=str(config_path))
        service = PrioritySynchronizer(brotr=brotr)

    config: PrioritySynchronizerConfig = service.config

    def handle_signal(sig: int, _frame: object) -> None:
        sig_name = signal.Signals(sig).name
        logger.info("shutdown_signal", signal=sig_name)
        service.request_shutdown()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        async with service:
            await service.run_forever(interval=config.sync_interval)
        return 0
    except Exception as e:
        logger.error("priority_synchronizer_failed", error=str(e))
        return 1


SERVICE_RUNNERS = {
    "initializer": run_initializer,
    "finder": run_finder,
    "monitor": run_monitor,
    "synchronizer": run_synchronizer,
    "priority_synchronizer": run_priority_synchronizer,
}


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
        choices=list(SERVICE_RUNNERS.keys()),
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

    # Resolve service config path
    config_path = args.config if args.config else SERVICE_CONFIGS[args.service]

    # Load brotr
    brotr = load_brotr(args.brotr_config)

    # Run service
    runner = SERVICE_RUNNERS[args.service]

    try:
        async with brotr.pool:
            return await runner(brotr, config_path)
    except ConnectionError as e:
        logger.error("connection_failed", error=str(e))
        return 1
    except KeyboardInterrupt:
        logger.info("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
