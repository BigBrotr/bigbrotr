import os
import sys
import asyncio
import logging
from datetime import datetime, timedelta
from bigbrotr import Bigbrotr
from aiohttp import ClientSession, WSMsgType
from aiohttp_socks import ProxyConnector

# --- Logging Config ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)


# --- Config Loader ---
def load_config_from_env():
    try:
        return {
            "dbhost": str(os.environ["POSTGRES_HOST"]),
            "user": str(os.environ["POSTGRES_USER"]),
            "password": str(os.environ["POSTGRES_PASSWORD"]),
            "dbname": str(os.environ["POSTGRES_DB"]),
            "dbport": int(os.environ["POSTGRES_PORT"]),
            "run_hour": int(os.environ["MONITOR_RUN_HOUR"]),
            "torhost": str(os.environ["TORPROXY_HOST"]),
            "torport": int(os.environ["TORPROXY_PORT"]),
            "num_cores": int(os.environ["MONITOR_NUM_CORES"]),
            "chunk_size": int(os.environ["MONITOR_CHUNK_SIZE"]),
            "requests_per_core": int(os.environ["MONITOR_REQUESTS_PER_CORE"]),
        }
    except KeyError as e:
        logging.error(f"❌ Missing environment variable: {e}")
        sys.exit(1)
    except ValueError as e:
        logging.error(f"❌ Invalid environment variable value: {e}")
        sys.exit(1)


# --- Database Test ---
def test_database_connection(config):
    logging.info(
        f"🔌 Testing database connection to {config["dbhost"]}:{config["dbport"]}/{config["dbname"]}")
    try:
        db = Bigbrotr(config["dbhost"], config["dbport"],
                      config["user"], config["password"], config["dbname"])
        db.connect()
        logging.info("✅ Database connection successful.")
    except Exception as e:
        logging.exception("❌ Database connection failed.")
        raise
    finally:
        db.close()
        logging.info("🔌 Database connection closed.")


# --- Tor Proxy Test ---
async def test_torproxy_connection(config, timeout=10):
    proxy_url = f"socks5://{config["torhost"]}:{config["torport"]}"
    # HTTP Test
    http_url = "https://check.torproject.org"
    connector = ProxyConnector.from_url(proxy_url)
    async with ClientSession(connector=connector) as session:
        try:
            logging.info("🌐 Testing Tor HTTP access...")
            async with session.get(http_url, timeout=timeout) as resp:
                text = await resp.text()
                if "Congratulations. This browser is configured to use Tor" in text:
                    logging.info("✅ HTTP response confirms Tor usage.")
                else:
                    raise RuntimeError("Tor usage not confirmed via HTTP.")
        except Exception:
            logging.exception("❌ HTTP test via Tor failed.")
            raise
    # WebSocket Test
    ws_url = "wss://echo.websocket.events"
    connector = ProxyConnector.from_url(proxy_url)
    async with ClientSession(connector=connector) as session:
        try:
            logging.info("🌐 Testing Tor WebSocket access...")
            async with session.ws_connect(ws_url, timeout=timeout) as ws:
                await ws.send_str("Hello via WebSocket")
                msg = await ws.receive(timeout=timeout)
                if msg.type == WSMsgType.TEXT:
                    logging.info(f"✅ WebSocket message received: {msg.data}")
                else:
                    raise RuntimeError(
                        f"Unexpected WebSocket response: {msg.type}")
        except Exception:
            logging.exception("❌ WebSocket test via Tor failed.")
            raise


# --- Wait Until Hour ---
async def wait_until_scheduled_hour(run_hour):
    now = datetime.now()
    next_run = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    wait_seconds = (next_run - now).total_seconds()
    logging.info(
        f"⏰ Waiting for scheduled time at {run_hour}:00 (in {wait_seconds:.2f} seconds)...")
    await asyncio.sleep(wait_seconds)


# --- Wait for Services (Resilience) ---
async def wait_for_services(config, retries=5, delay=30):
    for attempt in range(1, retries + 1):
        await asyncio.sleep(delay)
        try:
            test_database_connection(config)
            await test_torproxy_connection(config)
            return
        except Exception as e:
            logging.warning(
                f"⏳ Service not ready (attempt {attempt}/{retries}): {e}")
    raise RuntimeError("❌ Required services not available after retries.")


# --- Main Loop Placeholder ---
def main_loop(config):
    logging.info("🚧 Main loop logic would go here.")
    # TODO: implement processing logic using bigbrotr, torproxy, etc.


# --- Monitor Entrypoint ---
async def monitor():
    config = load_config_from_env()
    logging.info("🔍 Starting monitor...")
    await wait_for_services(config)
    while True:
        await wait_until_scheduled_hour(config["run_hour"])
        try:
            logging.info("🔄 Starting main loop...")
            main_loop(config)
            logging.info("✅ Main loop completed successfully.")
        except Exception as e:
            logging.exception("❌ Main loop failed with an error.")


if __name__ == "__main__":
    try:
        asyncio.run(monitor())
    except Exception:
        logging.exception("❌ Monitor failed to start.")
        sys.exit(1)
