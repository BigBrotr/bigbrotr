import os
import re
import sys
import time
import uuid
import json
import asyncio
import logging
import datetime
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
            "start": int(os.environ["SYNCTONIZER_START_TIMESTAMP"]),
            "stop": int(os.environ["SYNCTONIZER_STOP_TIMESTAMP"]),
            "filter": json.loads(os.environ["SYNCRONIZER_EVENT_FILTER"])
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
                "❌ Invalid SYNCRONIZER_NUM_CORES. Must be at least 1.")
            sys.exit(1)
        if config["chunk_size"] < 1:
            logging.error(
                "❌ Invalid SYNCRONIZER_CHUNK_SIZE. Must be at least 1.")
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
        if config["start"] < 0:
            logging.error(
                "❌ Invalid SYNCTONIZER_START_TIMESTAMP. Must be 0 or greater.")
            sys.exit(1)
        if config["stop"] != -1 and config["stop"] < 0:
            logging.error(
                "❌ Invalid SYNCTONIZER_STOP_TIMESTAMP. Must be 0 or greater.")
            sys.exit(1)
        if config["stop"] != -1 and config["start"] > config["stop"]:
            logging.error(
                "❌ SYNCTONIZER_START_TIMESTAMP cannot be greater than SYNCTONIZER_STOP_TIMESTAMP.")
            sys.exit(1)
        if not isinstance(config["filter"], dict):
            logging.error(
                "❌ SYNCRONIZER_EVENT_FILTER must be a valid JSON object.")
            sys.exit(1)
        config["filter"] = {k: v for k, v in config["filter"].items() if k in {"ids", "authors", "kinds"} or re.fullmatch(r"#([a-zA-Z])", k)}
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
            batch_size = 1000
            timeout = config["timeout"]
            stack_size = 10000
            until_stack = [end_time]
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
                start_time = row[0] + 1 if row and row[0] is not None else config["start"]
                try:
                    max_limit = relay_metadata.limitation.get('max_limit') if isinstance(
                        relay_metadata.limitation, dict) else None
                    max_limit = int(
                        max_limit) if max_limit is not None else None
                    max_limit = max_limit if max_limit > 0 else None
                except (ValueError, TypeError):
                    max_limit = None
                logging.info(f"🔄 Processing relay {relay_metadata.relay.url} with start_time={start_time}, end_time={end_time}, max_limit={max_limit}")
                connector = ProxyConnector.from_url(socks5_proxy_url) if relay_metadata.relay.network == 'tor' else None
                async with ClientSession(connector=connector) as session:
                    # logging.info(f"🔌 Connecting to relay: {relay_metadata.relay.url}")
                    async with session.ws_connect(relay_metadata.relay.url, timeout=timeout) as ws:
                        # logging.info(f"✅ WebSocket connection established with {relay_metadata.relay.url}")
                        while start_time <= end_time:
                            since = start_time
                            until = until_stack.pop()
                            # logging.info(f"📈 Starting to fetch events from {since} to {until} for {relay_metadata.relay.url}")
                            while since <= until:
                                subscription_id = uuid.uuid4().hex
                                # logging.info(f"🆔 Subscription ID: {subscription_id}")
                                request = json.dumps([
                                    "REQ", 
                                    subscription_id, 
                                    {**config["filter"], "since": since, "until": until}
                                ])
                                # logging.info(f"➡️ Sending request for events from {since} to {until}")
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
                                            logging.info(f"📢 NOTICE received from {relay_metadata.relay.url}: {data}")
                                            continue
                                        elif data[0] == "EVENT" and data[1] == subscription_id:
                                            n_event_msgs_received += 1
                                            try:
                                                event = Event.from_dict(
                                                    data[2])
                                                if since <= event.created_at and event.created_at <= until:
                                                    buffer.append(event)
                                                    buffer_len += 1
                                                    buffer_timestamps.add(
                                                        event.created_at)
                                            except (TypeError, ValueError) as e:
                                                logging.warning(f"⚠️ Invalid event data received from {relay_metadata.relay.url}: {data[2]}. Error: {e}")
                                                continue
                                            if max_limit is not None:
                                                if n_event_msgs_received >= max_limit and since != until:
                                                    # logging.info(f"⚠️ Max limit reached, reducing interval for {relay_metadata.relay.url}")
                                                    if len(until_stack) >= stack_size:
                                                        # logging.info(f"⚠️ Stack size exceeded, closing subscription for {relay_metadata.relay.url}")
                                                        await ws.send_str(json.dumps(["CLOSE", subscription_id]))
                                                        await asyncio.sleep(1)
                                                        raise RuntimeError(f"Stack size exceeded for {relay_metadata.relay.url}. Closing subscription.")
                                                    until_stack.append(until)
                                                    until = since + (until - since) // 2
                                                    await ws.send_str(json.dumps(["CLOSE", subscription_id]))
                                                    await asyncio.sleep(1)
                                                    # logging.info(f"🔒 Closed subscription {subscription_id} for {relay_metadata.relay.url}")
                                                    break
                                            else:
                                                if buffer_len >= batch_size and len(buffer_timestamps) > 1:
                                                    max_timestamp = max(buffer_timestamps)
                                                    events = [e for e in buffer if e.created_at != max_timestamp]
                                                    bigbrotr.insert_event_batch(events, relay_metadata.relay, int(time.time()))
                                                    # logging.info(f"✅ Inserted {len(events)} events into DB (excluding timestamp = {max_timestamp})")
                                                    n_events += len(events)
                                                    buffer = [e for e in buffer if e.created_at == max_timestamp]
                                                    buffer_len = len(buffer)
                                                    buffer_timestamps = set([max_timestamp])
                                                    start_time = max_timestamp
                                                    since = max_timestamp
                                        elif data[0] == "EOSE" and data[1] == subscription_id:
                                            start_time = until + 1
                                            since = until + 1
                                            # logging.info(f"📴 EOSE received from {relay_metadata.relay.url}")
                                            if buffer_len > 0:
                                                bigbrotr.insert_event_batch(buffer, relay_metadata.relay, int(time.time()))
                                                # logging.info(f"✅ Inserted final {len(buffer)} events into DB for interval ending at {until}")
                                                n_events += len(buffer)
                                            else:
                                                # logging.info(f"⏭️ No new events, moving start_time to {until + 1}")
                                                pass
                                            await ws.send_str(json.dumps(["CLOSE", subscription_id]))
                                            # logging.info(f"🔒 Closed subscription {subscription_id} for {relay_metadata.relay.url}")
                                            await asyncio.sleep(1)
                                            break
                                        else:
                                            raise RuntimeError(f"Unexpected message format from {relay_metadata.relay.url}: {data}")
                                    else:
                                        raise RuntimeError(f"Unexpected message type from {relay_metadata.relay.url}: {msg.type}")       
            except Exception as e:
                logging.warning(e)
            finally:
                if 'bigbrotr' in locals():
                    bigbrotr.close()
                    # logging.info(f"🔒 Database connection closed for relay {relay_metadata.relay.url}")
            logging.info(f"✅ Finished processing {relay_metadata.relay.url} — Total events inserted: {n_events}")
            return

    tasks = [process_single_relay_metadata(relay_metadata) for relay_metadata in chunk]
    await asyncio.gather(*tasks)
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
            relay_metadata = RelayMetadata.from_dict(
                {
                    "relay": Relay(row[0]),
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
    logging.info(
        f"📦 {len(relay_metadata_list)} relay metadata fetched from database.")
    return relay_metadata_list


# --- Main Loop ---
async def main_loop(config):
    bigbrotr = Bigbrotr(config["dbhost"], config["dbport"],
                        config["dbuser"], config["dbpass"], config["dbname"])
    relay_metedata_list = fetch_relay_metedata_list(bigbrotr)
    chunk_size = config["chunk_size"]
    num_cores = config["num_cores"]
    chunks = list(chunkify(relay_metedata_list, chunk_size))
    if config["stop"] != -1:
        end_time = config["stop"]
    else:
        now = datetime.datetime.now()
        end_time = int(datetime.datetime(now.year, now.month, now.day, 0, 0).timestamp())
    logging.info(f"📅 End time for processing: {end_time}")
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
        logging.info("⏳ Retrying in 30 seconds...")
        await asyncio.sleep(30)


if __name__ == "__main__":
    try:
        asyncio.run(syncronizer())
    except Exception:
        logging.exception("❌ Syncronizer failed to start.")
        sys.exit(1)