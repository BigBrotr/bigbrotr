"""Synchronizer service for archiving events from non-priority Nostr relays.

This service continuously fetches and archives events from all readable Nostr relays,
excluding those in the priority relay list. It uses a multi-process, multi-threaded
architecture to maximize throughput while respecting resource constraints.

Service Architecture:
    - Main loop: Fetches relay list and distributes work
    - Worker processes: Each process spawns multiple worker threads
    - Worker threads: Each thread processes relays from a shared queue
    - Per-thread resources: Each thread has its own event loop and database connection pool

Event Synchronization:
    - Resumes from last seen event per relay (or starts from configured timestamp)
    - Uses binary search algorithm to handle gaps in relay event history
    - Filters events based on configurable criteria (kinds, authors, etc.)
    - Batches inserts for efficiency

Configuration:
    - SYNCHRONIZER_START_TIMESTAMP: Starting timestamp (0=genesis, -1=resume)
    - SYNCHRONIZER_STOP_TIMESTAMP: End timestamp (-1=continuous)
    - SYNCHRONIZER_EVENT_FILTER: JSON filter for event kinds/authors/tags
    - SYNCHRONIZER_NUM_CORES: Number of worker processes
    - SYNCHRONIZER_REQUESTS_PER_CORE: Number of threads per process
    - SYNCHRONIZER_RELAY_METADATA_THRESHOLD_HOURS: Only sync relays with recent metadata

Dependencies:
    - brotr: Database wrapper for async operations
    - nostr_tools: Nostr protocol client and event structures
    - multiprocessing: Process-level parallelism
    - threading: Thread-level parallelism within processes
"""
import asyncio
import logging
import signal
from multiprocessing import Event
from typing import List

from nostr_tools import Relay

from brotr_core.services.base_synchronizer import main_loop_base
from shared.config.config import load_synchronizer_config
from shared.utils.constants import HEALTH_CHECK_PORT
from shared.utils.functions import wait_for_services
from shared.utils.healthcheck import HealthCheckServer
from shared.utils.logging_config import setup_logging
from src.relay_loader import fetch_relays_from_database, fetch_relays_from_file

# Setup logging
setup_logging("SYNCHRONIZER")

# Global shutdown event (thread-safe across processes)
shutdown_event = Event()
service_ready_event = asyncio.Event()


def signal_handler(signum: int, frame) -> None:
    """Handle shutdown signals gracefully."""
    signal_name = signal.Signals(signum).name
    logging.info(f"⚠️ Received {signal_name} signal. Initiating graceful shutdown...")
    shutdown_event.set()


async def main_loop(config: dict) -> None:
    """Main processing loop for synchronizer."""
    # Fetch readable relays from database
    relays = await fetch_relays_from_database(
        config,
        threshold_hours=config["relay_metadata_threshold_hours"],
        readable_only=True
    )

    # Exclude priority relays
    priority_relays = await fetch_relays_from_file(config["priority_relays_path"])
    priority_relay_urls: List[str] = [relay.url for relay in priority_relays]

    # Filter out priority relays
    filtered_relays = [relay for relay in relays if relay.url not in priority_relay_urls]

    # Delegate to base implementation
    await main_loop_base(
        config,
        filtered_relays,
        shutdown_event,
        operation_name="event_sync"
    )


async def synchronizer() -> None:
    """Synchronizer service entry point."""
    config = load_synchronizer_config()
    logging.info("🔄 Starting Synchronizer...")

    # Start health check server
    async def is_ready():
        return service_ready_event.is_set()

    health_server = HealthCheckServer(port=HEALTH_CHECK_PORT, ready_check=is_ready)
    await health_server.start()

    try:
        await wait_for_services(config)
        service_ready_event.set()

        while not shutdown_event.is_set():
            try:
                logging.info("🔄 Starting main loop...")
                await main_loop(config)
                logging.info("✅ Main loop completed successfully.")

                # Sleep in small intervals to respond quickly to shutdown signals
                sleep_seconds = config["loop_interval_minutes"] * 60
                logging.info(f"⏳ Waiting {config['loop_interval_minutes']} minutes before next run...")

                for _ in range(sleep_seconds):
                    if shutdown_event.is_set():
                        break
                    await asyncio.sleep(1)

            except Exception as e:
                if not shutdown_event.is_set():
                    logging.exception(f"❌ Main loop failed: {e}")

    finally:
        await health_server.stop()
        logging.info("✅ Synchronizer shutdown complete.")


if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        asyncio.run(synchronizer())
    except KeyboardInterrupt:
        logging.info("⚠️ Received keyboard interrupt.")
    except Exception:
        import sys
        logging.exception("❌ Synchronizer failed to start.")
        sys.exit(1)
