import time
import logging
from bigbrotr import Bigbrotr
from nostr_tools import Event, Client, Filter, stream_events


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


def get_start_time(default_start_time, bigbrotr, relay, retries=5, delay=30):
    """Get the starting timestamp for event synchronization from database."""
    def get_max_seen_at():
        query = """
            SELECT MAX(seen_at)
            FROM events_relays
            WHERE relay_url = %s
        """
        bigbrotr.execute(query, (relay.url,))
        return bigbrotr.fetchone()[0]

    def get_event_id(max_seen_at):
        query = """
            SELECT event_id
            FROM events_relays
            WHERE relay_url = %s AND seen_at = %s
            LIMIT 1
        """
        bigbrotr.execute(query, (relay.url, max_seen_at))
        return bigbrotr.fetchone()[0]

    def get_created_at(event_id):
        query = """
            SELECT created_at
            FROM events
            WHERE id = %s
        """
        bigbrotr.execute(query, (event_id,))
        return bigbrotr.fetchone()[0]

    max_seen_at_todo = True
    max_seen_at = None
    event_id_todo = True
    event_id = None
    created_at_todo = True
    created_at = None
    bigbrotr.connect()

    for attempt in range(retries):
        try:
            if max_seen_at_todo:
                max_seen_at = get_max_seen_at()
                max_seen_at_todo = False
            if max_seen_at is not None:
                if event_id_todo:
                    event_id = get_event_id(max_seen_at)
                    event_id_todo = False
                if event_id is not None:
                    if created_at_todo:
                        created_at = get_created_at(event_id)
                        created_at_todo = False
                    if created_at is not None:
                        return created_at + 1
            return default_start_time
        except Exception as e:
            logging.warning(
                f"⚠️ Attempt {attempt + 1}/{retries} failed while getting start time for {relay.url}: {e}")
            time.sleep(delay)

    bigbrotr.close()
    raise RuntimeError(
        f"❌ Failed to get start time for {relay.url} after {retries} attempts. Last error: {e}")


# async def get_max_limit(client, filter):
#     """
#     Compute the actual maximum limit supported by the relay.
#     """
#     if not isinstance(filter, Filter) or not filter.is_valid or filter.since is None or filter.until is None:
#         return None
#     min_created_at = None
#     first_count = 0
#     second_count = 0
#     async with client:
#         async for event in stream_events(client, filter):
#             first_count += 1
#             min_created_at = min(
#                 min_created_at if min_created_at is not None else event.created_at,
#                 event.created_at
#             )
#         if min_created_at is not None:
#             filter.until = min_created_at - 1
#             if filter.is_valid:
#                 async for event in stream_events(client, filter):
#                     second_count += 1
#     if second_count > 0:
#         return first_count
#     return None


def insert_batch(bigbrotr, batch, relay, seen_at):
    """Insert batch of events into database."""
    event_batch = []
    for event_data in batch:
        try:
            event = Event.from_dict(event_data)
            event_batch.append(event)
        except Exception as e:
            logging.warning(
                f"⚠️ Invalid event found in {relay.url}. Error: {e}")
            continue

    if event_batch:
        bigbrotr.insert_event_batch(event_batch, relay, seen_at)
    return len(event_batch)


async def process_relay(bigbrotr: Bigbrotr, client: Client, filter: Filter):
    # check arguments
    for argument, argument_type in zip([bigbrotr, client, filter], [Bigbrotr, Client, Filter]):
        if not isinstance(argument, argument_type):
            raise ValueError(
                f"{argument} must be an instance of {argument_type}")
        if not argument.is_valid:
            raise ValueError(f"{argument} must be valid")
    if bigbrotr.is_connected:
        raise ValueError("bigbrotr must be disconnected")
    if client.is_connected:
        raise ValueError("client must be disconnected")
    if filter.since is None or filter.until is None:
        raise ValueError("filter must have since and until")
    # logic
    async with bigbrotr:
        async with client:
            old_batch = []
            batch = []
            while True:
                subfilter = Filter.from_dict(filter.to_dict())
                subscription_id = client.subscribe(subfilter)
                async for message in client.listen_events(subscription_id):
                    event_data = message[2]
                    if isinstance(event_data, dict):
                        created_at = event_data.get('created_at')
                        if isinstance(created_at, int) and filter.since <= created_at <= filter.until:
                            batch.append(event_data)
                client.unsubscribe(subscription_id)
                # TODO: implement batching not using max_limit
                # IDEA: terminate when you find empty batch and so is possible to insert the previous batch
                if batch:
                    old_batch = batch
                else:
                    insert_batch(bigbrotr, old_batch,
                                 client.relay, int(time.time()))
                    old_batch = []
                    batch = []
            pass
    return
