"""Event repository for Nostr event database operations.

This module provides high-level operations for storing and managing Nostr events
in the database. Uses stored procedures for efficient batch operations and
automatic deduplication.

Key Responsibilities:
    - Insert single events with relay tracking
    - Batch insert events for better performance
    - Delete orphan events (events without relay associations)

Dependencies:
    - database_pool: Generic database connection pool
    - nostr_tools: Event and Relay types
"""
import json
import time
from typing import List, Optional
from nostr_tools import Event, Relay
from database_pool import DatabasePool

__all__ = ['EventRepository']


class EventRepository:
    """
    Repository for Nostr event database operations.

    Provides high-level methods for event storage with automatic relay tracking
    and deduplication. All operations use stored procedures defined in init.sql.

    Attributes:
        pool (DatabasePool): Database connection pool for executing queries
    """

    def __init__(self, pool: DatabasePool):
        """Initialize EventRepository with database pool.

        Args:
            pool: DatabasePool instance for database operations

        Raises:
            TypeError: If pool is not a DatabasePool instance
        """
        if not isinstance(pool, DatabasePool):
            raise TypeError(f"pool must be a DatabasePool, not {type(pool)}")
        self.pool = pool

    async def delete_orphan_events(self) -> None:
        """Delete orphan events from the database.

        Orphan events are events that have no associated relays in the
        events_relays junction table. This can happen if a relay is removed.
        """
        query = "SELECT delete_orphan_events()"
        await self.pool.execute(query)

    async def insert_event(
        self, event: Event, relay: Relay, seen_at: Optional[int] = None
    ) -> None:
        """Insert an event into the database with relay tracking.

        Uses the insert_event() stored procedure which handles:
        - Event deduplication (by event ID)
        - Relay registration
        - Relay-event association in events_relays table

        Args:
            event: Nostr event to insert
            relay: Relay where event was seen
            seen_at: Timestamp when event was seen (defaults to now)

        Raises:
            TypeError: If parameters have incorrect types
            ValueError: If seen_at is negative
        """
        if not isinstance(event, Event):
            raise TypeError(f"event must be an Event, not {type(event)}")
        if not isinstance(relay, Relay):
            raise TypeError(f"relay must be a Relay, not {type(relay)}")
        if seen_at is not None:
            if not isinstance(seen_at, int):
                raise TypeError(f"seen_at must be an int, not {type(seen_at)}")
            if seen_at < 0:
                raise ValueError(
                    f"seen_at must be a positive int, not {seen_at}")
        else:
            seen_at = int(time.time())

        relay_inserted_at = seen_at
        query = """
            SELECT insert_event(
                $1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10, $11
            )
        """

        await self.pool.execute(
            query,
            event.id,
            event.pubkey,
            event.created_at,
            event.kind,
            json.dumps(event.tags),
            event.content,
            event.sig,
            relay.url,
            relay.network,
            relay_inserted_at,
            seen_at,
        )

    async def insert_event_batch(
        self, events: List[Event], relay: Relay, seen_at: Optional[int] = None
    ) -> None:
        """Insert a batch of events efficiently with relay tracking.

        Uses executemany for better performance when inserting multiple events.
        All events are associated with the same relay and seen_at timestamp.

        Args:
            events: List of Nostr events to insert
            relay: Relay where events were seen
            seen_at: Timestamp when events were seen (defaults to now)

        Raises:
            TypeError: If parameters have incorrect types
            ValueError: If seen_at is negative
        """
        if not isinstance(events, list):
            raise TypeError(f"events must be a list, not {type(events)}")
        for event in events:
            if not isinstance(event, Event):
                raise TypeError(f"event must be an Event, not {type(event)}")
        if not isinstance(relay, Relay):
            raise TypeError(f"relay must be a Relay, not {type(relay)}")
        if seen_at is not None:
            if not isinstance(seen_at, int):
                raise TypeError(f"seen_at must be an int, not {type(seen_at)}")
            if seen_at < 0:
                raise ValueError(
                    f"seen_at must be a positive int, not {seen_at}")
        else:
            seen_at = int(time.time())

        if not events:
            return

        relay_inserted_at = seen_at
        query = """
            SELECT insert_event(
                $1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10, $11
            )
        """

        async with self.pool.pool.acquire(timeout=30) as conn:
            async with conn.transaction():
                await conn.executemany(
                    query,
                    [
                        (
                            event.id,
                            event.pubkey,
                            event.created_at,
                            event.kind,
                            json.dumps(event.tags),
                            event.content,
                            event.sig,
                            relay.url,
                            relay.network,
                            relay_inserted_at,
                            seen_at,
                        )
                        for event in events
                    ],
                )
