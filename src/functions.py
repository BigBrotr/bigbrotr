from typing import Generator, List, TypeVar, Optional, Any, Dict

import asyncio

from aiohttp import ClientSession, WSMsgType
from aiohttp_socks import ProxyConnector

from bigbrotr import Bigbrotr
from constants import TOR_CHECK_HTTP_URL, TOR_CHECK_WS_URL

T = TypeVar('T')


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


async def test_torproxy_connection(
    host: str,
    port: int,
    timeout: int = 10,
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
