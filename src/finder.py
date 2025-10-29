import asyncio
import logging
import signal

from config import load_finder_config
from constants import HEALTH_CHECK_PORT
from functions import wait_for_services
from healthcheck import HealthCheckServer
from logging_config import setup_logging

# Setup logging
setup_logging("FINDER")

# Global shutdown flag
shutdown_flag = False
service_ready = False


def signal_handler(signum: int, frame) -> None:
    """Handle shutdown signals gracefully."""
    global shutdown_flag
    signal_name = signal.Signals(signum).name
    logging.info(f"⚠️ Received {signal_name} signal. Initiating graceful shutdown...")
    shutdown_flag = True


# --- Finder Entrypoint ---
async def finder() -> None:
    """Finder service entry point."""
    global shutdown_flag, service_ready

    config = load_finder_config()
    logging.info("🔍 Starting finder...")

    # Start health check server
    async def is_ready():
        return service_ready

    health_server = HealthCheckServer(port=HEALTH_CHECK_PORT, ready_check=is_ready)
    await health_server.start()

    try:
        await wait_for_services(config)
        service_ready = True

        while not shutdown_flag:
            try:
                logging.info("🔍 Starting relay discovery...")

                # TODO: Implement comprehensive relay discovery:
                # 1. Fetch kind 10002 events (relay list metadata) from known relays
                # 2. Parse NIP-11 documents for relay cross-references
                # 3. Extract relay URLs from event tags
                # 4. Validate and insert new relays to database

                # For now, just log that discovery would run
                logging.info("📋 Relay discovery not yet fully implemented")
                logging.info("💡 Future implementation will:")
                logging.info("   - Query kind 10002 events from existing relays")
                logging.info("   - Parse relay references from NIP-11 metadata")
                logging.info("   - Extract 'r' tags from events")
                logging.info("   - Discover relays from relay list events")

                # Sleep in small intervals to respond quickly to shutdown signals
                sleep_seconds = config["frequency_hour"] * 3600
                logging.info(f"⏳ Waiting {config['frequency_hour']} hours before next run...")

                for _ in range(sleep_seconds):
                    if shutdown_flag:
                        break
                    await asyncio.sleep(1)

            except Exception as e:
                if not shutdown_flag:
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
