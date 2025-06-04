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
from aiohttp import ClientSession, WSMsgType, TCPConnector

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
            "stop": int(os.environ["SYNCRONIZER_STOP_TIMESTAMP"]),
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
        if config["start"] < 0:
            logging.error(
                "❌ Invalid SYNCTONIZER_START_TIMESTAMP. Must be 0 or greater.")
            sys.exit(1)
        if config["stop"] != -1 and config["stop"] < 0:
            logging.error(
                "❌ Invalid SYNCRONIZER_STOP_TIMESTAMP. Must be 0 or greater.")
            sys.exit(1)
        if config["stop"] != -1 and config["start"] > config["stop"]:
            logging.error(
                "❌ SYNCTONIZER_START_TIMESTAMP cannot be greater than SYNCRONIZER_STOP_TIMESTAMP.")
            sys.exit(1)
        if config["num_cores"] > cpu_count():
            logging.warning(
                f"⚠️ SYNCRONIZER_NUM_CORES exceeds available CPU cores ({cpu_count()}).")
            config["num_cores"] = cpu_count()
            logging.info(
                f"🔄 SYNCRONIZER_NUM_CORES set to {config['num_cores']} (max available).")
        if not isinstance(config["filter"], dict):
            logging.error(
                "❌ SYNCRONIZER_EVENT_FILTER must be a valid JSON object.")
            sys.exit(1)
        config["filter"] = {k: v for k, v in config["filter"].items(
        ) if k in {"ids", "authors", "kinds"} or re.fullmatch(r"#([a-zA-Z])", k)}
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
    connector = ProxyConnector.from_url(socks5_proxy_url, force_close=True)
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
    connector = ProxyConnector.from_url(socks5_proxy_url, force_close=True)
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


# --- Get Start Time ---
def get_start_time(config, bigbrotr, relay_metadata):
    query = """
        SELECT MAX(e.created_at) AS max_created_at
        FROM events e
        JOIN events_relays er ON e.id = er.event_id
        WHERE er.relay_url = %s;
    """
    bigbrotr.execute(query, (relay_metadata.relay.url,))
    row = bigbrotr.fetchone()
    start_time = row[0] + 1 if row and row[0] is not None else config["start"]
    return start_time


# --- Get Max Limit ---
async def get_max_limit(config, ws, timeout, start_time, end_time):
    n_events = [0, 0]
    min_created_at = None
    since = start_time
    until = end_time
    for attempt in range(2):
        subscription_id = uuid.uuid4().hex
        request = json.dumps([
            "REQ",
            subscription_id,
            {**config["filter"], "since": since, "until": until}
        ])
        await ws.send_str(request)
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
                if msg.type == WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if data[0] == "NOTICE":
                        continue
                    elif data[0] == "EVENT" and data[1] == subscription_id:
                        if attempt == 0:
                            if isinstance(data[2], dict) and "created_at" in data[2]:
                                if min_created_at is None or data[2]["created_at"] < min_created_at:
                                    min_created_at = data[2]["created_at"]
                        n_events[attempt] += 1
                    elif data[0] == "EOSE" and data[1] == subscription_id:
                        await ws.send_str(json.dumps(["CLOSE", subscription_id]))
                        await asyncio.sleep(1)
                        break
                    elif data[0] == "CLOSED" and data[1] == subscription_id:
                        break
                else:
                    break
            except Exception:
                break
        if attempt == 0:
            if min_created_at is not None:
                until = max(0, min(min_created_at, until) - 1)
            else:
                return None
    if n_events[1] > 0:
        return n_events[0]
    return None


# --- Create Event ---
def create_event(event_data):
    try:
        event = Event.from_dict(event_data)
    except ValueError as e:
        tags = []
        for tag in event_data['tags']:
            tag = [
                t.replace(r'\n', '\n').replace(r'\"', '\"').replace(r'\\', '\\').replace(
                    r'\r', '\r').replace(r'\t', '\t').replace(r'\b', '\b').replace(r'\f', '\f')
                for t in tag
            ]
            tags.append(tag)
        event_data['tags'] = tags
        event_data['content'] = event_data['content'].replace(r'\n', '\n').replace(r'\"', '\"').replace(
            r'\\', '\\').replace(r'\r', '\r').replace(r'\t', '\t').replace(r'\b', '\b').replace(r'\f', '\f')
        event = Event.from_dict(event_data)
    return event


# --- Insert Batch of Events ---
def insert_batch(bigbrotr, batch, relay, seen_at):
    event_batch = []
    for event_data in batch:
        try:
            event = create_event(event_data)
        except Exception as e:
            logging.warning(
                f"⚠️ Invalid event found in {relay.url}. Error: {e}")
            continue
        event_batch.append(event)
    bigbrotr.insert_event_batch(event_batch, relay, seen_at)
    return len(event_batch)


# --- Process Relay Metadata ---
async def process_relay_metadata(config, relay_metadata, end_time):
    socks5_proxy_url = f"socks5://{config['torhost']}:{config['torport']}"
    bigbrotr = Bigbrotr(config["dbhost"], config["dbport"],
                        config["dbuser"], config["dbpass"], config["dbname"])
    bigbrotr.connect()
    if relay_metadata.relay.network == 'tor':
        connector = ProxyConnector.from_url(socks5_proxy_url, force_close=True)
    else:
        connector = TCPConnector(force_close=True)
    async with ClientSession(connector=connector) as session:
        for schema in ['wss://', 'ws://']:
            try:
                start_time = get_start_time(config, bigbrotr, relay_metadata)
                relay_id = relay_metadata.relay.url.removeprefix('wss://')
                timeout = config["timeout"]
                n_events_inserted = 0
                n_requests_done = 0
                n_writes = 0
                stack = [end_time]
                stack_max_size = 1000
                async with session.ws_connect(schema + relay_id, timeout=timeout) as ws:
                    max_limit = await get_max_limit(config, ws, timeout, start_time, end_time)
                    max_limit = max_limit if max_limit is not None else 1000
                    max_limit = min(max_limit, 10000)
                    max_limit = max(1, max_limit - 50)
                    while start_time <= end_time and n_writes < 1000:
                        since = start_time
                        until = stack.pop()
                        while since <= until and n_writes < 1000:
                            if n_requests_done % 25 == 0:
                                logging.info(
                                    f"🔄 [Processing {relay_metadata.relay.url}] [from {since}] [to {until}] [max limit {max_limit}] [requests done {n_requests_done} ({n_writes} with events)] [requests todo {len(stack)+1}] [events inserted {n_events_inserted}]")
                            subscription_id = uuid.uuid4().hex
                            batch = []
                            request = json.dumps([
                                "REQ",
                                subscription_id,
                                {**config["filter"],
                                    "since": since, "until": until}
                            ])
                            await ws.send_str(request)
                            while True:
                                msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
                                if msg.type == WSMsgType.TEXT:
                                    data = json.loads(msg.data)
                                    if data[0] == "NOTICE":
                                        logging.info(
                                            f"📢 NOTICE received from {relay_metadata.relay.url}: {data}")
                                        continue
                                    elif data[0] == "EVENT" and data[1] == subscription_id:
                                        batch.append(data[2])
                                    elif data[0] == "EOSE" and data[1] == subscription_id:
                                        await ws.send_str(json.dumps(["CLOSE", subscription_id]))
                                        await asyncio.sleep(1)
                                        break
                                    elif data[0] == "CLOSED" and data[1] == subscription_id:
                                        break
                                    if len(batch) >= max_limit and since != until:
                                        stack.append(until)
                                        until = since + \
                                            (until - since) // 2
                                        if len(stack) > stack_max_size:
                                            stack.pop(0)
                                            end_time = stack[0]
                                        await ws.send_str(json.dumps(["CLOSE", subscription_id]))
                                        await asyncio.sleep(1)
                                        break
                                else:
                                    raise RuntimeError(
                                        f"Unexpected message type: {msg.type} from {relay_metadata.relay.url}")
                            if len(batch) < max_limit or since == until:
                                n_events_inserted += insert_batch(
                                    bigbrotr, batch, relay_metadata.relay, int(time.time()))
                                start_time = until + 1
                                since = until + 1
                                n_writes += 1
                            n_requests_done += 1
                break
            except Exception as e:
                logging.warning(
                    f"⚠️ Unexpected error while processing {relay_metadata.relay.url}: {e}")
                if 'session' in locals():
                    await session.close()
                if 'ws' in locals():
                    await ws.close()
    if 'bigbrotr' in locals():
        bigbrotr.close()
    logging.info(
        f"✅ Finished processing {relay_metadata.relay.url}. Total events inserted: {n_events_inserted}")
    return


# --- Process Chunk ---
async def process_chunk(chunk, config, end_time):
    semaphore = asyncio.Semaphore(config["requests_per_core"])

    async def sem_task(relay_metadata):
        async with semaphore:
            try:
                await process_relay_metadata(config, relay_metadata, end_time)
            except Exception as e:
                logging.exception(
                    f"❌ Error processing {relay_metadata.relay.url}: {e}")

    tasks = [sem_task(relay_metadata) for relay_metadata in chunk]
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
def fetch_relay_metedata_list(config):
    bigbrotr = Bigbrotr(config["dbhost"], config["dbport"],
                        config["dbuser"], config["dbpass"], config["dbname"])
    bigbrotr.connect()
    logging.info("📦 Fetching relay metadata from database...")
    query = """
        SELECT *
        FROM relay_metadata rm
        WHERE generated_at = (
            SELECT MAX(generated_at)
            FROM relay_metadata
            WHERE relay_url = rm.relay_url
        )
        AND generated_at > %s
        AND readable = TRUE
    """
    treshold = int(time.time()) - 60 * 60 * 12
    bigbrotr.execute(query, (treshold,))
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
            logging.warning(f"⚠️ Invalid relay metadata: {row}. Error: {e}")
            continue
    logging.info(
        f"📦 {len(relay_metadata_list)} relay metadata fetched from database.")
    return relay_metadata_list


# --- Main Loop ---
async def main_loop(config):
    relay_metedata_list = fetch_relay_metedata_list(config)
    chunk_size = config["chunk_size"]
    num_cores = config["num_cores"]
    chunks = list(chunkify(relay_metedata_list, chunk_size))
    if config["stop"] != -1:
        end_time = config["stop"]
    else:
        end_time = int(time.time()) - 60 * 60 * 24
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
            logging.info("⏳ Waiting 15 minutes before next run...")
            await asyncio.sleep(15 * 60)
        except Exception as e:
            logging.exception(f"❌ Main loop failed: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(syncronizer())
    except Exception:
        logging.exception("❌ Syncronizer failed to start.")
        sys.exit(1)
