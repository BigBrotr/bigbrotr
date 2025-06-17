from syncronizer import *

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 single_syncronizer.py <relay_url>")
        sys.exit(1)
    relay_url = sys.argv[1]
    config = {
        "torhost": "localhost",
        "torport": 9050,
        "dbhost": "localhost",
        "dbport": 5432,
        "dbuser": "admin",
        "dbpass": "admin",
        "dbname": "bigbrotr",
        "timeout": 20,
        "filter": {},
        "start": 0
    }
    relay = Relay(relay_url)
    while True:
        end_time = int(time.time()) - 60 * 60 * 24
        try:
            asyncio.run(process_relay(config, relay, end_time))
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(30)