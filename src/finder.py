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
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
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
            "frequency_hour": int(os.environ["FINDER_FREQUENCY_HOUR"]),
            "timeout": int(os.environ["FINDER_REQUEST_TIMEOUT"]),
        }
        if config["dbport"] < 0 or config["dbport"] > 65535:
            logging.error(
                "❌ Invalid POSTGRES_PORT. Must be between 0 and 65535.")
            sys.exit(1)
        if config["frequency_hour"] < 1:
            logging.error(
                "❌ Invalid FINDER_FREQUENCY_HOUR. Must be at least 1.")
            sys.exit(1)
        if config["timeout"] < 1:
            logging.error(
                "❌ Invalid FINDER_REQUEST_TIMEOUT. Must be 1 or greater.")
            sys.exit(1)
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


# --- Wait for Services (Resilience) ---
async def wait_for_services(config, retries=5, delay=30):
    for attempt in range(1, retries + 1):
        await asyncio.sleep(delay)
        try:
            test_database_connection(config)
            return
        except Exception as e:
            logging.warning(
                f"⏳ Service not ready (attempt {attempt}/{retries}): {e}")
    raise RuntimeError("❌ Required services not available after retries.")


# --- Finder Entrypoint ---
async def finder():
    config = load_config_from_env()
    logging.info("🔍 Starting finder...")
    await wait_for_services(config)
    while True:
        try:
            bigbrotr = Bigbrotr(
                config["dbhost"], config["dbport"], config["dbuser"], config["dbpass"], config["dbname"])
            relays = []
            # TODO: Implement the main finder logic here
        except Exception as e:
            logging.exception(f"❌ Finder encountered an error: {e}")
        await asyncio.sleep(config["frequency_hour"] * 3600)


if __name__ == "__main__":
    try:
        asyncio.run(finder())
    except Exception:
        logging.exception("❌ Finder failed to start.")
        sys.exit(1)
