import asyncio
import logging
import signal
import threading
import time
from multiprocessing import Queue, Process, Event
from queue import Empty
from typing import Dict, Any, List

from bigbrotr import Bigbrotr
from nostr_tools import Relay, Client, Filter

from config import load_synchronizer_config
from constants import (
    DB_POOL_MIN_SIZE_PER_WORKER,
    DB_POOL_MAX_SIZE_PER_WORKER,
    HEALTH_CHECK_PORT,
    RELAY_TIMEOUT_MULTIPLIER,
    SECONDS_PER_DAY
)
from functions import wait_for_services, connect_bigbrotr_with_retry
from healthcheck import HealthCheckServer
from logging_config import setup_logging
from process_relay import get_start_time_async, process_relay
from relay_loader import fetch_relays_from_database, fetch_relays_from_file

# Setup logging
setup_logging("SYNCHRONIZER")

# Global shutdown event (thread-safe across processes)
shutdown_event = Event()
service_ready = False


def signal_handler(signum: int, frame) -> None:
    """Handle shutdown signals gracefully."""
    signal_name = signal.Signals(signum).name
    logging.info(f"⚠️ Received {signal_name} signal. Initiating graceful shutdown...")
    shutdown_event.set()


# --- Thread Function ---
def relay_worker_thread(config: Dict[str, Any], shared_queue: Queue, end_time: int) -> None:
    """Worker thread that processes relays from queue.

    Creates one database connection pool and one event loop per thread,
    reusing them across all relays processed by this thread.
    """
    async def run_with_timeout(bigbrotr: Bigbrotr, relay: Relay, end_time: int) -> None:
        """Process a single relay with timeout."""
        try:
            # Get start time from database
            start_time = await get_start_time_async(config["start_timestamp"], bigbrotr, relay)

            # Create client with Tor proxy if needed
            socks5_proxy_url = f"socks5://{config['torproxy_host']}:{config['torproxy_port']}"
            client = Client(
                relay=relay,
                timeout=config["timeout"],
                socks5_proxy_url=socks5_proxy_url if relay.network == "tor" else None
            )

            # Create filter based on config
            filter_dict = config["event_filter"].copy()
            filter_dict["since"] = start_time
            filter_dict["until"] = end_time
            filter_dict["limit"] = config["batch_size"]

            event_filter = Filter(**filter_dict)

            # Process relay events with timeout
            logging.info(
                f"🔄 Processing relay {relay.url} from {start_time} to {end_time}")

            # Set a timeout for the entire relay processing
            relay_timeout = config["timeout"] * RELAY_TIMEOUT_MULTIPLIER
            await asyncio.wait_for(
                process_relay(bigbrotr, client, event_filter),
                timeout=relay_timeout
            )

            logging.info(f"✅ Completed processing relay {relay.url}")

        except asyncio.TimeoutError:
            logging.warning(
                f"⏰ Timeout while processing relay (exceeded {relay_timeout}s)",
                extra={
                    "relay_url": relay.url,
                    "relay_network": relay.network,
                    "operation": "event_sync",
                    "timeout_seconds": relay_timeout
                }
            )
        except Exception as e:
            logging.exception(
                f"❌ Error processing relay: {e}",
                extra={
                    "relay_url": relay.url,
                    "relay_network": relay.network,
                    "operation": "event_sync"
                }
            )

    # Create event loop once for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Create database connection pool once for this thread
    bigbrotr = Bigbrotr(
        config["database_host"],
        config["database_port"],
        config["database_user"],
        config["database_password"],
        config["database_name"],
        min_pool_size=DB_POOL_MIN_SIZE_PER_WORKER,
        max_pool_size=DB_POOL_MAX_SIZE_PER_WORKER
    )

    try:
        # Connect database pool with retry logic
        loop.run_until_complete(connect_bigbrotr_with_retry(bigbrotr, logging=logging))

        # Process relays from queue
        while not shutdown_event.is_set():
            try:
                relay = shared_queue.get(timeout=1)
            except Empty:
                break
            except Exception as e:
                logging.exception(f"❌ Error reading from shared queue: {e}")
                continue

            # Reuse bigbrotr and event loop for each relay
            loop.run_until_complete(run_with_timeout(bigbrotr, relay, end_time))
    finally:
        # Cleanup: close database connection pool and event loop
        loop.run_until_complete(bigbrotr.close())
        loop.close()


# --- Process Function ---
def relay_processor_worker(config: Dict[str, Any], shared_queue: Queue, end_time: int) -> None:
    """Spawn multiple threads to process relays from queue."""
    request_per_core: int = config["requests_per_core"]
    threads: List[threading.Thread] = []
    for _ in range(request_per_core):
        t = threading.Thread(
            target=relay_worker_thread,
            args=(config, shared_queue, end_time)
        )
        t.start()
        threads.append(t)
    for t in threads:
        t.join()


# --- Main Loop ---
async def main_loop(config: Dict[str, Any]) -> None:
    """Main processing loop for synchronizer."""
    relays = await fetch_relays_from_database(
        config,
        threshold_hours=config["relay_metadata_threshold_hours"],
        readable_only=True
    )
    priority_relays = await fetch_relays_from_file(config["priority_relays_path"])
    priority_relay_urls: List[str] = [relay.url for relay in priority_relays]
    num_cores: int = config["num_cores"]

    end_time: int
    if config["stop_timestamp"] != -1:
        end_time = config["stop_timestamp"]
    else:
        end_time = int(time.time()) - SECONDS_PER_DAY

    shared_queue: Queue = Queue()
    for relay in relays:
        if relay.url not in priority_relay_urls:
            shared_queue.put(relay)

    logging.info(f"📦 {shared_queue.qsize()} relays to process.")
    processes: List[Process] = []
    for _ in range(num_cores):
        p = Process(
            target=relay_processor_worker,
            args=(config, shared_queue, end_time)
        )
        p.start()
        processes.append(p)
    for p in processes:
        p.join()


# --- Synchronizer Entrypoint ---
async def synchronizer() -> None:
    """Synchronizer service entry point."""
    global service_ready

    config = load_synchronizer_config()
    logging.info("🔄 Starting Synchronizer...")

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
