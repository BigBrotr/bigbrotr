from typing import Generator, List, TypeVar, Optional, Any, Dict

import asyncio
import logging

from bigbrotr import BigBrotr

T = TypeVar('T')


class RelayFailureTracker:
    """Track relay processing failures and alert on high failure rates.

    This class maintains statistics on relay processing success/failure rates
    and emits alerts when failure rates exceed configured thresholds.
    """

    def __init__(self, alert_threshold: float = 0.1, check_interval: int = 100):
        """Initialize failure tracker.

        Args:
            alert_threshold: Failure rate threshold for alerts (default: 0.1 = 10%)
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
    logger: Optional[Any] = None
) -> bool:
    """Test database connection asynchronously."""
    try:
        async with BigBrotr(host, port, user, password, dbname) as db:
            # Try a simple query to verify connection
            await db.fetch("SELECT 1")
            if logger:
                logger.info("✅ Database connection successful.")
            return True
    except Exception:
        if logger:
            logger.exception("❌ Database connection failed.")
        return False


async def connect_bigbrotr_with_retry(
    bigbrotr: BigBrotr,
    max_retries: int = 5,
    base_delay: int = 1,
    logger: Optional[Any] = None
) -> None:
    """Connect BigBrotr instance with exponential backoff retry logic.

    Args:
        bigbrotr: BigBrotr instance to connect
        max_retries: Maximum number of retry attempts (default: 5)
        base_delay: Base delay in seconds for exponential backoff (default: 1)
        logger: Optional logging object for output

    Raises:
        Exception: If connection fails after all retry attempts
    """
    for attempt in range(max_retries):
        try:
            await bigbrotr.connect()
            if logger:
                logger.info(f"✅ Database connected on attempt {attempt + 1}")
            return
        except Exception as e:
            if attempt == max_retries - 1:
                if logger:
                    logger.exception(
                        f"❌ Database connection failed after {max_retries} attempts"
                    )
                raise
            delay = base_delay * (2 ** attempt)  # Exponential backoff
            if logger:
                logger.warning(
                    f"⚠️ Database connection failed (attempt {attempt + 1}/{max_retries}): {e}"
                )
                logger.info(f"⏳ Retrying in {delay} seconds...")
            await asyncio.sleep(delay)


async def test_torproxy_connection(
    host: str,
    port: int,
    timeout: int = 10,
    logger: Optional[Any] = None
) -> bool:
    """Test if Tor proxy SOCKS5 port is accessible.

    Args:
        host: Tor proxy host
        port: Tor proxy port
        timeout: Connection timeout in seconds
        logger: Optional logging object for output

    Returns:
        True if SOCKS5 port is accessible, False otherwise
    """
    try:
        # Simple TCP connection test to SOCKS5 port
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        if logger:
            logger.info(f"✅ Tor proxy SOCKS5 port accessible at {host}:{port}")
        return True
    except Exception as e:
        if logger:
            logger.warning(f"❌ Tor proxy connection failed at {host}:{port}: {e}")
        return False


async def wait_for_services(config: Dict[str, Any], retries: int = 5, delay: int = 30) -> None:
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
            config.get("database_name") or config.get("dbname"),
            logger=logging
        )

        # Check if torproxy is configured
        torproxy_host = config.get("torproxy_host") or config.get("torhost")
        torproxy_port = config.get("torproxy_port") or config.get("torport")
        timeout = config.get("timeout", 10)

        if torproxy_host and torproxy_port:
            torproxy_connection = await test_torproxy_connection(
                torproxy_host,
                torproxy_port,
                timeout=timeout,
                logger=logging
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
