import os
import sys
import time
import uuid
import json
import asyncio
import logging
from relay import Relay
from event import Event
from bigbrotr import Bigbrotr
from relay_metadata import RelayMetadata
from aiohttp_socks import ProxyConnector
from multiprocessing import Pool, cpu_count
from aiohttp import ClientSession, WSMsgType

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


# --- Chunkify Function ---
def chunkify(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


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
            "num_cores": int(os.environ["SYNCRONIZER_NUM_CORES"]),
            "chunk_size": int(os.environ["SYNCRONIZER_CHUNK_SIZE"]),
            "requests_per_core": int(os.environ["SYNCRONIZER_REQUESTS_PER_CORE"]),
            "timeout": int(os.environ["SYNCRONIZER_REQUEST_TIMEOUT"]),
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
            logging.error("❌ Invalid SYNCRONIZER_NUM_CORES. Must be at least 1.")
            sys.exit(1)
        if config["chunk_size"] < 1:
            logging.error("❌ Invalid SYNCRONIZER_CHUNK_SIZE. Must be at least 1.")
            sys.exit(1)
        if config["requests_per_core"] < 1:
            logging.error(
                "❌ Invalid SYNCRONIZER_REQUESTS_PER_CORE. Must be at least 1.")
            sys.exit(1)
        if config["timeout"] < 1:
            logging.error(
                "❌ Invalid SYNCRONIZER_REQUEST_TIMEOUT. Must be 1 or greater.")
            sys.exit(1)
        if config["num_cores"] > cpu_count():
            logging.warning(
                f"⚠️ SYNCRONIZER_NUM_CORES exceeds available CPU cores ({cpu_count()}).")
            config["num_cores"] = cpu_count()
            logging.info(
                f"🔄 SYNCRONIZER_NUM_CORES set to {config['num_cores']} (max available).")
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


# --- Tor Proxy Test ---
async def test_torproxy_connection(config, timeout=10):
    socks5_proxy_url = f"socks5://{config["torhost"]}:{config["torport"]}"
    # HTTP Test
    http_url = "https://check.torproject.org"
    connector = ProxyConnector.from_url(socks5_proxy_url)
    async with ClientSession(connector=connector) as session:
        try:
            logging.info("🌐 Testing Tor HTTP access...")
            async with session.get(http_url, timeout=timeout) as resp:
                text = await resp.text()
                if "Congratulations. This browser is configured to use Tor" in text:
                    logging.info("✅ HTTP response confirms Tor usage.")
                else:
                    raise RuntimeError("Tor usage not confirmed via HTTP.")
        except Exception:
            logging.exception("❌ HTTP test via Tor failed.")
            raise
        finally:
            await session.close()
            logging.info("🌐 HTTP connection closed.")
    # WebSocket Test
    ws_url = "wss://echo.websocket.events"
    connector = ProxyConnector.from_url(socks5_proxy_url)
    async with ClientSession(connector=connector) as session:
        try:
            logging.info("🌐 Testing Tor WebSocket access...")
            async with session.ws_connect(ws_url, timeout=timeout) as ws:
                await ws.send_str("Hello via WebSocket")
                msg = await ws.receive(timeout=timeout)
                if msg.type == WSMsgType.TEXT:
                    logging.info(f"✅ WebSocket message received: {msg.data}")
                else:
                    raise RuntimeError(
                        f"Unexpected WebSocket response: {msg.type}")
        except Exception:
            logging.exception("❌ WebSocket test via Tor failed.")
            raise
        finally:
            await ws.close()
            logging.info("🌐 WebSocket connection closed.")


# --- Wait for Services (Resilience) ---
async def wait_for_services(config, retries=5, delay=30):
    for attempt in range(1, retries + 1):
        await asyncio.sleep(delay)
        try:
            test_database_connection(config)
            await test_torproxy_connection(config)
            return
        except Exception as e:
            logging.warning(
                f"⏳ Service not ready (attempt {attempt}/{retries}): {e}")
    raise RuntimeError("❌ Required services not available after retries.")


# --- Process Chunk ---
async def process_chunk(chunk, config, end_time):
    socks5_proxy_url = f"socks5://{config['torhost']}:{config['torport']}"
    requests_per_core = config["requests_per_core"]
    sem = asyncio.Semaphore(requests_per_core)
    async def process_single_relay_metadata(relay_metadata):
        async with sem:
            n_events = 0
            try:
                bigbrotr = Bigbrotr(config["dbhost"], config["dbport"], config["dbuser"], config["dbpass"], config["dbname"])
                query = """
                    SELECT MAX(e.created_at) AS max_created_at
                    FROM events e
                    JOIN events_relays er ON e.id = er.event_id
                    WHERE er.relay_url = %s;
                """
                bigbrotr.connect()
                bigbrotr.execute(query, (relay_metadata.relay.url,))
                row = bigbrotr.fetchone()
                start_time = row[0]+1 if row and row[0] is not None else 0
                timeout = config["timeout"]
                subscription_id = uuid.uuid4().hex
                try:
                    max_limit = relay_metadata.limitation.get('max_limit') if isinstance(relay_metadata.limitation, dict) else None
                    max_limit = int(max_limit) if max_limit is not None else None
                    max_limit = max_limit if max_limit > 0 else None
                except (ValueError, TypeError):
                    max_limit = None
                batch_size = max(int(max_limit * 1.1), 1000) if max_limit is not None else 1000 # by costruction the batch size will be at least 10% more large than the max_limit
                connector = ProxyConnector.from_url(socks5_proxy_url) if relay_metadata.relay.network == 'tor' else None
                async with ClientSession(connector=connector) as session:
                    async with session.ws_connect(relay_metadata.relay.url, timeout=timeout) as ws:
                        # start_time and end_time is the time range to fetch
                        while start_time <= end_time:
                            # since and until is the time range that we are trying to fetch
                            since = start_time
                            until = end_time
                            # here by costruction we will fetch an  intervall starting from since and arrive to until. 
                            # after that start_time will be set to until + 1
                            while since <= until:
                                request = json.dumps([
                                    "REQ", subscription_id, {
                                        "since": since,
                                        "until": until,
                                    }
                                ])
                                buffer = []
                                buffer_len = 0
                                buffer_timestamps = set()
                                n_event_msgs_received = 0
                                await ws.send_str(request)
                                while True:
                                    msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
                                    if msg.type == WSMsgType.TEXT:
                                        data = json.loads(msg.data)
                                        if data[0] == "NOTICE":
                                            continue
                                        elif data[0] == "EVENT" and data[1] == subscription_id:
                                            n_event_msgs_received += 1
                                            try:
                                                event = Event.from_dict(data[2])
                                                if event.created_at >= since and event.created_at <= until:
                                                    buffer.append(event)
                                                    buffer_len += 1
                                                    buffer_timestamps.add(event.created_at)
                                            except (TypeError, ValueError) as e:
                                                continue

                                            if max_limit is not None:
                                                if n_event_msgs_received >= max_limit and since != until:
                                                        until = since + (until - since) // 2
                                                        break
                                            else:
                                                if buffer_len >= batch_size and len(buffer_timestamps) > 1:
                                                    max_timestamp = max(buffer_timestamps)
                                                    events = [e for e in buffer if e.created_at != max_timestamp]
                                                    bigbrotr.insert_event_batch(events, relay_metadata.relay.url, int(time.time()))
                                                    n_events += len(events)
                                                    buffer = [e for e in buffer if e.created_at == max_timestamp]
                                                    buffer_len = len(buffer)
                                                    buffer_timestamps = set([max_timestamp])
                                                    start_time = max_timestamp
                                                    since = max_timestamp
                                        elif data[0] == "EOSE" and data[1] == subscription_id:
                                            if buffer_len > 0:
                                                max_timestamp = max(buffer_timestamps)
                                                bigbrotr.insert_event_batch(buffer, relay_metadata.relay.url, int(time.time()))
                                                n_events += len(buffer)
                                                buffer = []
                                                buffer_len = 0
                                                buffer_timestamps = set()
                                                start_time = max_timestamp + 1
                                                since = max_timestamp + 1
                                            else:
                                                start_time = until + 1
                                                since = until + 1
                                            break
            except Exception as e:
                logging.exception(
                    f"❌ Error processing relay metadata for {relay_metadata.relay.url}: {e}")
            finally:
                if 'bigbrotr' in locals():
                    bigbrotr.close()
            return n_events
    tasks = [process_single_relay_metadata(relay_metadata) for relay_metadata in chunk]
    n_events_list = await asyncio.gather(*tasks)
    logging.info(f"🔄 Processed chunk of {len(chunk)} relay metadata. Total new events inserted: {sum(n_events_list)}")
    return


# --- Worker Function ---
def worker(chunk, config, end_time):
    async def worker_async(chunk, config, end_time):
        return await process_chunk(chunk, config, end_time)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(worker_async(chunk, config, end_time))


# --- Fetch Relay Metadata List from Database ---
def fetch_relay_metedata_list(bigbrotr):
    bigbrotr.connect()
    logging.info("🔌 Database connection established.")
    logging.info("📦 Fetching relay metadata from database...")
    query = "SELECT * FROM relay_metadata WHERE generated_at = (SELECT MAX(generated_at) FROM relay_metadata)"
    bigbrotr.execute(query)
    rows = bigbrotr.fetchall()
    bigbrotr.close()
    relay_metadata_list = []
    for row in rows:
        try:
            relay = Relay(row[0])
            relay_metadata = RelayMetadata(
                relay.url,
                **{
                    "generated_at": row[1],
                    "connection_success": row[2],
                    "nip11_success": row[3],
                    "openable": row[4],
                    "readable": row[5],
                    "writable": row[6],
                    "rtt_open": row[7],
                    "rtt_read": row[8],
                    "rtt_write": row[9],
                    "name": row[10],
                    "description": row[11],
                    "banner": row[12],
                    "icon": row[13],
                    "pubkey": row[14],
                    "contact": row[15],
                    "supported_nips": row[16],
                    "software": row[17],
                    "version": row[18],
                    "privacy_policy": row[19],
                    "terms_of_service": row[20],
                    "limitation": row[21],
                    "extra_fields": row[22]
                }
            )
            relay_metadata_list.append(relay_metadata)
        except Exception as e:
            logging.warning(
                f"⚠️ Invalid relay metadata: {row}. Error: {e}")
            continue
    logging.info(f"📦 {len(relay_metadata_list)} relay metadata fetched from database.")
    return relay_metadata_list


# --- Main Loop ---
async def main_loop(config):
    bigbrotr = Bigbrotr(config["dbhost"], config["dbport"],
                        config["dbuser"], config["dbpass"], config["dbname"])
    relay_metedata_list = fetch_relay_metedata_list(bigbrotr)
    chunk_size = config["chunk_size"]
    num_cores = config["num_cores"]
    chunks = list(chunkify(relay_metedata_list, chunk_size))
    end_time = int(time.time())
    args = [(chunk, config, end_time) for chunk in chunks]
    logging.info(
        f"🔄 Processing {len(chunks)} chunks with {num_cores} cores...")
    with Pool(processes=num_cores) as pool:
        pool.starmap(worker, args)
    logging.info("✅ All chunks processed successfully.")
    return


# --- Syncronizer Entrypoint ---
async def syncronizer():
    config = load_config_from_env()
    logging.info("🔄 Starting Syncronizer...")
    await wait_for_services(config)
    while True:
        try:
            logging.info("🔄 Starting main loop...")
            await main_loop(config)
            logging.info("✅ Main loop completed successfully.")
        except Exception as e:
            logging.exception(f"❌ Main loop failed: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(syncronizer())
    except Exception:
        logging.exception("❌ Syncronizer failed to start.")
        sys.exit(1)
