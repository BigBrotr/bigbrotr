"""Base Event Repository for Brotr architecture.

This module defines the abstract base class for event operations that both
bigbrotr (full event storage) and lilbrotr (minimal event storage) extend.

Architecture:
    - BaseEventRepository: Abstract interface for event operations
    - Concrete implementations: BigbrotrEventRepository, LilbrotrEventRepository
    - Shared logic: Batch processing, deduplication, validation

The repository pattern enables:
    - Flexible storage strategies (full vs minimal)
    - Testable business logic
    - Centralized query optimization
    - Easy switching between implementations
"""
from abc import ABC, abstractmethod
from typing import List, Optional
from nostr_tools import Event, Relay


class BaseEventRepository(ABC):
    """Abstract base repository for event operations.

    This class defines the interface that all event repositories must implement,
    allowing different storage strategies for bigbrotr (full) vs lilbrotr (minimal).
    """

    def __init__(self, pool):
        """Initialize repository with database pool.

        Args:
            pool: Database connection pool (DatabasePool instance)
        """
        self.pool = pool

    @abstractmethod
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

        Implementation Notes:
            - bigbrotr: Stores id, pubkey, created_at, kind, tags, content, sig
            - lilbrotr: Stores id, pubkey, created_at, kind, sig (NO tags, NO content)
        """
        pass

    @abstractmethod
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

        Implementation Notes:
            - Uses database-side stored procedures for atomicity
            - Batch processing reduces round trips by ~80%
            - Idempotent: ON CONFLICT DO NOTHING
        """
        pass

    @abstractmethod
    async def delete_orphan_events(self) -> None:
        """Delete orphan events from the database.

        Removes events that have no associated relay references. This maintains
        the data integrity constraint that every event must be seen on at least
        one relay.

        Implementation Notes:
            - Same logic for both bigbrotr and lilbrotr
            - Uses DELETE ... NOT IN (SELECT ...) pattern
        """
        pass

    def _validate_event(self, event: Event) -> bool:
        """Validate event has required fields.

        Args:
            event: Event object to validate

        Returns:
            True if event is valid, False otherwise
        """
        if not isinstance(event, Event):
            return False
        if not event.is_valid:
            return False
        return True

    def _validate_relay(self, relay: Relay) -> bool:
        """Validate relay has required fields.

        Args:
            relay: Relay object to validate

        Returns:
            True if relay is valid, False otherwise
        """
        if not isinstance(relay, Relay):
            return False
        if not relay.is_valid:
            return False
        return True

