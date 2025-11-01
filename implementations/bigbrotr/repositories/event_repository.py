"""Bigbrotr Event Repository - Full event storage implementation.

This repository stores complete Nostr events including:
    - Event metadata: id, pubkey, created_at, kind, sig
    - Event tags: JSONB array for flexible querying
    - Event content: Full text content (plaintext or encrypted)

Storage overhead: ~100% (baseline for comparison with lilbrotr)
Use cases: Full archival, content analysis, tag-based queries
"""
import sys
from pathlib import Path

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import time
import json
import logging
from typing import List, Optional

from nostr_tools import Event, Relay
from brotr_core.database.base_event_repository import BaseEventRepository


class EventRepository(BaseEventRepository):
    """Event repository for bigbrotr (full event storage)."""

    async def insert_event(
        self, 
        event: Event, 
        relay: Relay, 
        seen_at: Optional[int] = None
    ) -> None:
        """Insert a complete event with tags and content.

        Args:
            event: Nostr Event object to insert
            relay: Relay where event was seen
            seen_at: Unix timestamp when event was seen (default: current time)
        """
        if not self._validate_event(event):
            raise ValueError("Invalid event")
        if not self._validate_relay(relay):
            raise ValueError("Invalid relay")

        if seen_at is None:
            seen_at = int(time.time())

        # Call stored procedure: insert_event (bigbrotr version with tags and content)
        query = "SELECT insert_event($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)"
        await self.pool.execute(
            query,
            event.id,
            event.pubkey,
            event.created_at,
            event.kind,
            json.dumps(event.tags),  # Store tags as JSONB
            event.content,           # Store full content
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
        """Insert a batch of complete events efficiently.

        Args:
            events: List of Nostr Event objects to insert
            relay: Relay where events were seen
            seen_at: Unix timestamp when events were seen (default: current time)
        """
        if not self._validate_relay(relay):
            raise ValueError("Invalid relay")

        if seen_at is None:
            seen_at = int(time.time())

        # Batch insert using stored procedure
        query = "SELECT insert_event($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)"
        
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
                    json.dumps(event.tags),  # Store tags as JSONB
                    event.content,           # Store full content
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
        """Delete orphan events from the database."""
        query = "SELECT delete_orphan_events()"
        await self.pool.execute(query)
        logging.info("✅ Orphan events deleted")

