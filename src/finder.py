import asyncio
import logging
import signal
from multiprocessing import Event
from types import FrameType
from typing import Optional

from config import load_finder_config
from constants import HEALTH_CHECK_PORT
from functions import wait_for_services
from healthcheck import HealthCheckServer
from logging_config import setup_logging

# Setup logging
setup_logging("FINDER")

# Global shutdown event (thread-safe across processes)
shutdown_event = Event()
service_ready = False


def signal_handler(signum: int, frame: Optional[FrameType]) -> None:
    """Handle shutdown signals gracefully."""
    signal_name = signal.Signals(signum).name
    logging.info(f"⚠️ Received {signal_name} signal. Initiating graceful shutdown...")
    shutdown_event.set()


# --- Finder Entrypoint ---
async def finder() -> None:
    """Finder service entry point."""
    global service_ready

    config = load_finder_config()
    logging.info("🔍 Starting finder...")

    # Tor proxy configuration for accessing .onion relay aggregator websites
    # and discovering relays from Tor network sources

    # Start health check server
    async def is_ready():
        return service_ready

    health_server = HealthCheckServer(port=HEALTH_CHECK_PORT, ready_check=is_ready)
    await health_server.start()

    try:
        await wait_for_services(config)
        service_ready = True

        while not shutdown_event.is_set():
            try:
                logging.info("🔍 Starting relay discovery...")

                # TODO: Implement relay discovery logic:
                # 1. Query database for specific event kinds (e.g., kind 10002 relay list metadata)
                # 2. Extract relay URLs from event tags (e.g., 'r' tags and other relay references)
                # 3. Fetch relay lists from aggregator websites (e.g., nostr.watch, relay.exchange)
                # 4. Parse and validate all discovered relay URLs
                # 5. Insert new relays to database using bigbrotr.insert_relay_batch()

                logging.info("📋 Relay discovery logic pending implementation")

                # Sleep in small intervals to respond quickly to shutdown signals
                sleep_seconds = config["frequency_hour"] * 3600
                logging.info(f"⏳ Waiting {config['frequency_hour']} hours before next run...")

                for _ in range(sleep_seconds):
                    if shutdown_event.is_set():
                        break
                    await asyncio.sleep(1)

            except Exception as e:
                if not shutdown_event.is_set():
                    logging.exception(f"❌ Finder encountered an error: {e}")

    finally:
        await health_server.stop()
        logging.info("✅ Finder shutdown complete.")


if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        asyncio.run(finder())
    except KeyboardInterrupt:
        logging.info("⚠️ Received keyboard interrupt.")
    except Exception:
        import sys
        logging.exception("❌ Finder failed to start.")
        sys.exit(1)
