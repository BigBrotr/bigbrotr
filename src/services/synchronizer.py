import os
import re
import sys
import time
import json
import random
import asyncio
import logging
import threading
from nostr_tools import Relay
from queue import Empty
from brotr import Brotr
from process_relay import process_relay, get_start_time
from multiprocessing import cpu_count, Queue, Process
from functions import test_database_connection, test_torproxy_connection

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
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
            "num_cores": int(os.environ["SYNCHRONIZER_NUM_CORES"]),
            "requests_per_core": int(os.environ["SYNCHRONIZER_REQUESTS_PER_CORE"]),
            "timeout": int(os.environ["SYNCHRONIZER_REQUEST_TIMEOUT"]),
            "start": int(os.environ["SYNCHRONIZER_START_TIMESTAMP"]),
            "stop": int(os.environ["SYNCHRONIZER_STOP_TIMESTAMP"]),
            "filter": json.loads(os.environ["SYNCHRONIZER_EVENT_FILTER"]),
            "priority": str(os.environ.get("SYNCHRONIZER_PRIORITY_RELAYS_FILEPATH"))
        }
        if config["dbport"] < 0 or config["dbport"] > 65535:
            logging.error(
                "❌ Invalid POSTGRES_PORT. Must be between 0 and 65535.")
            sys.exit(1)
        if config["torport"] < 0 or config["torport"] > 65535:
            logging.error(
                "❌ Invalid TORPROXY_PORT. Must be between 0 and 65535.")
            sys.exit(1)
        if config["num_cores"] < 1:
            logging.error(
                "❌ Invalid SYNCHRONIZER_NUM_CORES. Must be at least 1.")
            sys.exit(1)
        if config["requests_per_core"] < 1:
            logging.error(
                "❌ Invalid SYNCHRONIZER_REQUESTS_PER_CORE. Must be at least 1.")
            sys.exit(1)
        if config["timeout"] < 1:
            logging.error(
                "❌ Invalid SYNCHRONIZER_REQUEST_TIMEOUT. Must be 1 or greater.")
            sys.exit(1)
        if config["start"] < 0:
            logging.error(
                "❌ Invalid SYNCHRONIZER_START_TIMESTAMP. Must be 0 or greater.")
            sys.exit(1)
        if config["stop"] != -1 and config["stop"] < 0:
            logging.error(
                "❌ Invalid SYNCHRONIZER_STOP_TIMESTAMP. Must be 0 or greater.")
            sys.exit(1)
        if config["stop"] != -1 and config["start"] > config["stop"]:
            logging.error(
                "❌ SYNCHRONIZER_START_TIMESTAMP cannot be greater than SYNCHRONIZER_STOP_TIMESTAMP.")
            sys.exit(1)
        if config["num_cores"] > cpu_count():
            logging.warning(
                f"⚠️ SYNCHRONIZER_NUM_CORES exceeds available CPU cores ({cpu_count()}).")
            config["num_cores"] = cpu_count()
            logging.info(
                f"🔄 SYNCHRONIZER_NUM_CORES set to {config['num_cores']} (max available).")
        if not isinstance(config["filter"], dict):
            logging.error(
                "❌ SYNCHRONIZER_EVENT_FILTER must be a valid JSON object.")
            sys.exit(1)
        config["filter"] = {k: v for k, v in config["filter"].items(
        ) if k in {"ids", "authors", "kinds"} or re.fullmatch(r"#([a-zA-Z])", k)}
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


# --- Fetch Relays from Database ---
def fetch_relays_from_database(host, port, user, password, dbname):
    brotr = Brotr(host, port, user, password, dbname)
    brotr.connect()
    logging.info("📦 Fetching relay metadata from database...")
    query = """
        SELECT relay_url
        FROM relay_metadata rm
        WHERE generated_at = (
            SELECT MAX(generated_at)
            FROM relay_metadata
            WHERE relay_url = rm.relay_url
        )
        AND generated_at > %s
        AND readable = TRUE
    """
    treshold = int(time.time()) - 60 * 60 * 12
    brotr.execute(query, (treshold,))
    rows = brotr.fetchall()
    brotr.close()
    relays = []
    for row in rows:
        relay_url = row[0].strip()
        try:
            relay = Relay(relay_url)
            relays.append(relay)
        except Exception as e:
            logging.warning(f"⚠️ Invalid relay: {relay_url}. Error: {e}")
            continue
    logging.info(f"📦 {len(relays)} relay fetched from database.")
    random.shuffle(relays)
    return relays


# --- Fetch Relays from File ---
def fetch_relays_from_filepath(filepath):
    relays = []
    with open(filepath, "r") as file:
        for line in file:
            relay_url = line.strip()
            try:
                relay = Relay(relay_url)
                relays.append(relay)
            except Exception as e:
                logging.warning(f"⚠️ Invalid relay: {relay_url}. Error: {e}")
                continue
    logging.info(f"📦 {len(relays)} relay fetched from file.")
    random.shuffle(relays)
    return relays


# --- Thread Function ---
def thread_foo(config, shared_queue, end_time):
    async def run_with_timeout(config, relay, end_time):
        try:
            await asyncio.sleep(random.randint(0, 120))
            brotr = Brotr(config["dbhost"], config["dbport"], config["dbuser"], config["dbpass"], config["dbname"])
            start_time = get_start_time(config["start"], brotr, relay)
            await asyncio.wait_for(
                process_relay(config, relay, brotr, start_time, end_time),
                timeout=60 * 30
            )
        except asyncio.TimeoutError:
            logging.warning(f"⏰ Timeout while processing {relay.url}")
        except Exception as e:
            logging.exception(f"❌ Error processing {relay.url}: {e}")
    while True:
        try:
            relay = shared_queue.get(timeout=1)
        except Empty:
            break
        except Exception as e:
            logging.exception(f"❌ Error reading from shared queue: {e}")
        asyncio.run(run_with_timeout(config, relay, end_time))
    return


# --- Process Function ---
def process_foo(config, shared_queue, end_time):
    request_per_core = config["requests_per_core"]
    threads = []
    for _ in range(request_per_core):
        t = threading.Thread(
            target=thread_foo,
            args=(config, shared_queue, end_time)
        )
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    return


# --- Main Loop ---
async def main_loop(config):
    relays = fetch_relays_from_database(
        config["dbhost"], config["dbport"], config["dbuser"], config["dbpass"], config["dbname"])
    priority_relays = fetch_relays_from_filepath(config["priority"])
    priority_relays = [relay.url for relay in priority_relays]
    num_cores = config["num_cores"]
    if config["stop"] != -1:
        end_time = config["stop"]
    else:
        end_time = int(time.time()) - 60 * 60 * 24
    shared_queue = Queue()
    for relay in relays:
        if relay.url not in priority_relays:
            shared_queue.put(relay)
    logging.info(f"📦 {shared_queue.qsize()} relays to process.")
    processes = []
    for _ in range(num_cores):
        p = Process(
            target=process_foo,
            args=(config, shared_queue, end_time)
        )
        p.start()
        processes.append(p)
    for p in processes:
        p.join()
    return


# --- Syncronizer Entrypoint ---
async def synchronizer():
    config = load_config_from_env()
    logging.info("🔄 Starting Syncronizer...")
    await wait_for_services(config)
    while True:
        try:
            logging.info("🔄 Starting main loop...")
            await main_loop(config)
            logging.info("✅ Main loop completed successfully.")
            logging.info("⏳ Waiting 15 minutes before next run...")
            await asyncio.sleep(15 * 60)
        except Exception as e:
            logging.exception(f"❌ Main loop failed: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(synchronizer())
    except Exception:
        logging.exception("❌ Syncronizer failed to start.")
        sys.exit(1)
