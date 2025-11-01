"""Template Event Repository - Customize for your needs!

Replace this docstring with a description of your storage strategy:
- What fields do you store?
- What's the use case?
- What are the performance characteristics?

Example:
    This implementation stores X, Y, Z fields for use case ABC.
    Storage: ~N bytes per event
    Performance: ~M events/second
"""
import sys
from pathlib import Path

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import time
import logging
from typing import List, Optional

from nostr_tools import Event, Relay
from brotr_core.database.base_event_repository import BaseEventRepository


class EventRepository(BaseEventRepository):
    """Event repository for your custom Brotr implementation.
    
    Customize this class to implement your storage strategy.
    """

    async def insert_event(
        self, 
        event: Event, 
        relay: Relay, 
        seen_at: Optional[int] = None
    ) -> None:
        """Insert a single event into the database.
        
        Args:
            event: Nostr Event object to insert
            relay: Relay where event was seen
            seen_at: Unix timestamp when event was seen (default: current time)
        
        Raises:
            ValueError: If event or relay is invalid
        
        Implementation Notes:
            - Validate inputs using self._validate_event() and self._validate_relay()
            - Call your custom stored procedure from init.sql
            - Handle errors gracefully
        """
        # Validate inputs
        if not self._validate_event(event):
            raise ValueError("Invalid event")
        if not self._validate_relay(relay):
            raise ValueError("Invalid relay")

        if seen_at is None:
            seen_at = int(time.time())

        # TODO: Customize this query to match your init.sql stored procedure
        # Example: Call insert_event() with your custom parameters
        query = """
            SELECT insert_event(
                $1, $2, $3, $4,
                -- ADD YOUR CUSTOM PARAMETERS HERE
                -- $5,  -- e.g., tags
                -- $6,  -- e.g., content
                $5, $6, $7, $8, $9
            )
        """
        
        await self.pool.execute(
            query,
            event.id,
            event.pubkey,
            event.created_at,
            event.kind,
            # ADD YOUR CUSTOM FIELDS HERE
            # json.dumps(event.tags),  # Example: if storing tags
            # event.content,           # Example: if storing content
            event.sig,
            relay.url,
            relay.network,
            relay.inserted_at,
            seen_at
        )

    async def insert_event_batch(
        self, 
        events: List[Event], 
        relay: Relay, 
        seen_at: Optional[int] = None
    ) -> None:
        """Insert a batch of events efficiently.
        
        Args:
            events: List of Nostr Event objects to insert
            relay: Relay where events were seen
            seen_at: Unix timestamp when events were seen (default: current time)
        
        Raises:
            ValueError: If relay is invalid
        
        Implementation Notes:
            - Process events in batch for better performance
            - Skip invalid events with warnings
            - Use same query as insert_event() but in a loop
        """
        if not self._validate_relay(relay):
            raise ValueError("Invalid relay")

        if seen_at is None:
            seen_at = int(time.time())

        # TODO: Customize this query to match your init.sql stored procedure
        query = """
            SELECT insert_event(
                $1, $2, $3, $4,
                -- ADD YOUR CUSTOM PARAMETERS HERE
                $5, $6, $7, $8, $9
            )
        """
        
        for event in events:
            if not self._validate_event(event):
                logging.warning(f"⚠️ Skipping invalid event: {event}")
                continue

            try:
                await self.pool.execute(
                    query,
                    event.id,
                    event.pubkey,
                    event.created_at,
                    event.kind,
                    # ADD YOUR CUSTOM FIELDS HERE
                    event.sig,
                    relay.url,
                    relay.network,
                    relay.inserted_at,
                    seen_at
                )
            except Exception as e:
                logging.warning(f"⚠️ Failed to insert event {event.id}: {e}")
                continue

    async def delete_orphan_events(self) -> None:
        """Delete orphan events from the database.
        
        Orphan events are events without relay associations.
        This is standard across all implementations.
        """
        query = "SELECT delete_orphan_events()"
        await self.pool.execute(query)
        logging.info("✅ Orphan events deleted")


# NOTES FOR DEVELOPERS:
# 
# 1. Class MUST be named "EventRepository" (exact name!)
# 2. Class MUST extend BaseEventRepository
# 3. You MUST implement these three methods:
#    - insert_event()
#    - insert_event_batch()
#    - delete_orphan_events()
#
# 4. Use self.pool.execute() for database operations
# 5. Use self._validate_event() and self._validate_relay() from base class
# 6. Customize the SQL queries to match your init.sql schema
#
# 7. Testing:
#    export BROTR_MODE=your_implementation_name
#    python3 -c "from brotr_core.registry import list_implementations; print(list_implementations())"
#
# 8. See docs/HOW_TO_CREATE_BROTR.md for detailed instructions

