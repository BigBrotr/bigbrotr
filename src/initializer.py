import os
import time
import logging
import sys
from bigbrotr import Bigbrotr
from relay import Relay

# --- Logging Config ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)


# --- Load Config ---
def load_config_from_env():
    try:
        return {
            "dbhost": os.environ["POSTGRES_HOST"],
            "dbuser": os.environ["POSTGRES_USER"],
            "dbpass": os.environ["POSTGRES_PASSWORD"],
            "dbname": os.environ["POSTGRES_DB"],
            "dbport": int(os.environ["POSTGRES_PORT"]),
            "relays_seed_path": os.environ["RELAYS_SEED_PATH"]
        }
    except KeyError as e:
        logging.error(f"❌ Missing environment variable: {e}")
        sys.exit(1)
    except ValueError as e:
        logging.error(f"❌ Invalid environment variable value: {e}")
        sys.exit(1)


# --- Insert Relays ---
def initializer():
    config = load_config_from_env()
    # Initialize DB instance
    try:
        db = Bigbrotr(config["dbhost"], config["dbport"],
                      config["dbuser"], config["dbpass"], config["dbname"])
    except TypeError as e:
        logging.error(f"❌ Invalid DB connection parameters: {e}")
        return
    # Connect to database with retries
    while True:
        try:
            db.connect()
            logging.info("✅ Connected to the database.")
            break
        except Exception as e:
            logging.warning(
                f"🔌 Connection failed: {e}. Retrying in 5 seconds...")
            time.sleep(5)
    # Read and insert relays
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
            db.insert_relay_batch(relays)
            logging.info(f"✅ Inserted {len(relays)} valid relays.")
        else:
            logging.warning("⚠️ No valid relays to insert.")
    except FileNotFoundError:
        logging.error(
            f"❌ Relay seed file not found: {config['relays_seed_path']}")
    except Exception as e:
        logging.exception(f"❌ Unexpected error during relay insertion: {e}")
    finally:
        db.close()
        logging.info("🔌 Database connection closed.")


# --- Entrypoint ---
if __name__ == "__main__":
    logging.info("🚀 Starting initializer...")
    time.sleep(5)
    try:
        initializer()
        logging.info("✅ Initializer completed successfully.")
    except Exception as e:
        logging.exception("❌ Initializer failed.")
        sys.exit(1)
