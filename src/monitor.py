import os
import sys
import asyncio
import logging
from bigbrotr import Bigbrotr
from relay import Relay
from aiohttp import ClientSession, WSMsgType
from aiohttp_socks import ProxyConnector
import time
from utils import test_keypair
from multiprocessing import Pool, cpu_count
from compute_relay_metadata import compute_relay_metadata

# --- Logging Config ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)


# --- Chunkify Function ---
def chunkify(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


# --- Config Loader ---
def load_config_from_env():
    try:
        config = {
            "dbhost": str(os.environ["POSTGRES_HOST"]),
            "dbuser": str(os.environ["POSTGRES_USER"]),
            "dbpass": str(os.environ["POSTGRES_PASSWORD"]),
            "dbname": str(os.environ["POSTGRES_DB"]),
            "dbport": int(os.environ["POSTGRES_PORT"]),
            "torhost": str(os.environ["TORPROXY_HOST"]),
            "torport": int(os.environ["TORPROXY_PORT"]),
            "frequency_hour": int(os.environ["MONITOR_FREQUENCY_HOUR"]),
            "num_cores": int(os.environ["MONITOR_NUM_CORES"]),
            "chunk_size": int(os.environ["MONITOR_CHUNK_SIZE"]),
            "requests_per_core": int(os.environ["MONITOR_REQUESTS_PER_CORE"]),
            "timeout": int(os.environ["MONITOR_REQUEST_TIMEOUT"]),
            "seckey": str(os.environ["SECRET_KEY"]),
            "pubkey": str(os.environ["PUBLIC_KEY"]),
        }
        if config["dbport"] < 0 or config["dbport"] > 65535:
            logging.error(
                "❌ Invalid POSTGRES_PORT. Must be between 0 and 65535.")
            sys.exit(1)
        if config["torport"] < 0 or config["torport"] > 65535:
            logging.error(
                "❌ Invalid TORPROXY_PORT. Must be between 0 and 65535.")
            sys.exit(1)
        if config["frequency_hour"] < 1:
            logging.error(
                "❌ Invalid MONITOR_FREQUENCY_HOUR. Must be at least 1.")
            sys.exit(1)
        if config["num_cores"] < 1:
            logging.error("❌ Invalid MONITOR_NUM_CORES. Must be at least 1.")
            sys.exit(1)
        if config["chunk_size"] < 1:
            logging.error("❌ Invalid MONITOR_CHUNK_SIZE. Must be at least 1.")
            sys.exit(1)
        if config["requests_per_core"] < 1:
            logging.error(
                "❌ Invalid MONITOR_REQUESTS_PER_CORE. Must be at least 1.")
            sys.exit(1)
        if not test_keypair(config["seckey"], config["pubkey"]):
            logging.error("❌ Invalid SECRET_KEY or PUBLIC_KEY.")
            sys.exit(1)
        if config["timeout"] < 1:
            logging.error(
                "❌ Invalid MONITOR_REQUEST_TIMEOUT. Must be 1 or greater.")
            sys.exit(1)
        if config["num_cores"] > cpu_count():
            logging.warning(
                f"⚠️ MONITOR_NUM_CORES exceeds available CPU cores ({cpu_count()}).")
            config["num_cores"] = cpu_count()
            logging.info(
                f"🔄 MONITOR_NUM_CORES set to {config['num_cores']} (max available).")
    except KeyError as e:
        logging.error(f"❌ Missing environment variable: {e}")
        sys.exit(1)
    except ValueError as e:
        logging.error(f"❌ Invalid environment variable value: {e}")
        sys.exit(1)
    return config


# --- Database Test ---
def test_database_connection(config):
    logging.info(
        f"🔌 Testing database connection to {config["dbhost"]}:{config["dbport"]}/{config["dbname"]}")
    try:
        db = Bigbrotr(config["dbhost"], config["dbport"],
                      config["dbuser"], config["dbpass"], config["dbname"])
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
    socks5_proxy_url = f"socks5://{config["torhost"]}:{config["torport"]}"
    # HTTP Test
    http_url = "https://check.torproject.org"
    connector = ProxyConnector.from_url(socks5_proxy_url)
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
        finally:
            await session.close()
            logging.info("🌐 HTTP connection closed.")
    # WebSocket Test
    ws_url = "wss://echo.websocket.events"
    connector = ProxyConnector.from_url(socks5_proxy_url)
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
        finally:
            await ws.close()
            logging.info("🌐 WebSocket connection closed.")


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


# --- Process Relay Metadata ---
async def process_relay(config, relay, generated_at):
    socks5_proxy_url = f"socks5://{config['torhost']}:{config['torport']}"
    relay_metadata = await compute_relay_metadata(
        relay,
        config["seckey"],
        config["pubkey"],
        socks5_proxy_url=socks5_proxy_url if relay.network == "tor" else None,
        timeout=config["timeout"],
    )
    relay_metadata.generated_at = generated_at
    return relay_metadata


# --- Process Chunk ---
async def process_chunk(chunk, config, generated_at):
    semaphore = asyncio.Semaphore(config["requests_per_core"])
    relay_metadata_list = []

    async def sem_task(relay):
        async with semaphore:
            try:
                relay_metadata = await process_relay(config, relay, generated_at)
                if relay_metadata.connection_success or relay_metadata.nip11_success:
                    return relay_metadata
            except Exception as e:
                logging.exception(f"❌ Error processing {relay.url}: {e}")
            return None

    tasks = [sem_task(relay) for relay in chunk]
    results = await asyncio.gather(*tasks)
    relay_metadata_list = [r for r in results if r is not None]
    bigbrotr = Bigbrotr(config["dbhost"], config["dbport"], config["dbuser"], config["dbpass"], config["dbname"])
    bigbrotr.connect()
    bigbrotr.insert_relay_metadata_batch(relay_metadata_list)
    bigbrotr.close()
    logging.info(f"✅ Processed {len(chunk)} relays. Found {len(relay_metadata_list)} valid relay metadata.")
    return


# --- Worker Function ---
def worker(chunk, config, generated_at):
    async def worker_async(chunk, config, generated_at):
        return await process_chunk(chunk, config, generated_at)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(worker_async(chunk, config, generated_at))


# --- Fetch Relays from Database ---
def fetch_relays(config):
    bigbrotr = Bigbrotr(config["dbhost"], config["dbport"], config["dbuser"], config["dbpass"], config["dbname"])
    bigbrotr.connect()
    logging.info("📦 Fetching relays from database...")
    query = f"""
    SELECT r.url
    FROM relays r
    LEFT JOIN (
        SELECT relay_url, MAX(generated_at) AS last_generated_at
        FROM relay_metadata
        GROUP BY relay_url
    ) rm ON r.url = rm.relay_url
    WHERE rm.last_generated_at IS NULL
    OR rm.last_generated_at < %s
    """
    threshold = int(time.time()) - 60 * 60 * config["frequency_hour"]
    bigbrotr.execute(query, (threshold,))
    rows = bigbrotr.fetchall()
    bigbrotr.close()
    relays = []
    for row in rows:
        try:
            relay = Relay(row[0])
            relays.append(relay)
        except Exception as e:
            logging.warning(f"⚠️ Invalid relay: {row[0]}. Error: {e}")
            continue
    logging.info(f"📦 {len(relays)} relays fetched from database.")
    return relays


# --- Main Loop ---
async def main_loop(config):
    relays = fetch_relays(config)
    chunk_size = config["chunk_size"]
    num_cores = config["num_cores"]
    chunks = list(chunkify(relays, chunk_size))
    generated_at = int(time.time())
    args = [(chunk, config, generated_at) for chunk in chunks]
    logging.info(f"🔄 Processing {len(chunks)} chunks with {num_cores} cores...")
    with Pool(processes=num_cores) as pool:
        pool.starmap(worker, args)
    logging.info(f"✅ All chunks processed successfully.")
    return


# --- Monitor Entrypoint ---
async def monitor():
    config = load_config_from_env()
    logging.info("🔍 Starting monitor...")
    await wait_for_services(config)
    while True:
        try:
            logging.info("🔄 Starting main loop...")
            await main_loop(config)
            logging.info("✅ Main loop completed successfully.")
            logging.info(f"⏳ Waiting 15 minutes before next run...")
            await asyncio.sleep(15 * 60)
        except Exception as e:
            logging.exception(f"❌ Main loop failed: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(monitor())
    except Exception:
        logging.exception("❌ Monitor failed to start.")
        sys.exit(1)
