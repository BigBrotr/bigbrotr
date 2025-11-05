import os
import sys
import time
import asyncio
import logging
from nostr_tools import Relay, validate_keypair, Client, fetch_relay_metadata
from brotr import Brotr
from multiprocessing import Pool, cpu_count
from functions import chunkify, test_database_connection, test_torproxy_connection


# --- Logging Config ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)


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
        if not validate_keypair(config["seckey"], config["pubkey"]):
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


# --- Wait for Services (Resilience) ---
async def wait_for_services(config, retries=5, delay=30):
    for attempt in range(1, retries + 1):
        await asyncio.sleep(delay)
        database_connection = test_database_connection(
            config["dbhost"], config["dbport"], config["dbuser"], config["dbpass"], config["dbname"])
        torproxy_connection = await test_torproxy_connection(config["torhost"], config["torport"], timeout=config["timeout"])
        if database_connection and torproxy_connection:
            logging.info("✅ All required services are available.")
            return
        else:
            logging.warning(
                f"⚠️ Attempt {attempt}/{retries} failed. Retrying in {delay} seconds...")
    raise RuntimeError(
        "❌ Required services are not available after multiple attempts. Exiting.")


# --- Process Relay Metadata ---
async def process_relay(config, relay, generated_at):
    socks5_proxy_url = f"socks5://{config['torhost']}:{config['torport']}"
    client = Client(
        relay=relay,
        timeout=config["timeout"],
        socks5_proxy_url=socks5_proxy_url if relay.network == "tor" else None
    )
    relay_metadata = await fetch_relay_metadata(
        client=client,
        private_key=config["seckey"],
        public_key=config["pubkey"]
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
                # Check if we got any useful metadata (nip66 or nip11)
                if relay_metadata and (relay_metadata.nip66 or relay_metadata.nip11):
                    return relay_metadata
            except Exception as e:
                logging.exception(f"❌ Error processing {relay.url}: {e}")
            return None

    tasks = [sem_task(relay) for relay in chunk]
    results = await asyncio.gather(*tasks)
    relay_metadata_list = [r for r in results if r is not None]
    brotr = Brotr(config["dbhost"], config["dbport"],
                        config["dbuser"], config["dbpass"], config["dbname"])
    brotr.connect()
    brotr.insert_relay_metadata_batch(relay_metadata_list)
    brotr.close()
    logging.info(
        f"✅ Processed {len(chunk)} relays. Found {len(relay_metadata_list)} valid relay metadata.")
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
    brotr = Brotr(config["dbhost"], config["dbport"],
                        config["dbuser"], config["dbpass"], config["dbname"])
    brotr.connect()
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
    brotr.execute(query, (threshold,))
    rows = brotr.fetchall()
    brotr.close()
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
    logging.info(
        f"🔄 Processing {len(chunks)} chunks with {num_cores} cores...")
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
