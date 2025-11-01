"""Priority Synchronizer service for archiving events from high-priority Nostr relays.

This service is dedicated to archiving events from a curated list of high-priority relays
defined in priority_relays.txt. It operates independently from the main synchronizer to
ensure critical relays receive dedicated resources and guaranteed processing time.

Service Architecture:
    - Main loop: Fetches priority relay list and distributes work
    - Worker processes: Each process spawns multiple worker threads
    - Worker threads: Each thread processes relays from a shared queue
    - Per-thread resources: Each thread has its own event loop and database connection pool

Why Separate Priority Synchronizer:
    - Guaranteed resources: Priority relays always get processed
    - Isolated failures: Issues with general relays don't affect priority relay sync
    - Different scheduling: Can run on different intervals/configurations
    - Performance isolation: Priority relay performance not impacted by slow general relays

Event Synchronization:
    - Resumes from last seen event per relay (or starts from configured timestamp)
    - Uses binary search algorithm to handle gaps in relay event history
    - Filters events based on configurable criteria (kinds, authors, etc.)
    - Batches inserts for efficiency

Configuration:
    - SYNCHRONIZER_PRIORITY_RELAYS_PATH: Path to priority relays file
    - SYNCHRONIZER_START_TIMESTAMP: Starting timestamp (0=genesis, -1=resume)
    - SYNCHRONIZER_STOP_TIMESTAMP: End timestamp (-1=continuous)
    - SYNCHRONIZER_EVENT_FILTER: JSON filter for event kinds/authors/tags
    - SYNCHRONIZER_NUM_CORES: Number of worker processes
    - SYNCHRONIZER_REQUESTS_PER_CORE: Number of threads per process

Dependencies:
    - bigbrotr: Database wrapper for async operations
    - nostr_tools: Nostr protocol client and event structures
    - multiprocessing: Process-level parallelism
    - threading: Thread-level parallelism within processes
"""
import asyncio
import logging
import signal
from multiprocessing import Event

from base_synchronizer import main_loop_base
from config import load_synchronizer_config
from constants import HEALTH_CHECK_PORT
from functions import wait_for_services
from healthcheck import HealthCheckServer
from logging_config import setup_logging
from relay_loader import fetch_relays_from_file

# Setup logging
setup_logging("PRIORITY_SYNCHRONIZER")

# Global shutdown flag
shutdown_event = Event()
service_ready_event = asyncio.Event()


def signal_handler(signum: int, frame) -> None:
    """Handle shutdown signals gracefully."""
    # No global needed, using Event()
    signal_name = signal.Signals(signum).name
    logging.info(f"⚠️ Received {signal_name} signal. Initiating graceful shutdown...")
    shutdown_event.set()


async def main_loop(config: dict) -> None:
    """Main processing loop for priority synchronizer."""
    # Fetch priority relays from file
    relays = await fetch_relays_from_file(config["priority_relays_path"])

    # Delegate to base implementation
    await main_loop_base(
        config,
        relays,
        shutdown_event,
        operation_name="event_sync_priority"
    )


async def priority_synchronizer() -> None:
    """Priority synchronizer service entry point."""
    config = load_synchronizer_config()
    logging.info("🔄 Starting Priority Synchronizer...")

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
        logging.info("✅ Priority Synchronizer shutdown complete.")


if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        asyncio.run(priority_synchronizer())
    except KeyboardInterrupt:
        logging.info("⚠️ Received keyboard interrupt.")
    except Exception:
        import sys
        logging.exception("❌ Priority Synchronizer failed to start.")
        sys.exit(1)
