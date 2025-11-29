"""
BigBrotr Services CLI Entry Point.

Allows running services via: python -m services <service_name>

Usage:
    python -m services initializer              # Local development (localhost:5432)
    python -m services finder                   # Local development (localhost:5432)
    python -m services initializer --docker     # Docker direct (postgres:5432)
    python -m services finder --docker          # Docker direct (postgres:5432)
    python -m services finder --pgbouncer       # Docker via PGBouncer (pgbouncer:6432)

Configuration Philosophy:
    - ALL parameters come from YAML files (host, port, database, timeouts, etc.)
    - ONLY DB_PASSWORD comes from environment variable (sensitive data)
    - --docker flag: brotr.docker.yaml (host=postgres, port=5432)
    - --pgbouncer flag: brotr.pgbouncer.yaml (host=pgbouncer, port=6432)
"""

import argparse
import asyncio
import logging
import sys

from core.brotr import Brotr
from core.logger import configure_logging

_logger = logging.getLogger(__name__)

# Base path for YAML configs (set by Dockerfile: /app/yaml)
YAML_BASE = "yaml"


def get_brotr_config_path(docker: bool, pgbouncer: bool) -> str:
    """Get Brotr configuration file path based on environment."""
    if pgbouncer:
        return f"{YAML_BASE}/core/brotr.pgbouncer.yaml"
    if docker:
        return f"{YAML_BASE}/core/brotr.docker.yaml"
    return f"{YAML_BASE}/core/brotr.yaml"


def get_service_config_path(service_name: str) -> str:
    """Get configuration file path for a service."""
    return f"{YAML_BASE}/services/{service_name}.yaml"


async def run_initializer(docker: bool, pgbouncer: bool) -> int:
    """Run the Initializer service."""
    from services.initializer import Initializer

    brotr_config = get_brotr_config_path(docker, pgbouncer)
    service_config = get_service_config_path("initializer")

    # Create Brotr from YAML (password from DB_PASSWORD env)
    brotr = Brotr.from_yaml(brotr_config)

    async with brotr.pool:
        # base_path is "." since YAML is mounted at /app/yaml
        initializer = Initializer.from_yaml(service_config, brotr=brotr, base_path=".")
        result = await initializer.initialize()

        if result.success:
            _logger.info("Initialization completed: %d relays seeded", result.relays_seeded)
            return 0
        else:
            _logger.error("Initialization failed: %s", result.errors)
            return 1


async def run_finder(docker: bool, pgbouncer: bool) -> int:
    """Run the Finder service."""
    from services.finder import Finder

    brotr_config = get_brotr_config_path(docker, pgbouncer)
    service_config = get_service_config_path("finder")

    # Create Brotr from YAML (password from DB_PASSWORD env)
    brotr = Brotr.from_yaml(brotr_config)

    async with brotr.pool:
        finder = Finder.from_yaml(service_config, brotr=brotr)

        # Start the finder
        await finder.start()

        # Run discovery
        result = await finder.discover()

        # Stop the finder
        await finder.stop()

        if result.success:
            _logger.info("Discovery completed: %d new relays found", result.new_relays)
            return 0
        else:
            _logger.error("Discovery failed: %s", result.errors)
            return 1


SERVICE_RUNNERS = {
    "initializer": run_initializer,
    "finder": run_finder,
}


def main() -> int:
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

    # Connection mode (mutually exclusive)
    conn_group = parser.add_mutually_exclusive_group()
    conn_group.add_argument(
        "--docker",
        action="store_true",
        help="Docker direct connection (postgres:5432)",
    )
    conn_group.add_argument(
        "--pgbouncer",
        action="store_true",
        help="Docker via PGBouncer (pgbouncer:6432)",
    )

    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Log level (default: INFO)",
    )

    args = parser.parse_args()

    # Configure logging
    configure_logging(level=args.log_level, structured=True, console_output=True)

    # Run the service with connection flags
    runner = SERVICE_RUNNERS[args.service]
    return asyncio.run(runner(docker=args.docker, pgbouncer=args.pgbouncer))


if __name__ == "__main__":
    sys.exit(main())
