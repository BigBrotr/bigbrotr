from bigbrotr import Bigbrotr
from aiohttp import ClientSession, WSMsgType
from aiohttp_socks import ProxyConnector


def chunkify(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def test_database_connection(host, port, user, password, dbname, logging=None):
    db = None
    try:
        db = Bigbrotr(host, port, user, password, dbname)
        db.connect()
        if logging:
            logging.info("✅ Database connection successful.")
        return True
    except Exception as e:
        if logging:
            logging.exception("❌ Database connection failed.")
        return False
    finally:
        if db:
            try:
                db.close()
                if logging:
                    logging.info("🧹 Database connection closed.")
            except Exception:
                if logging:
                    logging.warning(
                        "⚠️ Failed to close database connection cleanly.")


async def test_torproxy_connection(host, port, timeout=10, logging=None):
    socks5_proxy_url = f"socks5://{host}:{port}"
    # HTTP Test
    http_url = "https://check.torproject.org"
    connector = ProxyConnector.from_url(socks5_proxy_url, force_close=True)
    try:
        async with ClientSession(connector=connector) as session:
            async with session.get(http_url, timeout=timeout) as resp:
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
    ws_url = "wss://echo.websocket.events"
    connector = ProxyConnector.from_url(socks5_proxy_url, force_close=True)
    try:
        async with ClientSession(connector=connector) as session:
            if logging:
                logging.info("🌐 Testing Tor WebSocket access...")
            async with session.ws_connect(ws_url, timeout=timeout) as ws:
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
