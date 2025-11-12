import sys
import time
import random
import asyncio
import logging
import threading
from brotr import Brotr
from functions import chunkify
from multiprocessing import Process
from synchronizer import load_config_from_env, wait_for_services, fetch_relays_from_filepath, process_relay, get_start_time


# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


# --- Thread Function ---
def thread_foo(relay, config, end_time):
    while True:
        try:
            time.sleep(random.randint(0, 120))
            brotr = Brotr(config["dbhost"], config["dbport"], config["dbuser"], config["dbpass"], config["dbname"])
            start_time = get_start_time(config["start"], brotr, relay)
            asyncio.run(process_relay(config, relay, brotr, start_time, end_time))
            time.sleep(15 * 60)
        except Exception as e:
            logging.exception(f"❌ Error processing relay {relay.url}: {e}")
            time.sleep(60)
    return


# --- Process Function ---
def process_foo(chunk, config, end_time):
    threads = []
    for relay in chunk:
        t = threading.Thread(
            target=thread_foo,
            args=(relay, config, end_time)
        )
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    return


# --- Main Loop ---
async def main_loop(config):
    relays = fetch_relays_from_filepath(config["priority"])
    num_cores = config["num_cores"]
    if config["stop"] != -1:
        end_time = config["stop"]
    else:
        end_time = int(time.time()) - 60 * 60 * 24
    chunks = chunkify(relays, num_cores)
    logging.info(f"📦 {len(relays)} relays to process.")
    processes = []
    for chunk in chunks:
        p = Process(
            target=process_foo,
            args=(chunk, config, end_time)
        )
        p.start()
        processes.append(p)
    for p in processes:
        p.join()
    return


# --- Syncronizer Entrypoint ---
async def priority_synchronizer():
    config = load_config_from_env()
    logging.info("🔄 Starting Priority Syncronizer...")
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
        asyncio.run(priority_synchronizer())
    except Exception:
        logging.exception("❌ Priority Syncronizer failed to start.")
        sys.exit(1)
