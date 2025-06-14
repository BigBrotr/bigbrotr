from syncronizer import process_relay
from relay import Relay
import time
import logging
import asyncio

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

end_time = int(time.time()) - 60 * 60 * 12 # 12 hours ago
config = {
    "dbhost": "localhost",
    "dbport": 5432,
    "dbuser": "admin",
    "dbpass": "admin",
    "dbname": "bigbrotr",
    "timeout": 20,
    "start": 0,
    "filter": {},
    "torhost": "localhost",
    "torport": 9050
}
relay = Relay('wss://relay.nostr.band')

async def main_loop():
    while True:
        try:
            await process_relay(config, relay, end_time)
        except Exception as e:
            print(f"Error processing relay metadata: {e}")
        print("Sleeping for 20 seconds before next iteration...")
        await asyncio.sleep(20)

if __name__ == "__main__":
    asyncio.run(main_loop())