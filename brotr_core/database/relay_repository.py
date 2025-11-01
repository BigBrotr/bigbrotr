"""Relay repository for relay database operations.

This module provides high-level operations for storing and managing relay
information in the database. Uses stored procedures for efficient batch
operations and automatic deduplication.

Key Responsibilities:
    - Insert single relays with network type tracking
    - Batch insert relays for better performance

Dependencies:
    - database_pool: Generic database connection pool
    - nostr_tools: Relay type
"""
import time
from typing import List, Optional
from nostr_tools import Relay
from brotr_core.database.database_pool import DatabasePool

__all__ = ['RelayRepository']


class RelayRepository:
    """
    Repository for relay database operations.

    Provides high-level methods for relay registration with automatic
    deduplication. All operations use stored procedures defined in init.sql.

    Attributes:
        pool (DatabasePool): Database connection pool for executing queries
    """

    def __init__(self, pool: DatabasePool):
        """Initialize RelayRepository with database pool.

        Args:
            pool: DatabasePool instance for database operations

        Raises:
            TypeError: If pool is not a DatabasePool instance
        """
        if not isinstance(pool, DatabasePool):
            raise TypeError(f"pool must be a DatabasePool, not {type(pool)}")
        self.pool = pool

    async def insert_relay(self, relay: Relay, inserted_at: Optional[int] = None) -> None:
        """Insert a relay into the database.

        Uses the insert_relay() stored procedure which handles relay
        deduplication (ON CONFLICT DO NOTHING).

        Args:
            relay: Relay to insert
            inserted_at: Timestamp when relay was inserted (defaults to now)

        Raises:
            TypeError: If parameters have incorrect types
            ValueError: If inserted_at is negative
        """
        if not isinstance(relay, Relay):
            raise TypeError(f"relay must be a Relay, not {type(relay)}")
        if inserted_at is not None:
            if not isinstance(inserted_at, int):
                raise TypeError(
                    f"inserted_at must be an int, not {type(inserted_at)}")
            if inserted_at < 0:
                raise ValueError(
                    f"inserted_at must be a positive int, not {inserted_at}")
        else:
            inserted_at = int(time.time())

        query = "SELECT insert_relay($1, $2, $3)"
        await self.pool.execute(query, relay.url, relay.network, inserted_at)

    async def insert_relay_batch(
        self, relays: List[Relay], inserted_at: Optional[int] = None
    ) -> None:
        """Insert a batch of relays efficiently.

        Uses executemany for better performance when inserting multiple relays.
        All relays share the same inserted_at timestamp.

        Args:
            relays: List of relays to insert
            inserted_at: Timestamp when relays were inserted (defaults to now)

        Raises:
            TypeError: If parameters have incorrect types
            ValueError: If inserted_at is negative
        """
        if not isinstance(relays, list):
            raise TypeError(f"relays must be a list, not {type(relays)}")
        for relay in relays:
            if not isinstance(relay, Relay):
                raise TypeError(f"relay must be a Relay, not {type(relay)}")
        if inserted_at is not None:
            if not isinstance(inserted_at, int):
                raise TypeError(
                    f"inserted_at must be an int, not {type(inserted_at)}")
            if inserted_at < 0:
                raise ValueError(
                    f"inserted_at must be a positive int, not {inserted_at}")
        else:
            inserted_at = int(time.time())

        if not relays:
            return

        query = "SELECT insert_relay($1, $2, $3)"

        async with self.pool.pool.acquire(timeout=30) as conn:
            async with conn.transaction():
                await conn.executemany(
                    query,
                    [(relay.url, relay.network, inserted_at)
                     for relay in relays],
                )
