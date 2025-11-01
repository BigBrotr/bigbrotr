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
    SECONDS_PER_DAY,
    WORKER_GRACEFUL_SHUTDOWN_TIMEOUT,
    WORKER_FORCE_SHUTDOWN_TIMEOUT,
    NetworkType
)
from functions import wait_for_services, connect_bigbrotr_with_retry, RelayFailureTracker
from healthcheck import HealthCheckServer
from logging_config import setup_logging
from process_relay import get_start_time_async, process_relay
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


# --- Worker Thread Function ---
def priority_relay_worker_thread(config: Dict[str, Any], shared_queue: Queue, end_time: int) -> None:
    """Worker thread that processes priority relays from queue.

    Creates one database connection pool and one event loop per thread,
    reusing them across all relays processed by this thread.
    """
    # Create failure tracker for this thread
    failure_tracker = RelayFailureTracker(alert_threshold=0.1, check_interval=100)

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
                socks5_proxy_url=socks5_proxy_url if relay.network == NetworkType.TOR else None
            )

            # Create filter based on config
            filter_dict = config["event_filter"].copy()
            filter_dict["since"] = start_time
            filter_dict["until"] = end_time
            filter_dict["limit"] = config["batch_size"]

            event_filter = Filter(**filter_dict)

            # Process relay events with timeout
            logging.info(
                f"🔄 Processing priority relay {relay.url} from {start_time} to {end_time}")

            # Set a timeout for the entire relay processing
            relay_timeout = config["timeout"] * RELAY_TIMEOUT_MULTIPLIER
            await asyncio.wait_for(
                process_relay(bigbrotr, client, event_filter),
                timeout=relay_timeout
            )

            logging.info(f"✅ Completed processing priority relay {relay.url}")
            failure_tracker.record_success()

        except asyncio.TimeoutError:
            failure_tracker.record_failure()
            logging.warning(
                f"⏰ Timeout while processing priority relay (exceeded {relay_timeout}s)",
                extra={
                    "relay_url": relay.url,
                    "relay_network": relay.network,
                    "operation": "event_sync_priority",
                    "timeout_seconds": relay_timeout
                }
            )
        except Exception as e:
            failure_tracker.record_failure()
            logging.exception(
                f"❌ Error processing priority relay: {e}",
                extra={
                    "relay_url": relay.url,
                    "relay_network": relay.network,
                    "operation": "event_sync_priority"
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
        # Log final stats
        stats = failure_tracker.get_stats()
        if stats['total'] > 0:
            logging.info(
                f"📊 Thread final stats: {stats['successes']}/{stats['total']} successful "
                f"({stats['failure_rate']:.1%} failure rate)"
            )
        # Cleanup: close database connection pool and event loop
        loop.run_until_complete(bigbrotr.close())
        loop.close()


# --- Process Worker Function ---
def priority_relay_processor_worker(config: Dict[str, Any], shared_queue: Queue, end_time: int, num_threads: int) -> None:
    """Spawn multiple threads to process priority relays from queue."""
    threads: List[threading.Thread] = []
    for _ in range(num_threads):
        t = threading.Thread(
            target=priority_relay_worker_thread,
            args=(config, shared_queue, end_time)
        )
        t.start()
        threads.append(t)
    for t in threads:
        t.join()


# --- Main Loop ---
async def main_loop(config: Dict[str, Any]) -> None:
    """Main processing loop for priority synchronizer."""
    relays = await fetch_relays_from_file(config["priority_relays_path"])
    num_cores: int = config["num_cores"]
    requests_per_core: int = config["requests_per_core"]

    end_time: int
    if config["stop_timestamp"] != -1:
        end_time = config["stop_timestamp"]
    else:
        end_time = int(time.time()) - SECONDS_PER_DAY

    shared_queue: Queue = Queue()
    for relay in relays:
        shared_queue.put(relay)

    logging.info(f"📦 {shared_queue.qsize()} priority relays to process.")
    processes: List[Process] = []
    for _ in range(num_cores):
        p = Process(
            target=priority_relay_processor_worker,
            args=(config, shared_queue, end_time, requests_per_core)
        )
        p.start()
        processes.append(p)

    # Wait for all processes to complete gracefully
    for p in processes:
        p.join(timeout=WORKER_GRACEFUL_SHUTDOWN_TIMEOUT)

    # Terminate any remaining processes
    for p in processes:
        if p.is_alive():
            logging.warning(f"⚠️ Process {p.pid} did not finish gracefully, terminating...")
            p.terminate()
            p.join(timeout=WORKER_FORCE_SHUTDOWN_TIMEOUT)


# --- Priority Synchronizer Entrypoint ---
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
