import os
import sys
import time
import logging
from bigbrotr import Bigbrotr
from relay import Relay

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
            "relays_seed_path": str(os.environ["RELAYS_SEED_PATH"])
        }
        if config["dbport"] < 0 or config["dbport"] > 65535:
            logging.error("❌ Invalid database port number.")
            sys.exit(1)
    except KeyError as e:
        logging.error(f"❌ Missing environment variable: {e}")
        sys.exit(1)
    except ValueError as e:
        logging.error(f"❌ Invalid environment variable value: {e}")
        sys.exit(1)
    return config
    

# --- Database Connection ---
def test_database_connection(config):
    logging.info(
        f"🔌 Testing database connection to {config['dbhost']}:{config['dbport']}/{config['dbname']}")
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


# --- Insert Relays ---
def insert_relays(config):
    logging.info("🌐 Starting relay insertion process...")
    try:
        with open(config["relays_seed_path"], 'r') as f:
            lines = f.read().splitlines()
        relays = []
        for raw_url in lines:
            try:
                relay = Relay(raw_url)
                relays.append(relay)
            except (ValueError, TypeError) as e:
                logging.warning(
                    f"⚠️ Invalid relay URL skipped: {raw_url}. Reason: {e}")
        if relays:
            db = Bigbrotr(config["dbhost"], config["dbport"],
                          config["dbuser"], config["dbpass"], config["dbname"])
            db.connect()
            db.insert_relay_batch(relays)
            logging.info(f"✅ Inserted {len(relays)} valid relays.")
            db.close()
        else:
            logging.warning("⚠️ No valid relays to insert.")
    except FileNotFoundError:
        logging.error(
            f"❌ Relay seed file not found: {config['relays_seed_path']}")
    except Exception as e:
        logging.exception(f"❌ Unexpected error during relay insertion: {e}")


# --- Retry Logic for Database ---
def wait_for_database_connection(config, retries=5, delay=10):
    for attempt in range(1, retries + 1):
        time.sleep(delay)
        try:
            test_database_connection(config)
            return
        except Exception as e:
            logging.warning(
                f"⏳ Database not ready (attempt {attempt}/{retries}): {e}. Retrying in {delay} seconds...")
    raise RuntimeError("❌ Database not available after retries.")


# --- Main Entry Point ---
def initializer():
    config = load_config_from_env()
    logging.info("🔍 Starting initializer...")
    wait_for_database_connection(config)
    insert_relays(config)
    logging.info("✅ Initializer completed successfully.")


# --- Monitor Entrypoint ---
if __name__ == "__main__":
    try:
        logging.info("🚀 Starting initializer...")
        initializer()
    except Exception as e:
        logging.exception("❌ Initializer failed.")
        sys.exit(1)
