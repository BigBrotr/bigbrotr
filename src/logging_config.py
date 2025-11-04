"""Centralized logging configuration for all BigBrotr services."""
import logging
import sys


def setup_logging(service_name: str, level: str = "INFO") -> None:
    """Configure logging for a BigBrotr service.

    Args:
        service_name: Name of the service (e.g., "monitor", "synchronizer")
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format=f"%(asctime)s - {service_name} - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    # Reduce noise from aiohttp
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
