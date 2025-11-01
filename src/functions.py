"""Shared utility functions for Bigbrotr services.

This module provides common utility functions used across all Bigbrotr services,
including chunking, connection testing, retry logic, and failure tracking.

Key Components:
    - chunkify: Split iterables into fixed-size chunks for parallel processing
    - RelayFailureTracker: Monitor and alert on relay processing failure rates
    - wait_for_services: Wait for dependent services (database, Tor proxy) to be ready
    - connect_bigbrotr_with_retry: Retry logic for database connection establishment
    - test_tor_connectivity: Verify Tor proxy is working for both HTTP and WebSocket

Dependencies:
    - bigbrotr: Database wrapper for async operations
    - aiohttp: HTTP client for connectivity testing
    - aiohttp_socks: SOCKS5 proxy support for Tor connections
"""
from typing import Generator, List, TypeVar, Optional, Any, Dict

import asyncio
import logging

from aiohttp import ClientSession, WSMsgType
from aiohttp_socks import ProxyConnector

from bigbrotr import Bigbrotr
from constants import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BASE_DELAY,
    DEFAULT_DB_RETRY_DELAY,
    DEFAULT_FAILURE_THRESHOLD,
    DEFAULT_FAILURE_CHECK_INTERVAL,
    DEFAULT_TORPROXY_TIMEOUT,
    TOR_CHECK_HTTP_URL,
    TOR_CHECK_WS_URL
)
from db_error_handler import is_transient_db_error, is_permanent_db_error

T = TypeVar('T')


class RelayFailureTracker:
    """Track relay processing failures and alert on high failure rates.

    This class maintains statistics on relay processing success/failure rates
    and emits alerts when failure rates exceed configured thresholds.
    """

    def __init__(self, alert_threshold: float = DEFAULT_FAILURE_THRESHOLD, check_interval: int = DEFAULT_FAILURE_CHECK_INTERVAL):
        """Initialize failure tracker.

        Args:
            alert_threshold: Failure rate threshold for alerts (default: 10%)
            check_interval: Check failure rate every N relays (default: 100)
        """
        self.total = 0
        self.failures = 0
        self.alert_threshold = alert_threshold
        self.check_interval = check_interval

    def record_success(self) -> None:
        """Record successful relay processing."""
        self.total += 1
        self._check_and_alert()

    def record_failure(self) -> None:
        """Record failed relay processing."""
        self.total += 1
        self.failures += 1
        self._check_and_alert()

    def _check_and_alert(self) -> None:
        """Check failure rate and emit alert if threshold exceeded."""
        if self.total >= self.check_interval and self.total % self.check_interval == 0:
            failure_rate = self.failures / self.total
            if failure_rate > self.alert_threshold:
                logging.error(
                    f"🚨 High relay failure rate detected: {failure_rate:.1%} "
                    f"({self.failures}/{self.total} relays failed)"
                )
            else:
                logging.info(
                    f"📊 Relay processing stats: {failure_rate:.1%} failure rate "
                    f"({self.total - self.failures}/{self.total} successful)"
                )

    def get_stats(self) -> Dict[str, Any]:
        """Get current failure statistics.

        Returns:
            Dictionary with total, failures, successes, and failure_rate
        """
        return {
            'total': self.total,
            'failures': self.failures,
            'successes': self.total - self.failures,
            'failure_rate': self.failures / self.total if self.total > 0 else 0.0
        }


def chunkify(lst: List[T], n: int) -> Generator[List[T], None, None]:
    """Split a list into chunks of size n."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


async def test_database_connection_async(
    host: str,
    port: int,
    user: str,
    password: str,
    dbname: str,
    logging: Optional[Any] = None
) -> bool:
    """Test database connection asynchronously."""
    try:
        async with Bigbrotr(host, port, user, password, dbname) as db:
            # Try a simple query to verify connection
            await db.fetch("SELECT 1")
            if logging:
                logging.info("✅ Database connection successful.")
            return True
    except Exception:
        if logging:
            logging.exception("❌ Database connection failed.")
        return False


async def connect_bigbrotr_with_retry(
    bigbrotr: Bigbrotr,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: int = DEFAULT_RETRY_BASE_DELAY,
    logging: Optional[Any] = None
) -> None:
    """Connect Bigbrotr instance with exponential backoff retry logic.

    Automatically distinguishes between transient and permanent connection errors.
    Only retries on transient errors (network partition, temporary unavailability).
    Fails fast on permanent errors (authentication, misconfiguration).

    Args:
        bigbrotr: Bigbrotr instance to connect
        max_retries: Maximum number of retry attempts (default: 5)
        base_delay: Base delay in seconds for exponential backoff (default: 1)
        logging: Optional logging object for output

    Raises:
        Exception: If connection fails after all retry attempts or permanent error
    """
    for attempt in range(max_retries):
        try:
            await bigbrotr.connect()
            if logging:
                if attempt > 0:
                    logging.info(f"✅ Database connected after {attempt + 1} attempts")
                else:
                    logging.info("✅ Database connected")
            return
        except Exception as e:
            # Check for permanent errors (fail fast)
            if is_permanent_db_error(e):
                if logging:
                    logging.error(
                        f"❌ Database connection failed with permanent error: {e}",
                        extra={"error_type": type(e).__name__}
                    )
                raise

            # Check if we've exhausted retries
            if attempt == max_retries - 1:
                if logging:
                    logging.error(
                        f"❌ Database connection failed after {max_retries} attempts: {e}",
                        extra={"error_type": type(e).__name__}
                    )
                raise

            # Transient error - retry with exponential backoff
            if is_transient_db_error(e):
                delay = base_delay * (2 ** attempt)
                if logging:
                    logging.warning(
                        f"⚠️ Database connection failed with transient error: {e}"
                    )
                    logging.info(
                        f"⏳ Retrying in {delay}s (attempt {attempt + 2}/{max_retries})..."
                    )
                await asyncio.sleep(delay)
            else:
                # Unknown error - retry anyway but log as unknown
                delay = base_delay * (2 ** attempt)
                if logging:
                    logging.warning(
                        f"⚠️ Database connection failed with unknown error: {e}"
                    )
                    logging.info(
                        f"⏳ Retrying in {delay}s (attempt {attempt + 2}/{max_retries})..."
                    )
                await asyncio.sleep(delay)


async def test_torproxy_connection(
    host: str,
    port: int,
    timeout: int = DEFAULT_TORPROXY_TIMEOUT,
    logging: Optional[Any] = None
) -> bool:
    """Test Tor proxy connection with HTTP and WebSocket.

    Args:
        host: Tor proxy host
        port: Tor proxy port
        timeout: Connection timeout in seconds
        logging: Optional logging object for output

    Returns:
        True if both HTTP and WebSocket tests pass, False otherwise
    """
    socks5_proxy_url = f"socks5://{host}:{port}"
    # HTTP Test
    connector = ProxyConnector.from_url(socks5_proxy_url, force_close=True)
    try:
        async with ClientSession(connector=connector) as session:
            async with session.get(TOR_CHECK_HTTP_URL, timeout=timeout) as resp:
                text = await resp.text()
                if "Congratulations. This browser is configured to use Tor" in text:
                    if logging:
                        logging.info("✅ HTTP response confirms Tor usage.")
                else:
                    if logging:
                        logging.error("❌ Tor usage not confirmed via HTTP.")
                    return False
    except Exception:
        if logging:
            logging.exception("❌ HTTP test via Tor failed.")
        return False
    # WebSocket Test
    connector = ProxyConnector.from_url(socks5_proxy_url, force_close=True)
    try:
        async with ClientSession(connector=connector) as session:
            if logging:
                logging.info("🌐 Testing Tor WebSocket access...")
            async with session.ws_connect(TOR_CHECK_WS_URL, timeout=timeout) as ws:
                await ws.send_str("Hello via WebSocket")
                msg = await ws.receive(timeout=timeout)
                if msg.type == WSMsgType.TEXT:
                    if logging:
                        logging.info(
                            f"✅ WebSocket message received: {msg.data}")
                    return True
                else:
                    if logging:
                        logging.error(
                            f"❌ Unexpected WebSocket response: {msg.type}")
                    return False
    except Exception:
        if logging:
            logging.exception("❌ WebSocket test via Tor failed.")
        return False


async def wait_for_services(config: Dict[str, Any], retries: int = DEFAULT_MAX_RETRIES, delay: int = DEFAULT_DB_RETRY_DELAY) -> None:
    """Wait for required services (database and Tor proxy) to be available.

    Args:
        config: Configuration dictionary with database and proxy settings
        retries: Number of retry attempts (default: 5)
        delay: Delay between retries in seconds (default: 30)

    Raises:
        RuntimeError: If services are not available after all retry attempts
    """
    import logging

    for attempt in range(1, retries + 1):
        database_connection = await test_database_connection_async(
            config.get("database_host") or config.get("dbhost"),
            config.get("database_port") or config.get("dbport"),
            config.get("database_user") or config.get("dbuser"),
            config.get("database_password") or config.get("dbpass"),
            config.get("database_name") or config.get("dbname")
        )

        # Check if torproxy is configured
        torproxy_host = config.get("torproxy_host") or config.get("torhost")
        torproxy_port = config.get("torproxy_port") or config.get("torport")
        timeout = config.get("timeout", 10)

        if torproxy_host and torproxy_port:
            torproxy_connection = await test_torproxy_connection(
                torproxy_host,
                torproxy_port,
                timeout=timeout
            )
        else:
            # Tor proxy not configured, skip check
            torproxy_connection = True

        if database_connection and torproxy_connection:
            logging.info("✅ All required services are available.")
            return
        else:
            logging.warning(
                f"⚠️ Attempt {attempt}/{retries} failed. Retrying in {delay} seconds..."
            )
            # Only sleep if we have more attempts remaining
            if attempt < retries:
                await asyncio.sleep(delay)

    raise RuntimeError(
        "❌ Required services are not available after multiple attempts. Exiting."
    )
