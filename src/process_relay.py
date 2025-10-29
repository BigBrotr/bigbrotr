import time
import logging
import asyncio
from typing import Optional, List, Dict, Any
from bigbrotr import Bigbrotr
from nostr_tools import Event, Client, Filter, Relay

from logging_config import setup_logging


async def get_start_time_async(
    default_start_time: int,
    bigbrotr: Bigbrotr,
    relay: Relay,
    retries: int = 5,
    delay: int = 30
) -> int:
    """Get the starting timestamp for event synchronization from database (async version)."""
    for attempt in range(retries):
        try:
            # Get max seen_at for this relay
            query = """
                SELECT MAX(seen_at)
                FROM events_relays
                WHERE relay_url = $1
            """
            result = await bigbrotr.fetchone(query, relay.url)
            max_seen_at = result[0] if result else None

            if max_seen_at is None:
                return default_start_time

            # Get event_id for that seen_at
            query = """
                SELECT event_id
                FROM events_relays
                WHERE relay_url = $1 AND seen_at = $2
                LIMIT 1
            """
            result = await bigbrotr.fetchone(query, relay.url, max_seen_at)
            event_id = result[0] if result else None

            if event_id is None:
                return default_start_time

            # Get created_at for that event
            query = """
                SELECT created_at
                FROM events
                WHERE id = $1
            """
            result = await bigbrotr.fetchone(query, event_id)
            created_at = result[0] if result else None

            if created_at is not None:
                return created_at + 1
            return default_start_time

        except Exception as e:
            logging.warning(
                f"⚠️ Attempt {attempt + 1}/{retries} failed while getting start time for {relay.url}: {e}")
            await asyncio.sleep(delay)

    raise RuntimeError(
        f"❌ Failed to get start time for {relay.url} after {retries} attempts.")


async def insert_batch(
    bigbrotr: Bigbrotr,
    batch: List[Dict[str, Any]],
    relay: Relay,
    seen_at: int
) -> int:
    """Insert batch of events into database."""
    event_batch: List[Event] = []
    for event_data in batch:
        try:
            event = Event.from_dict(event_data)
            event_batch.append(event)
        except Exception as e:
            logging.warning(
                f"⚠️ Invalid event found in {relay.url}. Error: {e}")
            continue

    if event_batch:
        await bigbrotr.insert_event_batch(event_batch, relay, seen_at)
    return len(event_batch)


class RawEventBatch:
    """Batch container for raw Nostr events."""

    def __init__(self, since: int, until: int, limit: int) -> None:
        self.since: int = since
        self.until: int = until
        self.limit: int = limit
        self.size: int = 0
        self.raw_events: List[Dict[str, Any]] = []
        self.min_created_at: Optional[int] = None
        self.max_created_at: Optional[int] = None

    def append(self, raw_event: Dict[str, Any]) -> bool:
        """Append a raw event to the batch.

        Returns:
            True if event was added successfully, False if batch is full or event is invalid.
        """
        if not isinstance(raw_event, dict):
            return False
        created_at = raw_event.get("created_at")
        if not isinstance(created_at, int) or created_at < 0 or created_at < self.since or created_at > self.until:
            return False
        if self.size < self.limit:
            self.raw_events.append(raw_event)
            self.size += 1
            if self.min_created_at is None or created_at < self.min_created_at:
                self.min_created_at = created_at
            if self.max_created_at is None or created_at > self.max_created_at:
                self.max_created_at = created_at
            return True
        else:
            return False

    def is_full(self) -> bool:
        """Check if batch is full."""
        return self.size >= self.limit

    def is_empty(self) -> bool:
        """Check if batch is empty."""
        return self.size == 0


async def process_batch(client: Client, filter: Filter) -> RawEventBatch:
    """Process a batch of events from a relay."""
    batch = RawEventBatch(filter.since, filter.until, filter.limit)
    subscription_id = client.subscribe(filter)
    async for message in client.listen_events(subscription_id):
        if batch.is_full():
            break
        batch.append(message[2])
    client.unsubscribe(subscription_id)
    return batch


async def process_relay(bigbrotr: Bigbrotr, client: Client, filter: Filter) -> None:
    """Process relay events and insert them into the database."""
    # check arguments
    for argument, argument_type in zip([bigbrotr, client, filter], [Bigbrotr, Client, Filter]):
        if not isinstance(argument, argument_type):
            raise ValueError(
                f"{argument} must be an instance of {argument_type}")
        if not argument.is_valid:
            raise ValueError(f"{argument} must be valid")
    if bigbrotr.is_connected:
        raise ValueError("bigbrotr must be disconnected before calling process_relay")
    if client.is_connected:
        raise ValueError("client must be disconnected before calling process_relay")
    if filter.since is None or filter.until is None:
        raise ValueError("filter must have since and until")
    if filter.limit is None:
        raise ValueError("filter must have limit")
    # logic
    async with bigbrotr:
        async with client:
            until_stack = [filter.until]
            while until_stack:
                # fetch [since, until] interval
                filter.until = until_stack[0]
                first_batch = await process_batch(client, filter)
                if first_batch.is_empty():
                    # no events found -> interval [since, until] done
                    until_stack.pop(0)
                    filter.since = filter.until + 1
                elif filter.since == filter.until:
                    # events found AND [since, until] is one timestamp interval -> interval [since, until] done
                    await insert_batch(bigbrotr, first_batch.raw_events,
                                       client.relay, int(time.time()))
                    until_stack.pop(0)
                    filter.since = filter.until + 1
                else:
                    # Events found AND [since, until] is multiple timestamp interval
                    # Fetch [since, first_batch.min_created_at] interval
                    filter.until = first_batch.min_created_at
                    second_batch = await process_batch(client, filter)

                    # Check if relay behaved correctly
                    batch_min_matches = first_batch.min_created_at == second_batch.max_created_at
                    if second_batch.is_empty() or not batch_min_matches:
                        logging.warning(
                            f"⚠️ Relay {client.relay.url} returned unexpected results. Stopping processing.")
                        break
                    elif second_batch.min_created_at != first_batch.min_created_at:
                        # Found events in [since, first_batch.min_created_at - 1]
                        # First batch did not fetch all events - add mid point to stack
                        mid = (filter.until - filter.since) // 2 + filter.since
                        until_stack.insert(0, mid)
                    else:
                        # Found only first_batch.min_created_at events
                        # Fetch [since, first_batch.min_created_at - 1] interval
                        filter.until = first_batch.min_created_at - 1
                        filter.limit = 1
                        third_batch = await process_batch(client, filter)
                        if third_batch.is_empty():
                            # No events found - all events fetched
                            # Add fetched events to db
                            batch = [
                                raw_event for raw_event in first_batch.raw_events
                                if raw_event.get("created_at") != first_batch.min_created_at
                            ]
                            batch.extend(second_batch.raw_events)
                            await insert_batch(bigbrotr, batch,
                                               client.relay, int(time.time()))
                            filter.since = until_stack.pop(0) + 1
                        else:
                            # events found -> not all events fetched -> add mid point to stack
                            mid = (filter.until - filter.since) // 2 + \
                                filter.since
                            until_stack.insert(0, mid)
