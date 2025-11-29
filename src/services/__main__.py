"""
CLI Entry Point for BigBrotr Services.

Usage:
    python -m services <service_name> [options]

Examples:
    python -m services initializer
    python -m services finder --config yaml/services/finder.yaml
    python -m services finder --log-level DEBUG

Configuration:
    - Service configs: yaml/services/<service>.yaml
    - Pool config: yaml/core/brotr.yaml
    - Password: DB_PASSWORD environment variable
"""

import argparse
import asyncio
import signal
import sys
from pathlib import Path

from core import Pool, configure_logging, get_logger
from core.brotr import Brotr

from .finder import Finder
from .initializer import Initializer


logger = get_logger("cli", component="ServiceRunner")

# Default config paths
YAML_BASE = "yaml"


def get_pool_config_path() -> str:
    """Get pool configuration file path."""
    return f"{YAML_BASE}/core/brotr.yaml"


def get_service_config_path(service_name: str) -> str:
    """Get service configuration file path."""
    return f"{YAML_BASE}/services/{service_name}.yaml"


async def run_initializer(pool: Pool, config_path: str) -> int:
    """Run initializer service (one-shot)."""
    path = Path(config_path)
    if path.exists():
        initializer = Initializer.from_yaml(str(path), pool=pool)
    else:
        logger.warning("config_not_found", path=str(path))
        initializer = Initializer(pool=pool)

    result = await initializer.run()

    if result.success:
        logger.info(
            "initializer_completed",
            relays_seeded=result.metrics.get("relays_seeded", 0),
        )
        return 0
    else:
        logger.error("initializer_failed", errors=result.errors)
        return 1


async def run_finder(pool: Pool, config_path: str) -> int:
    """Run finder service (continuous)."""
    brotr = Brotr(pool=pool)

    path = Path(config_path)
    if path.exists():
        finder = Finder.from_yaml(str(path), pool=pool, brotr=brotr)
    else:
        logger.warning("config_not_found", path=str(path))
        finder = Finder(pool=pool, brotr=brotr)

    # Setup graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler(sig, frame):
        logger.info("shutdown_requested", signal=sig)
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        async with finder:
            interval = finder.config.discovery_interval

            while not shutdown_event.is_set():
                result = await finder.run()
                logger.info(
                    "discovery_cycle",
                    success=result.success,
                    relays_found=result.metrics.get("relays_found", 0),
                    duration_s=round(result.duration_s, 2),
                )

                # Wait for next cycle or shutdown
                try:
                    await asyncio.wait_for(
                        shutdown_event.wait(),
                        timeout=interval,
                    )
                    break
                except asyncio.TimeoutError:
                    continue

    except Exception as e:
        logger.error("finder_error", error=str(e))
        return 1

    logger.info("finder_stopped")
    return 0


SERVICE_RUNNERS = {
    "initializer": run_initializer,
    "finder": run_finder,
}


async def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="BigBrotr Service Runner",
        prog="python -m services",
    )
    parser.add_argument(
        "service",
        choices=list(SERVICE_RUNNERS.keys()),
        help="Service to run",
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to service config YAML (default: yaml/services/<service>.yaml)",
    )
    parser.add_argument(
        "--pool-config",
        type=str,
        help="Path to pool config YAML (default: yaml/core/brotr.yaml)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )

    args = parser.parse_args()

    # Configure logging
    configure_logging(level=args.log_level)

    # Resolve config paths
    pool_config_path = args.pool_config or get_pool_config_path()
    service_config_path = args.config or get_service_config_path(args.service)

    # Load pool
    pool_path = Path(pool_config_path)
    if pool_path.exists():
        pool = Pool.from_yaml(str(pool_path))
    else:
        logger.warning("pool_config_not_found", path=str(pool_path))
        pool = Pool()

    # Run service
    try:
        async with pool:
            runner = SERVICE_RUNNERS[args.service]
            return await runner(pool, service_config_path)

    except ConnectionError as e:
        logger.error("connection_error", error=str(e))
        return 1
    except Exception as e:
        logger.exception("fatal_error", error=str(e))
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))