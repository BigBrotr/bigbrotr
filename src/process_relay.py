"""Relay event processing and synchronization logic.

This module contains the core logic for processing and synchronizing events from Nostr relays.
It implements an adaptive binary search algorithm to efficiently fetch events from relays that
may have inconsistent or incomplete event histories.

Modern Architecture:
    - RelayProcessor: Main class orchestrating event synchronization
    - BatchValidator: Validates relay behavior and batch consistency
    - IntervalStack: Manages time interval processing queue
    - EventInserter: Handles database insertion operations
    - RawEventBatch: Container for managing batches of raw Nostr events

The binary search algorithm handles:
    - Relays with gaps in their event history
    - Relays that return inconsistent results
    - Efficient batching to minimize round trips
    - Detection of misbehaving relays

Dependencies:
    - brotr: Database wrapper using repository pattern
    - nostr_tools: Nostr protocol client and data structures
    - asyncio: Async I/O operations
"""
import time
import logging
import asyncio
from typing import Optional, List, Dict, Any, Final
from dataclasses import dataclass, field
from brotr_core.database.brotr import Brotr
from nostr_tools import Event, Client, Filter, Relay
from shared.utils.constants import DEFAULT_MAX_RETRIES, DEFAULT_DB_RETRY_DELAY

__all__ = [
    'RawEventBatch',
    'IntervalStack',
    'BatchValidator',
    'EventInserter',
    'RelayProcessor',
    'get_start_time_async'
]


@dataclass
class RawEventBatch:
    """Batch container for raw Nostr events with automatic min/max tracking."""
    since: int
    until: int
    limit: int
    size: int = 0
    raw_events: List[Dict[str, Any]] = field(default_factory=list)
    min_created_at: Optional[int] = None
    max_created_at: Optional[int] = None

    def append(self, raw_event: Dict[str, Any]) -> bool:
        """Append a raw event to the batch.

        Returns:
            True if event was added successfully, False if batch is full or event is invalid.
        """
        if not isinstance(raw_event, dict):
            return False
        created_at = raw_event.get("created_at")
        if not isinstance(created_at, int) or created_at < 0:
            return False
        if created_at < self.since or created_at > self.until:
            return False
        if self.size >= self.limit:
            return False

        self.raw_events.append(raw_event)
        self.size += 1
        if self.min_created_at is None or created_at < self.min_created_at:
            self.min_created_at = created_at
        if self.max_created_at is None or created_at > self.max_created_at:
            self.max_created_at = created_at
        return True

    def is_full(self) -> bool:
        """Check if batch is full."""
        return self.size >= self.limit

    def is_empty(self) -> bool:
        """Check if batch is empty."""
        return self.size == 0


class IntervalStack:
    """Manages time interval processing queue for binary search algorithm."""

    def __init__(self, initial_until: int):
        """Initialize with initial interval endpoint."""
        self.stack = [initial_until]

    def is_empty(self) -> bool:
        """Check if stack is empty."""
        return len(self.stack) == 0

    def current_until(self) -> int:
        """Get current interval endpoint."""
        return self.stack[0]

    def complete_interval(self) -> int:
        """Mark current interval as complete and return its value."""
        return self.stack.pop(0)

    def add_midpoint(self, since: int, until: int) -> None:
        """Add midpoint interval to process."""
        mid = (until - since) // 2 + since
        self.stack.insert(0, mid)


class BatchValidator:
    """Validates relay behavior and batch consistency."""

    @staticmethod
    def validate_relay_behavior(
        first_batch: RawEventBatch,
        second_batch: RawEventBatch,
        relay_url: str
    ) -> bool:
        """Validate that relay returned consistent results.

        Args:
            first_batch: First batch fetched
            second_batch: Second batch fetched for validation
            relay_url: Relay URL for logging

        Returns:
            True if relay behaved correctly, False otherwise
        """
        if second_batch.is_empty():
            logging.warning(
                f"⚠️ Relay {relay_url} returned empty batch unexpectedly. Stopping processing.")
            return False

        batch_min_matches = first_batch.min_created_at == second_batch.max_created_at
        if not batch_min_matches:
            logging.warning(
                f"⚠️ Relay {relay_url} returned inconsistent timestamps. Stopping processing.")
            return False

        return True

    @staticmethod
    def found_earlier_events(first_batch: RawEventBatch, second_batch: RawEventBatch) -> bool:
        """Check if earlier events were found in second batch.

        Returns:
            True if second batch contains events before first batch minimum
        """
        return second_batch.min_created_at != first_batch.min_created_at


class EventInserter:
    """Handles database insertion operations for events."""

    @staticmethod
    async def insert_batch(
        brotr: Brotr,
        batch: List[Dict[str, Any]],
        relay: Relay,
        seen_at: int
    ) -> int:
        """Insert batch of events into database.

        Args:
            brotr: Database connection
            batch: List of raw event dictionaries
            relay: Relay where events were seen
            seen_at: Timestamp when events were seen

        Returns:
            Number of events successfully inserted
        """
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
            await brotr.insert_event_batch(event_batch, relay, seen_at)
        return len(event_batch)

    @staticmethod
    def combine_batches(first_batch: RawEventBatch, second_batch: RawEventBatch) -> List[Dict[str, Any]]:
        """Combine two batches, excluding duplicates by minimum created_at.

        Args:
            first_batch: First batch (newer events)
            second_batch: Second batch (older events)

        Returns:
            Combined list of raw events with duplicates removed
        """
        batch = [
            raw_event for raw_event in first_batch.raw_events
            if raw_event.get("created_at") != first_batch.min_created_at
        ]
        batch.extend(second_batch.raw_events)
        return batch


class RelayProcessor:
    """Main processor for relay event synchronization using adaptive binary search."""

    def __init__(self, brotr: Brotr, client: Client, filter: Filter):
        """Initialize relay processor.

        Args:
            brotr: Database connection
            client: Nostr client connected to relay
            filter: Event filter with since, until, and limit

        Raises:
            ValueError: If arguments are invalid
        """
        self._validate_arguments(brotr, client, filter)
        self.brotr = brotr
        self.client = client
        self.filter = filter
        self.validator = BatchValidator()
        self.inserter = EventInserter()

    @staticmethod
    def _validate_arguments(brotr: Brotr, client: Client, filter: Filter) -> None:
        """Validate processor arguments."""
        for argument, argument_type in zip([brotr, client, filter], [Brotr, Client, Filter]):
            if not isinstance(argument, argument_type):
                raise ValueError(
                    f"{argument} must be an instance of {argument_type}")
            if not argument.is_valid:
                raise ValueError(f"{argument} must be valid")
        if filter.since is None or filter.until is None:
            raise ValueError("filter must have since and until")
        if filter.limit is None:
            raise ValueError("filter must have limit")

    async def fetch_batch(self, filter: Filter) -> RawEventBatch:
        """Fetch a batch of events from relay.

        Args:
            filter: Event filter with time range and limit

        Returns:
            RawEventBatch containing fetched events
        """
        batch = RawEventBatch(filter.since, filter.until, filter.limit)
        subscription_id = self.client.subscribe(filter)
        async for message in self.client.listen_events(subscription_id):
            if batch.is_full():
                break
            batch.append(message[2])
        self.client.unsubscribe(subscription_id)
        return batch

    async def process_empty_interval(self, stack: IntervalStack) -> None:
        """Handle interval with no events found."""
        stack.complete_interval()
        self.filter.since = self.filter.until + 1

    async def process_single_timestamp_interval(
        self,
        first_batch: RawEventBatch,
        stack: IntervalStack
    ) -> None:
        """Handle interval with events at single timestamp."""
        await self.inserter.insert_batch(
            self.brotr,
            first_batch.raw_events,
            self.client.relay,
            int(time.time())
        )
        stack.complete_interval()
        self.filter.since = self.filter.until + 1

    async def process_multiple_timestamp_interval(
        self,
        first_batch: RawEventBatch,
        stack: IntervalStack
    ) -> bool:
        """Handle interval with events across multiple timestamps.

        Returns:
            True if processing should continue, False if relay misbehaved
        """
        # Fetch second batch to validate relay behavior
        self.filter.until = first_batch.min_created_at
        second_batch = await self.fetch_batch(self.filter)

        # Validate relay behavior
        if not self.validator.validate_relay_behavior(
            first_batch, second_batch, self.client.relay.url
        ):
            return False

        # Check if there are earlier events
        if self.validator.found_earlier_events(first_batch, second_batch):
            # Found events before first batch minimum - need to split interval
            stack.add_midpoint(self.filter.since, self.filter.until)
        else:
            # Only events at first_batch.min_created_at found
            # Check for events before that timestamp
            await self._check_for_earlier_events(first_batch, second_batch, stack)

        return True

    async def _check_for_earlier_events(
        self,
        first_batch: RawEventBatch,
        second_batch: RawEventBatch,
        stack: IntervalStack
    ) -> None:
        """Check for events before minimum timestamp."""
        self.filter.until = first_batch.min_created_at - 1
        self.filter.limit = 1
        third_batch = await self.fetch_batch(self.filter)

        if third_batch.is_empty():
            # No earlier events - all events fetched for this interval
            combined_batch = self.inserter.combine_batches(first_batch, second_batch)
            await self.inserter.insert_batch(
                self.brotr,
                combined_batch,
                self.client.relay,
                int(time.time())
            )
            self.filter.since = stack.complete_interval() + 1
        else:
            # Found earlier events - need to split interval
            stack.add_midpoint(self.filter.since, self.filter.until)

    async def process(self) -> None:
        """Process all events from relay using adaptive binary search."""
        async with self.brotr:
            async with self.client:
                stack = IntervalStack(self.filter.until)

                while not stack.is_empty():
                    # Set current interval endpoint
                    self.filter.until = stack.current_until()

                    # Fetch first batch
                    first_batch = await self.fetch_batch(self.filter)

                    if first_batch.is_empty():
                        await self.process_empty_interval(stack)
                    elif self.filter.since == self.filter.until:
                        await self.process_single_timestamp_interval(first_batch, stack)
                    else:
                        should_continue = await self.process_multiple_timestamp_interval(
                            first_batch, stack
                        )
                        if not should_continue:
                            break




# Utility functions
async def get_start_time_async(
    default_start_time: int,
    brotr: Brotr,
    relay: Relay,
    retries: int = DEFAULT_MAX_RETRIES,
    delay: int = DEFAULT_DB_RETRY_DELAY
) -> int:
    """Get the starting timestamp for event synchronization from database.

    Args:
        default_start_time: Default start time if no events found
        brotr: Database connection
        relay: Relay to get start time for
        retries: Number of retry attempts
        delay: Delay between retries in seconds

    Returns:
        Start timestamp for synchronization

    Raises:
        RuntimeError: If all retry attempts fail
    """
    for attempt in range(retries):
        try:
            # Single JOIN query to get the created_at of the most recently seen event
            query = """
                SELECT e.created_at
                FROM events_relays er
                JOIN events e ON er.event_id = e.id
                WHERE er.relay_url = $1
                ORDER BY er.seen_at DESC
                LIMIT 1
            """
            result = await brotr.fetchone(query, relay.url)

            if result and result[0] is not None:
                return result[0] + 1

            return default_start_time

        except Exception as e:
            logging.warning(
                f"⚠️ Attempt {attempt + 1}/{retries} failed while getting start time for {relay.url}: {e}")
            await asyncio.sleep(delay)

    raise RuntimeError(
        f"❌ Failed to get start time for {relay.url} after {retries} attempts.")
