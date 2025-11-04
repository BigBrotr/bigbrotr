import asyncio
import logging
import time
from typing import Dict, Any, List

from bigbrotr import BigBrotr
from nostr_tools import Relay
from nostr_tools.exceptions.errors import RelayValidationError

from config import load_initializer_config
from functions import wait_for_services
from logging_config import setup_logging

# Setup logging
setup_logging("INITIALIZER")


# --- Insert Relays ---
async def insert_relays(config: Dict[str, Any]) -> None:
    """Insert seed relays into the database."""
    logging.info("🌐 Starting relay insertion process...")
    try:
        with open(config["seed_relays_path"], 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
        relays: List[Relay] = []
        for raw_url in lines:
            raw_url = raw_url.strip()
            if not raw_url or raw_url.startswith("#"):
                # Skip empty lines and comments
                continue
            try:
                relay = Relay(raw_url)
                relays.append(relay)
            except (ValueError, TypeError, RelayValidationError) as e:
                logging.warning(
                    f"⚠️ Invalid relay URL skipped: {raw_url}. Reason: {e}")
        if relays:
            async with BigBrotr(
                config["database_host"],
                config["database_port"],
                config["database_user"],
                config["database_password"],
                config["database_name"]
            ) as db:
                await db.insert_relay_batch(relays, int(time.time()))
                logging.info(f"✅ Inserted {len(relays)} valid relays.")
        else:
            logging.warning("⚠️ No valid relays to insert.")
    except FileNotFoundError:
        logging.error(
            f"❌ Relay seed file not found: {config['seed_relays_path']}")
    except Exception as e:
        logging.exception(f"❌ Unexpected error during relay insertion: {e}")


# --- Main Entry Point ---
async def initializer() -> None:
    """Initialize the database with seed relays."""
    config = load_initializer_config()

    # Wait for database to be available
    await wait_for_services(config, retries=5, delay=10)

    await insert_relays(config)


# --- Initializer Entrypoint ---
if __name__ == "__main__":
    try:
        logging.info("🚀 Starting initializer...")
        asyncio.run(initializer())
        logging.info("✅ Initializer completed successfully.")
    except Exception as e:
        import sys
        logging.exception("❌ Initializer failed.")
        sys.exit(1)
