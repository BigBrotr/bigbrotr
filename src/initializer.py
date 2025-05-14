import os
import time
import logging
from bigbrotr import Bigbrotr
from relay import Relay

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)


def initializer():
    host = os.getenv('POSTGRES_HOST')
    port = int(os.getenv('POSTGRES_PORT'))
    user = os.getenv('POSTGRES_USER')
    password = os.getenv('POSTGRES_PASSWORD')
    dbname = os.getenv('POSTGRES_DB')
    bigbrotr = Bigbrotr(host, port, user, password, dbname)
    while True:
        try:
            bigbrotr.connect()
            logging.info("Connected to the database.")
            break
        except Exception as e:
            logging.error(f"Connection failed: {e}. Retrying in 5 seconds...")
            time.sleep(5)
    try:
        with open('relays_seed.txt', 'r') as f:
            relays = f.read().splitlines()
        relays = [Relay(relay) for relay in relays]
        bigbrotr.insert_relay_batch(relays)
        logging.info("Relays inserted successfully.")
    except Exception as e:
        logging.error(f"Failed initializer: {e}")
    finally:
        bigbrotr.close()
        logging.info("Database connection closed.")


if __name__ == "__main__":
    logging.info("Starting initializer...")
    time.sleep(5)
    try:
        initializer()
        logging.info("Initializer completed successfully.")
    except Exception as e:
        logging.error(f"Initializer failed: {e}")
