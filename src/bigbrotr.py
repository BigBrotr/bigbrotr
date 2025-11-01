"""Async database wrapper for Bigbrotr using repository pattern.

This module provides a high-level interface for database operations using the
repository pattern for better separation of concerns and testability.

Architecture:
    - DatabasePool: Connection pool management and generic SQL operations
    - EventRepository: Event-specific database operations
    - RelayRepository: Relay-specific database operations
    - MetadataRepository: Metadata-specific database operations
    - Bigbrotr: Facade class composing all repositories

The Bigbrotr class provides both direct repository access and convenience methods
for common operations, maintaining a clean API while allowing fine-grained control.

Dependencies:
    - database_pool: Connection pool management
    - event_repository: Event operations
    - relay_repository: Relay operations
    - metadata_repository: Metadata operations
    - nostr_tools: Event, Relay, RelayMetadata types
"""
import asyncpg
from typing import Optional, List, Any
from nostr_tools import Event, Relay, RelayMetadata

from database_pool import DatabasePool
from event_repository import EventRepository
from relay_repository import RelayRepository
from metadata_repository import MetadataRepository

__all__ = ['Bigbrotr']


class Bigbrotr:
    """
    Async database wrapper for Bigbrotr using repository pattern.

    This class provides a facade over specialized repositories, offering both
    direct repository access and convenience methods for common operations.

    Attributes:
        pool (DatabasePool): Connection pool manager
        events (EventRepository): Event operations repository
        relays (RelayRepository): Relay operations repository
        metadata (MetadataRepository): Metadata operations repository
    """

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        dbname: str,
        min_pool_size: int = 5,
        max_pool_size: int = 20,
        command_timeout: int = 60
    ):
        """Initialize Bigbrotr instance with connection parameters.

        Args:
            host: Database host
            port: Database port
            user: Database user
            password: Database password
            dbname: Database name
            min_pool_size: Minimum connections in pool (default: 5)
            max_pool_size: Maximum connections in pool (default: 20)
            command_timeout: Timeout for database commands in seconds (default: 60)
        """
        # Create database pool
        self.pool = DatabasePool(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=dbname,
            min_pool_size=min_pool_size,
            max_pool_size=max_pool_size,
            command_timeout=command_timeout
        )

        # Create repositories
        self.events = EventRepository(self.pool)
        self.relays = RelayRepository(self.pool)
        self.metadata = MetadataRepository(self.pool)

        # Expose connection parameters for compatibility
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.dbname = dbname
        self.min_pool_size = min_pool_size
        self.max_pool_size = max_pool_size
        self.command_timeout = command_timeout

    async def connect(self) -> None:
        """Create connection pool."""
        await self.pool.connect()

    async def close(self) -> None:
        """Close connection pool."""
        await self.pool.close()

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    @property
    def is_connected(self) -> bool:
        """Check if connection pool is active."""
        return self.pool.is_connected

    @property
    def is_valid(self) -> bool:
        """Check if instance is valid (has required attributes)."""
        return self.pool.is_valid

    # Generic database operations (delegated to pool)
    async def execute(self, query: str, *args: Any, timeout: float = 30) -> str:
        """Execute a query without returning results."""
        return await self.pool.execute(query, *args, timeout=timeout)

    async def fetch(self, query: str, *args: Any, timeout: float = 30) -> List[asyncpg.Record]:
        """Fetch all results from a query."""
        return await self.pool.fetch(query, *args, timeout=timeout)

    async def fetchone(self, query: str, *args: Any, timeout: float = 30) -> Optional[asyncpg.Record]:
        """Fetch one result from a query."""
        return await self.pool.fetchone(query, *args, timeout=timeout)

    # Event operations (delegated to event repository)
    async def delete_orphan_events(self) -> None:
        """Delete orphan events from the database."""
        await self.events.delete_orphan_events()

    async def insert_event(
        self, event: Event, relay: Relay, seen_at: Optional[int] = None
    ) -> None:
        """Insert an event into the database."""
        await self.events.insert_event(event, relay, seen_at)

    async def insert_event_batch(
        self, events: List[Event], relay: Relay, seen_at: Optional[int] = None
    ) -> None:
        """Insert a batch of events efficiently."""
        await self.events.insert_event_batch(events, relay, seen_at)

    # Relay operations (delegated to relay repository)
    async def insert_relay(self, relay: Relay, inserted_at: Optional[int] = None) -> None:
        """Insert a relay into the database."""
        await self.relays.insert_relay(relay, inserted_at)

    async def insert_relay_batch(
        self, relays_list: List[Relay], inserted_at: Optional[int] = None
    ) -> None:
        """Insert a batch of relays efficiently."""
        await self.relays.insert_relay_batch(relays_list, inserted_at)

    # Metadata operations (delegated to metadata repository)
    async def insert_relay_metadata(self, relay_metadata: RelayMetadata) -> None:
        """Insert relay metadata into the database."""
        await self.metadata.insert_relay_metadata(relay_metadata)

    async def insert_relay_metadata_batch(
        self, relay_metadata_list: List[RelayMetadata]
    ) -> None:
        """Insert a batch of relay metadata efficiently."""
        await self.metadata.insert_relay_metadata_batch(relay_metadata_list)
