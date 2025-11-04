import asyncio
import logging
import signal
import time
from multiprocessing import Pool, Event
from types import FrameType
from typing import Dict, Any, List, Optional

from bigbrotr import BigBrotr
from nostr_tools import Relay, Client, fetch_relay_metadata, RelayMetadata

from config import load_monitor_config
from constants import DB_POOL_MIN_SIZE_PER_WORKER, DB_POOL_MAX_SIZE_PER_WORKER, HEALTH_CHECK_PORT
from functions import chunkify, wait_for_services, connect_bigbrotr_with_retry, RelayFailureTracker
from healthcheck import HealthCheckServer
from logging_config import setup_logging
from relay_loader import fetch_relays_needing_metadata

# Setup logging
setup_logging("MONITOR")

# Global shutdown event (thread-safe across processes)
shutdown_event = Event()
service_ready = False


def signal_handler(signum: int, frame: Optional[FrameType]) -> None:
    """Handle shutdown signals gracefully."""
    signal_name = signal.Signals(signum).name
    logging.info(f"⚠️ Received {signal_name} signal. Initiating graceful shutdown...")
    shutdown_event.set()


# --- Process Relay Metadata ---
async def process_relay(config: Dict[str, Any], relay: Relay, generated_at: int) -> RelayMetadata:
    """Process a single relay and fetch its metadata.

    Args:
        config: Configuration dictionary with torproxy settings and keys
        relay: Relay object to fetch metadata from
        generated_at: Timestamp for when metadata was generated

    Returns:
        RelayMetadata object with nip11 and nip66 data
    """
    torproxy_host = config.get("torproxy_host")
    torproxy_port = config.get("torproxy_port")
    socks5_proxy_url = f"socks5://{torproxy_host}:{torproxy_port}"
    client = Client(
        relay=relay,
        timeout=config["timeout"],
        socks5_proxy_url=socks5_proxy_url if relay.network == "tor" else None
    )
    relay_metadata = await fetch_relay_metadata(
        client=client,
        sec=config.get("secret_key"),
        pub=config.get("public_key")
    )
    relay_metadata.generated_at = generated_at
    return relay_metadata


# --- Process Chunk ---
async def process_relay_chunk_for_metadata(chunk: List[Relay], config: Dict[str, Any], generated_at: int, bigbrotr: BigBrotr, failure_tracker: RelayFailureTracker) -> None:
    """Process a chunk of relays and save their metadata.

    Args:
        chunk: List of relays to process
        config: Configuration dictionary
        generated_at: Timestamp for metadata generation
        bigbrotr: Shared database connection (must be connected)
        failure_tracker: Tracker for monitoring relay processing failures
    """
    semaphore = asyncio.Semaphore(config["requests_per_core"])
    relay_metadata_list: List[RelayMetadata] = []

    async def sem_task(relay: Relay) -> RelayMetadata:
        async with semaphore:
            try:
                relay_metadata = await process_relay(config, relay, generated_at)
                # Check if we got any useful metadata (nip66 or nip11)
                if relay_metadata and (relay_metadata.nip66 or relay_metadata.nip11):
                    failure_tracker.record_success()
                    return relay_metadata
                else:
                    failure_tracker.record_failure()
            except Exception as e:
                failure_tracker.record_failure()
                logging.exception(
                    f"❌ Error processing relay: {e}",
                    extra={
                        "relay_url": relay.url,
                        "relay_network": relay.network,
                        "operation": "metadata_fetch"
                    }
                )
            return None

    tasks = [sem_task(relay) for relay in chunk]
    results = await asyncio.gather(*tasks)
    relay_metadata_list = [r for r in results if r is not None]

    # Use the shared connection instead of creating a new one
    await bigbrotr.insert_relay_metadata_batch(relay_metadata_list)

    logging.info(
        f"✅ Processed {len(chunk)} relays. Found {len(relay_metadata_list)} valid relay metadata.")


# --- Worker Function ---
def metadata_monitor_worker(chunk: List[Relay], config: Dict[str, Any], generated_at: int) -> None:
    """Worker function for multiprocessing pool.

    Each worker process creates its own database connection pool
    to avoid sharing connections across processes.

    Args:
        chunk: List of relays to process
        config: Configuration dictionary
        generated_at: Timestamp for metadata generation
    """
    async def worker_async(chunk: List[Relay], config: Dict[str, Any], generated_at: int) -> None:
        # Create a database connection for this worker process
        bigbrotr = BigBrotr(
            config["database_host"],
            config["database_port"],
            config["database_user"],
            config["database_password"],
            config["database_name"],
            min_pool_size=DB_POOL_MIN_SIZE_PER_WORKER,
            max_pool_size=DB_POOL_MAX_SIZE_PER_WORKER
        )
        # Connect with retry logic
        await connect_bigbrotr_with_retry(bigbrotr, logger=logging)

        # Create failure tracker for this worker
        failure_tracker = RelayFailureTracker(alert_threshold=0.1, check_interval=100)

        try:
            return await process_relay_chunk_for_metadata(chunk, config, generated_at, bigbrotr, failure_tracker)
        finally:
            # Log final stats
            stats = failure_tracker.get_stats()
            if stats['total'] > 0:
                logging.info(
                    f"📊 Worker final stats: {stats['successes']}/{stats['total']} successful "
                    f"({stats['failure_rate']:.1%} failure rate)"
                )
            await bigbrotr.close()

    # Create new event loop for this worker process
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        return loop.run_until_complete(worker_async(chunk, config, generated_at))
    finally:
        # Always close the loop we created
        loop.close()


# --- Main Loop ---
async def main_loop(config: Dict[str, Any]) -> None:
    """Main processing loop for monitoring relays."""
    relays = await fetch_relays_needing_metadata(config, config["frequency_hour"])
    chunk_size = config["chunk_size"]
    num_cores = config["num_cores"]
    chunks = list(chunkify(relays, chunk_size))
    generated_at = int(time.time())
    args = [(chunk, config, generated_at) for chunk in chunks]
    logging.info(
        f"🔄 Processing {len(chunks)} chunks with {num_cores} cores...")

    pool = Pool(processes=num_cores)
    try:
        pool.starmap(metadata_monitor_worker, args)
        logging.info(f"✅ All chunks processed successfully.")
    finally:
        pool.close()  # Prevent new tasks
        pool.join()  # Wait for workers to finish gracefully


# --- Monitor Entrypoint ---
async def monitor() -> None:
    """Monitor service entry point."""
    global service_ready

    config = load_monitor_config()
    logging.info("🔍 Starting monitor...")

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
        logging.info("✅ Monitor shutdown complete.")


if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        asyncio.run(monitor())
    except KeyboardInterrupt:
        logging.info("⚠️ Received keyboard interrupt.")
    except Exception:
        import sys
        logging.exception("❌ Monitor failed to start.")
        sys.exit(1)
