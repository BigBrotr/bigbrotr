"""Base synchronizer for shared event archiving logic.

This module provides the common base class for both the regular synchronizer and
priority synchronizer services. It eliminates code duplication by extracting shared
functionality into reusable components.

Shared Functionality:
    - Worker thread creation and management
    - Relay event processing logic
    - Process pool coordination
    - Health check integration
    - Graceful shutdown handling

Architecture Pattern:
    - Template Method Pattern: Subclasses override specific methods for customization
    - Strategy Pattern: Relay source fetching is delegated to subclasses
    - Dependency Injection: Configuration and dependencies passed to constructors

Dependencies:
    - brotr: Database wrapper for async operations
    - nostr_tools: Nostr protocol client and event structures
    - multiprocessing: Process-level parallelism
    - threading: Thread-level parallelism within processes
"""
import asyncio
import logging
import time
from multiprocessing import Queue, Process
from typing import Dict, Any, List, Optional
from queue import Empty

from brotr_core.database.brotr import Brotr
from nostr_tools import Relay, Client, Filter

from shared.utils.constants import (
    DB_POOL_MIN_SIZE_PER_WORKER,
    DB_POOL_MAX_SIZE_PER_WORKER,
    RELAY_TIMEOUT_MULTIPLIER,
    SECONDS_PER_DAY,
    WORKER_GRACEFUL_SHUTDOWN_TIMEOUT,
    WORKER_FORCE_SHUTDOWN_TIMEOUT,
    DEFAULT_RELAY_REQUESTS_PER_SECOND,
    DEFAULT_RELAY_BURST_SIZE,
    NetworkType
)
from shared.utils.functions import connect_brotr_with_retry, RelayFailureTracker
from src.process_relay import get_start_time_async, RelayProcessor
from brotr_core.services.rate_limiter import RelayRateLimiter

__all__ = [
    'BaseSynchronizerWorker',
    'worker_thread',
    'main_loop_base'
]


class BaseSynchronizerWorker:
    """Base worker for processing relays from a shared queue.

    This class encapsulates the logic for a single worker thread that processes
    relays from a queue. It can be subclassed to customize logging messages and
    operation names.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        shared_queue: Queue,
        end_time: int,
        shutdown_event: Any,
        operation_name: str = "event_sync",
        rate_limiter: Optional[RelayRateLimiter] = None
    ):
        """Initialize worker.

        Args:
            config: Configuration dictionary
            shared_queue: Queue containing relays to process
            end_time: End timestamp for event synchronization
            shutdown_event: Multiprocessing Event for shutdown signaling
            operation_name: Name for logging (e.g., "event_sync", "event_sync_priority")
            rate_limiter: Optional rate limiter for relay connections
        """
        self.config = config
        self.shared_queue = shared_queue
        self.end_time = end_time
        self.shutdown_event = shutdown_event
        self.operation_name = operation_name
        self.failure_tracker = RelayFailureTracker(alert_threshold=0.1, check_interval=100)
        self.rate_limiter = rate_limiter or RelayRateLimiter(
            requests_per_second=DEFAULT_RELAY_REQUESTS_PER_SECOND,
            burst_size=DEFAULT_RELAY_BURST_SIZE
        )

    async def process_single_relay(
        self,
        brotr: Brotr,
        relay: Relay,
        end_time: int
    ) -> None:
        """Process a single relay with timeout and rate limiting.

        Args:
            brotr: Database connection
            relay: Relay to process
            end_time: End timestamp for event synchronization
        """
        try:
            # Apply rate limiting before processing
            await self.rate_limiter.acquire(relay.url)

            # Get start time from database
            start_time = await get_start_time_async(
                self.config["start_timestamp"],
                bigbrotr,
                relay
            )

            # Create client with Tor proxy if needed
            socks5_proxy_url = f"socks5://{self.config['torproxy_host']}:{self.config['torproxy_port']}"
            client = Client(
                relay=relay,
                timeout=self.config["timeout"],
                socks5_proxy_url=socks5_proxy_url if relay.network == NetworkType.TOR else None
            )

            # Create filter based on config
            filter_dict = self.config["event_filter"].copy()
            filter_dict["since"] = start_time
            filter_dict["until"] = end_time
            filter_dict["limit"] = self.config["batch_size"]

            event_filter = Filter(**filter_dict)

            # Process relay events with timeout
            self._log_processing_start(relay, start_time, end_time)

            # Create processor and process relay
            processor = RelayProcessor(bigbrotr, client, event_filter)
            relay_timeout = self.config["timeout"] * RELAY_TIMEOUT_MULTIPLIER
            await asyncio.wait_for(
                processor.process(),
                timeout=relay_timeout
            )

            self._log_processing_success(relay)
            self.failure_tracker.record_success()

        except asyncio.TimeoutError:
            self.failure_tracker.record_failure()
            relay_timeout = self.config["timeout"] * RELAY_TIMEOUT_MULTIPLIER
            logging.warning(
                f"⏰ Timeout while processing relay (exceeded {relay_timeout}s)",
                extra={
                    "relay_url": relay.url,
                    "relay_network": relay.network,
                    "operation": self.operation_name,
                    "timeout_seconds": relay_timeout
                }
            )
        except Exception as e:
            self.failure_tracker.record_failure()
            logging.exception(
                f"❌ Error processing relay: {e}",
                extra={
                    "relay_url": relay.url,
                    "relay_network": relay.network,
                    "operation": self.operation_name
                }
            )

    def _log_processing_start(self, relay: Relay, start_time: int, end_time: int) -> None:
        """Log relay processing start. Can be overridden by subclasses."""
        logging.info(
            f"🔄 Processing relay {relay.url} from {start_time} to {end_time}"
        )

    def _log_processing_success(self, relay: Relay) -> None:
        """Log relay processing success. Can be overridden by subclasses."""
        logging.info(f"✅ Completed processing relay {relay.url}")

    def run(self) -> None:
        """Run worker thread (synchronous entry point)."""
        # Create event loop once for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Create database connection pool once for this thread
        bigbrotr = Brotr(
            self.config["database_host"],
            self.config["database_port"],
            self.config["database_user"],
            self.config["database_password"],
            self.config["database_name"],
            min_pool_size=DB_POOL_MIN_SIZE_PER_WORKER,
            max_pool_size=DB_POOL_MAX_SIZE_PER_WORKER
        )

        try:
            # Connect database pool with retry logic
            loop.run_until_complete(
                connect_brotr_with_retry(bigbrotr, logging=logging)
            )

            # Process relays from queue
            while not self.shutdown_event.is_set():
                try:
                    relay = self.shared_queue.get(timeout=1)
                except Empty:
                    break
                except Exception as e:
                    logging.exception(f"❌ Error reading from shared queue: {e}")
                    continue

                # Reuse bigbrotr and event loop for each relay
                loop.run_until_complete(
                    self.process_single_relay(bigbrotr, relay, self.end_time)
                )
        finally:
            # Log final stats
            stats = self.failure_tracker.get_stats()
            if stats['total'] > 0:
                logging.info(
                    f"📊 Thread final stats: {stats['successes']}/{stats['total']} successful "
                    f"({stats['failure_rate']:.1%} failure rate)"
                )
            # Cleanup: close database connection pool and event loop
            loop.run_until_complete(bigbrotr.close())
            loop.close()


def relay_worker_thread(
    config: Dict[str, Any],
    shared_queue: Queue,
    end_time: int,
    shutdown_event: Any,
    operation_name: str = "event_sync"
) -> None:
    """Worker thread function (entry point for threading.Thread).

    Args:
        config: Configuration dictionary
        shared_queue: Queue containing relays to process
        end_time: End timestamp for event synchronization
        shutdown_event: Multiprocessing Event for shutdown signaling
        operation_name: Name for logging
    """
    worker = BaseSynchronizerWorker(
        config,
        shared_queue,
        end_time,
        shutdown_event,
        operation_name
    )
    worker.run()


def relay_processor_worker(
    config: Dict[str, Any],
    shared_queue: Queue,
    end_time: int,
    shutdown_event: Any,
    num_threads: int,
    operation_name: str = "event_sync"
) -> None:
    """Process worker function - spawns multiple threads.

    Args:
        config: Configuration dictionary
        shared_queue: Queue containing relays to process
        end_time: End timestamp for event synchronization
        shutdown_event: Multiprocessing Event for shutdown signaling
        num_threads: Number of worker threads to spawn
        operation_name: Name for logging
    """
    import threading

    threads: List[threading.Thread] = []
    for _ in range(num_threads):
        t = threading.Thread(
            target=relay_worker_thread,
            args=(config, shared_queue, end_time, shutdown_event, operation_name)
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()


async def main_loop_base(
    config: Dict[str, Any],
    relays: List[Relay],
    shutdown_event: Any,
    operation_name: str = "event_sync"
) -> None:
    """Base main processing loop for synchronizers.

    Args:
        config: Configuration dictionary
        relays: List of relays to process
        shutdown_event: Multiprocessing Event for shutdown signaling
        operation_name: Name for logging
    """
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

    logging.info(f"📦 {shared_queue.qsize()} relays to process.")
    processes: List[Process] = []
    for _ in range(num_cores):
        p = Process(
            target=relay_processor_worker,
            args=(config, shared_queue, end_time, shutdown_event, requests_per_core, operation_name)
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
