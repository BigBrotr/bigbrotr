import os
import sys
import asyncio
import logging
from datetime import datetime, timedelta
from bigbrotr import Bigbrotr
from relay import Relay
from aiohttp import ClientSession, WSMsgType
from aiohttp_socks import ProxyConnector
import time
import utils
from multiprocessing import Pool, cpu_count

# --- Logging Config ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
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
            "run_hour": int(os.environ["MONITOR_RUN_HOUR"]),
            "torhost": str(os.environ["TORPROXY_HOST"]),
            "torport": int(os.environ["TORPROXY_PORT"]),
            "num_cores": int(os.environ["MONITOR_NUM_CORES"]),
            "chunk_size": int(os.environ["MONITOR_CHUNK_SIZE"]),
            "requests_per_core": int(os.environ["MONITOR_REQUESTS_PER_CORE"]),
        }
        if config["dbport"] < 0 or config["dbport"] > 65535:
            logging.error("❌ Invalid database port number.")
            sys.exit(1)
        if config["torport"] < 0 or config["torport"] > 65535:
            logging.error("❌ Invalid Tor proxy port number.")
            sys.exit(1)
        if config["run_hour"] < 0 or config["run_hour"] > 23:
            logging.error("❌ Invalid run hour. Must be between 0 and 23.")
            sys.exit(1)
        if config["num_cores"] < 1:
            logging.error("❌ Invalid number of cores. Must be at least 1.")
            sys.exit(1)
        if config["chunk_size"] < 1:
            logging.error("❌ Invalid chunk size. Must be at least 1.")
            sys.exit(1)
        if config["requests_per_core"] < 1:
            logging.error("❌ Invalid requests per core. Must be at least 1.")
            sys.exit(1)
        if config["num_cores"] > cpu_count():
            logging.warning(
                f"⚠️ Number of cores ({config['num_cores']}) exceeds available CPU cores ({cpu_count()}).")
            config["num_cores"] = cpu_count()
            logging.info(
                f"🔄 Adjusting number of cores to {config['num_cores']}.")
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


# --- Process Chunk ---
async def process_chunk(chunk, config, generated_at):
    proxy_url = f"socks5://{config['torhost']}:{config['torport']}"
    requests_per_core = config["requests_per_core"]
    sem = asyncio.Semaphore(requests_per_core)

    async def process_single_relay(relay):
        async with sem:
            try:
                metadata = await utils.compute_relay_metadata(relay, proxy_url)
                if metadata:
                    metadata.generated_at = generated_at
                    return metadata
            except Exception as e:
                logging.warning(
                    f"⚠️ Failed to compute metadata for relay {relay.url}: {e}")
        return None
    tasks = [process_single_relay(relay) for relay in chunk]
    all_results = await asyncio.gather(*tasks)
    return [res for res in all_results if res is not None]


# --- Main Loop Placeholder ---
async def main_loop(config):
    bigbrotr = Bigbrotr(config["dbhost"], config["dbport"],
                        config["dbuser"], config["dbpass"], config["dbname"])
    bigbrotr.connect()
    logging.info("🔌 Database connection established.")
    logging.info("📦 Fetching relays from database...")
    query = "SELECT url FROM relays"
    bigbrotr.execute(query)
    rows = bigbrotr.fetchall()
    bigbrotr.close()
    relays = []
    for row in rows:
        try:
            relay = Relay(row[0])
            relays.append(relay)
        except Exception as e:
            logging.warning(
                f"⚠️ Invalid relay URL skipped: {row[0]}. Reason: {e}")
            continue
    logging.info(f"📦 {len(relays)} relays fetched from database.")
    chunk_size = config["chunk_size"]
    num_cores = config["num_cores"]
    chunks = list(chunkify(relays, chunk_size))
    generated_at = int(time.time())
    args = [(chunk, config, generated_at) for chunk in chunks]
    logging.info(
        f"🔄 Processing {len(chunks)} chunks with {num_cores} cores...")
    relay_metadata_list = []
    with Pool(processes=num_cores) as pool:
        results = pool.starmap(process_chunk, args)
        for result in results:
            relay_metadata_list.extend(result)
    logging.info(f"✅ All chunks processed successfully.")
    logging.info(relay_metadata_list)
    bigbrotr.connect()
    logging.info("🔌 Database connection established.")
    logging.info("🌐 Starting relay metadata insertion process...")
    bigbrotr.insert_relay_metadata_batch(relay_metadata_list)
    logging.info(f"✅ Inserted {len(relay_metadata_list)} relay metadata.")
    bigbrotr.close()
    logging.info("🔌 Database connection closed.")
    return


# --- Monitor Entrypoint ---
async def monitor():
    config = load_config_from_env()
    logging.info("🔍 Starting monitor...")
    await wait_for_services(config)
    while True:
        await wait_until_scheduled_hour(config["run_hour"])
        try:
            logging.info("🔄 Starting main loop...")
            await main_loop(config)
            logging.info("✅ Main loop completed successfully.")
        except Exception as e:
            logging.exception(f"❌ Main loop failed: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(monitor())
    except Exception:
        logging.exception("❌ Monitor failed to start.")
        sys.exit(1)
