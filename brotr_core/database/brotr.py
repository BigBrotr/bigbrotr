"""Unified Brotr database interface supporting multiple implementations.

This module provides a unified interface for database operations that automatically
selects the appropriate implementation (Bigbrotr or Lilbrotr) based on the BROTR_MODE
environment variable.

Architecture:
    - BrotrFactory: Creates the appropriate event repository based on mode
    - Brotr: Unified facade class that composes all repositories
    - Supports both full (Bigbrotr) and minimal (Lilbrotr) event storage

The Brotr class provides both direct repository access and convenience methods
for common operations, maintaining a clean API while allowing fine-grained control.

Dependencies:
    - database_pool: Connection pool management
    - bigbrotr_event_repository: Full event storage
    - lilbrotr_event_repository: Minimal event storage
    - relay_repository: Shared relay operations
    - metadata_repository: Shared metadata operations
    - nostr_tools: Event, Relay, RelayMetadata types
"""
import os
import asyncpg
from typing import Optional, List, Any

from nostr_tools import Event, Relay, RelayMetadata

from brotr_core.database.database_pool import DatabasePool
from brotr_core.database.relay_repository import RelayRepository
from brotr_core.database.metadata_repository import MetadataRepository
from brotr_core.registry import get_implementation, list_implementations, implementation_exists

__all__ = ['Brotr', 'BrotrFactory']


class BrotrFactory:
    """Factory for creating the appropriate event repository using plugin system.
    
    This factory enables runtime selection of storage strategy based on the
    BROTR_MODE environment variable. It uses the BrotrRegistry to automatically
    discover and load any registered implementation.
    
    Supports unlimited implementations through plugin system:
    - bigbrotr: Full event storage with tags and content
    - lilbrotr: Minimal event storage without tags and content
    - mediumbrotr: Custom implementation (example)
    - yourbrotr: Create your own!
    """
    
    @staticmethod
    def create_event_repository(pool: DatabasePool, mode: Optional[str] = None):
        """Create event repository based on mode using plugin registry.
        
        Args:
            pool: Database connection pool
            mode: Brotr mode (e.g., 'bigbrotr', 'lilbrotr', 'yourbrotr')
                  Defaults to BROTR_MODE env var or 'bigbrotr'
            
        Returns:
            Event repository instance (extends BaseEventRepository)
            
        Raises:
            ValueError: If mode is not registered
        """
        if mode is None:
            mode = os.environ.get('BROTR_MODE', 'bigbrotr')
        
        mode = mode.lower()
        
        # Get implementation from registry
        repository_class = get_implementation(mode)
        
        if repository_class is None:
            available = list_implementations()
            raise ValueError(
                f"Unknown BROTR_MODE: '{mode}'. "
                f"Available implementations: {available}. "
                f"To create a new implementation, see docs/HOW_TO_CREATE_BROTR.md"
            )
        
        return repository_class(pool)


class Brotr:
    """
    Unified async database wrapper for Brotr using repository pattern.

    This class provides a facade over specialized repositories, automatically
    selecting the appropriate event storage strategy based on BROTR_MODE.

    Attributes:
        pool (DatabasePool): Connection pool manager
        events (BaseEventRepository): Event operations repository (Bigbrotr or Lilbrotr)
        relays (RelayRepository): Relay operations repository (shared)
        metadata (MetadataRepository): Metadata operations repository (shared)
        mode (str): Current Brotr mode ('bigbrotr' or 'lilbrotr')
    
    Usage:
        # Bigbrotr mode (full storage)
        os.environ['BROTR_MODE'] = 'bigbrotr'
        async with Brotr(host, port, user, password, dbname) as db:
            await db.insert_event(event, relay, seen_at)  # Stores tags + content
        
        # Lilbrotr mode (minimal storage)
        os.environ['BROTR_MODE'] = 'lilbrotr'
        async with Brotr(host, port, user, password, dbname) as db:
            await db.insert_event(event, relay, seen_at)  # Stores only metadata
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
        command_timeout: int = 60,
        mode: Optional[str] = None
    ):
        """Initialize Brotr instance with connection parameters.

        Args:
            host: Database host
            port: Database port
            user: Database user
            password: Database password
            dbname: Database name
            min_pool_size: Minimum connections in pool (default: 5)
            max_pool_size: Maximum connections in pool (default: 20)
            command_timeout: Timeout for database commands in seconds (default: 60)
            mode: Brotr mode ('bigbrotr' or 'lilbrotr'), defaults to BROTR_MODE env var
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

        # Store mode (defaults to bigbrotr if not specified)
        self.mode = mode if mode is not None else os.environ.get('BROTR_MODE', 'bigbrotr')
        
        # Create repositories
        self.events = BrotrFactory.create_event_repository(self.pool, self.mode)
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

    # Event operations (delegated to event repository - Bigbrotr or Lilbrotr)
    async def delete_orphan_events(self) -> None:
        """Delete orphan events from the database."""
        await self.events.delete_orphan_events()

    async def insert_event(
        self, event: Event, relay: Relay, seen_at: Optional[int] = None
    ) -> None:
        """Insert an event into the database.
        
        Implementation depends on mode:
        - Bigbrotr: Stores complete event (id, pubkey, created_at, kind, tags, content, sig)
        - Lilbrotr: Stores minimal event (id, pubkey, created_at, kind, sig)
        """
        await self.events.insert_event(event, relay, seen_at)

    async def insert_event_batch(
        self, events: List[Event], relay: Relay, seen_at: Optional[int] = None
    ) -> None:
        """Insert a batch of events efficiently.
        
        Implementation depends on mode:
        - Bigbrotr: Stores complete events with tags and content
        - Lilbrotr: Stores minimal events without tags and content
        """
        await self.events.insert_event_batch(events, relay, seen_at)

    # Relay operations (delegated to relay repository - shared)
    async def insert_relay(self, relay: Relay, inserted_at: Optional[int] = None) -> None:
        """Insert a relay into the database."""
        await self.relays.insert_relay(relay, inserted_at)

    async def insert_relay_batch(
        self, relays_list: List[Relay], inserted_at: Optional[int] = None
    ) -> None:
        """Insert a batch of relays efficiently."""
        await self.relays.insert_relay_batch(relays_list, inserted_at)

    # Metadata operations (delegated to metadata repository - shared)
    async def insert_relay_metadata(self, relay_metadata: RelayMetadata) -> None:
        """Insert relay metadata into the database."""
        await self.metadata.insert_relay_metadata(relay_metadata)

    async def insert_relay_metadata_batch(
        self, relay_metadata_list: List[RelayMetadata]
    ) -> None:
        """Insert a batch of relay metadata efficiently."""
        await self.metadata.insert_relay_metadata_batch(relay_metadata_list)

