"""Async database wrapper for Bigbrotr using asyncpg for better performance."""
import asyncpg
import json
import time
from typing import Optional, List, Any
from nostr_tools import Event, Relay, RelayMetadata, sanitize
from db_error_handler import retry_on_db_error


class Bigbrotr:
    """
    Async database wrapper for Bigbrotr using asyncpg connection pool.

    This class provides async database operations with connection pooling
    for better performance in async contexts.

    Attributes:
        host (str): Database host
        port (int): Database port
        user (str): Database user
        password (str): Database password
        dbname (str): Database name
        pool (asyncpg.Pool): Connection pool
        min_pool_size (int): Minimum connections in pool
        max_pool_size (int): Maximum connections in pool
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
        """Initialize Bigbrotr instance with connection parameters."""
        if not isinstance(host, str):
            raise TypeError(f"host must be a str, not {type(host)}")
        if not isinstance(port, int):
            raise TypeError(f"port must be an int, not {type(port)}")
        if not isinstance(user, str):
            raise TypeError(f"user must be a str, not {type(user)}")
        if not isinstance(password, str):
            raise TypeError(f"password must be a str, not {type(password)}")
        if not isinstance(dbname, str):
            raise TypeError(f"dbname must be a str, not {type(dbname)}")

        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.dbname = dbname
        self.min_pool_size = min_pool_size
        self.max_pool_size = max_pool_size
        self.command_timeout = command_timeout
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        """Create connection pool."""
        if self.pool is not None:
            return

        self.pool = await asyncpg.create_pool(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.dbname,
            min_size=self.min_pool_size,
            max_size=self.max_pool_size,
            command_timeout=self.command_timeout,
        )

    async def close(self) -> None:
        """Close connection pool."""
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

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
        return self.pool is not None

    @property
    def is_valid(self) -> bool:
        """Check if instance is valid (has required attributes)."""
        return all([self.host, self.port, self.user, self.password, self.dbname])

    async def execute(self, query: str, *args: Any, timeout: float = 30) -> str:
        """Execute a query without returning results with automatic retry on transient errors.

        Args:
            query: SQL query to execute
            *args: Query parameters
            timeout: Timeout in seconds for acquiring connection from pool (default: 30)
        """
        if not isinstance(query, str):
            raise TypeError(f"query must be a str, not {type(query)}")
        if self.pool is None:
            raise RuntimeError(
                "Connection pool not initialized. Call connect() first.")

        async def _execute_query():
            async with self.pool.acquire(timeout=timeout) as conn:
                return await conn.execute(query, *args)

        return await retry_on_db_error(_execute_query, operation_name="execute_query")

    async def fetch(self, query: str, *args: Any, timeout: float = 30) -> List[asyncpg.Record]:
        """Fetch all results from a query with automatic retry on transient errors.

        Args:
            query: SQL query to execute
            *args: Query parameters
            timeout: Timeout in seconds for acquiring connection from pool (default: 30)
        """
        if not isinstance(query, str):
            raise TypeError(f"query must be a str, not {type(query)}")
        if self.pool is None:
            raise RuntimeError(
                "Connection pool not initialized. Call connect() first.")

        async def _fetch_query():
            async with self.pool.acquire(timeout=timeout) as conn:
                return await conn.fetch(query, *args)

        return await retry_on_db_error(_fetch_query, operation_name="fetch_query")

    async def fetchone(self, query: str, *args: Any, timeout: float = 30) -> Optional[asyncpg.Record]:
        """Fetch one result from a query with automatic retry on transient errors.

        Args:
            query: SQL query to execute
            *args: Query parameters
            timeout: Timeout in seconds for acquiring connection from pool (default: 30)
        """
        if not isinstance(query, str):
            raise TypeError(f"query must be a str, not {type(query)}")
        if self.pool is None:
            raise RuntimeError(
                "Connection pool not initialized. Call connect() first.")

        async def _fetchone_query():
            async with self.pool.acquire(timeout=timeout) as conn:
                return await conn.fetchrow(query, *args)

        return await retry_on_db_error(_fetchone_query, operation_name="fetchone_query")

    async def delete_orphan_events(self) -> None:
        """Delete orphan events from the database."""
        query = "SELECT delete_orphan_events()"
        await self.execute(query)

    async def insert_event(
        self, event: Event, relay: Relay, seen_at: Optional[int] = None
    ) -> None:
        """Insert an event into the database.

        Args:
            event: Event to insert
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

        await self.execute(
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
        """Insert a batch of events efficiently.

        Args:
            events: List of events to insert
            relay: Relay where events were seen
            seen_at: Timestamp when events were seen

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

        async with self.pool.acquire(timeout=30) as conn:
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

    async def insert_relay(self, relay: Relay, inserted_at: Optional[int] = None) -> None:
        """Insert a relay into the database.

        Args:
            relay: Relay to insert
            inserted_at: Timestamp when relay was inserted

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
        await self.execute(query, relay.url, relay.network, inserted_at)

    async def insert_relay_batch(
        self, relays: List[Relay], inserted_at: Optional[int] = None
    ) -> None:
        """Insert a batch of relays efficiently.

        Args:
            relays: List of relays to insert
            inserted_at: Timestamp when relays were inserted

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

        async with self.pool.acquire(timeout=30) as conn:
            async with conn.transaction():
                await conn.executemany(
                    query,
                    [(relay.url, relay.network, inserted_at)
                     for relay in relays],
                )

    async def insert_relay_metadata(self, relay_metadata: RelayMetadata) -> None:
        """Insert relay metadata into the database.

        Args:
            relay_metadata: RelayMetadata to insert

        Raises:
            TypeError: If relay_metadata is not a RelayMetadata instance
        """
        if not isinstance(relay_metadata, RelayMetadata):
            raise TypeError(
                f"relay_metadata must be a RelayMetadata, not {type(relay_metadata)}"
            )

        relay_inserted_at = relay_metadata.generated_at
        nip11 = relay_metadata.nip11
        nip66 = relay_metadata.nip66

        # Determine if NIP-11 and NIP-66 objects are present (matches new schema)
        nip66_present = nip66 is not None
        nip11_present = nip11 is not None

        query = """
            SELECT insert_relay_metadata(
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                $13, $14, $15, $16, $17, $18, $19::jsonb, $20, $21,
                $22, $23, $24::jsonb, $25::jsonb
            )
        """

        await self.execute(
            query,
            relay_metadata.relay.url,
            relay_metadata.relay.network,
            relay_inserted_at,
            relay_metadata.generated_at,
            nip66_present,
            nip66.openable if nip66 else None,
            nip66.readable if nip66 else None,
            nip66.writable if nip66 else None,
            nip66.rtt_open if nip66 else None,
            nip66.rtt_read if nip66 else None,
            nip66.rtt_write if nip66 else None,
            nip11_present,
            sanitize(nip11.name) if nip11 else None,
            sanitize(nip11.description) if nip11 else None,
            sanitize(nip11.banner) if nip11 else None,
            sanitize(nip11.icon) if nip11 else None,
            sanitize(nip11.pubkey) if nip11 else None,
            sanitize(nip11.contact) if nip11 else None,
            json.dumps(sanitize(nip11.supported_nips)
                       ) if nip11 and nip11.supported_nips else None,
            sanitize(nip11.software) if nip11 else None,
            sanitize(nip11.version) if nip11 else None,
            sanitize(nip11.privacy_policy) if nip11 else None,
            sanitize(nip11.terms_of_service) if nip11 else None,
            json.dumps(sanitize(nip11.limitation)
                       ) if nip11 and nip11.limitation else None,
            json.dumps(sanitize(nip11.extra_fields)
                       ) if nip11 and nip11.extra_fields else None,
        )

    async def insert_relay_metadata_batch(
        self, relay_metadata_list: List[RelayMetadata]
    ) -> None:
        """Insert a batch of relay metadata efficiently.

        Args:
            relay_metadata_list: List of RelayMetadata to insert

        Raises:
            TypeError: If relay_metadata_list is not a list of RelayMetadata
        """
        if not isinstance(relay_metadata_list, list):
            raise TypeError(
                f"relay_metadata_list must be a list, not {type(relay_metadata_list)}"
            )
        for relay_metadata in relay_metadata_list:
            if not isinstance(relay_metadata, RelayMetadata):
                raise TypeError(
                    f"relay_metadata must be a RelayMetadata, not {type(relay_metadata)}"
                )

        if not relay_metadata_list:
            return

        query = """
            SELECT insert_relay_metadata(
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                $13, $14, $15, $16, $17, $18, $19::jsonb, $20, $21,
                $22, $23, $24::jsonb, $25::jsonb
            )
        """

        args = []
        for relay_metadata in relay_metadata_list:
            nip11 = relay_metadata.nip11
            nip66 = relay_metadata.nip66
            # Determine if NIP-11 and NIP-66 objects are present (matches new schema)
            nip66_present = nip66 is not None
            nip11_present = nip11 is not None

            args.append(
                (
                    relay_metadata.relay.url,
                    relay_metadata.relay.network,
                    relay_metadata.generated_at,
                    relay_metadata.generated_at,
                    nip66_present,
                    nip66.openable if nip66 else None,
                    nip66.readable if nip66 else None,
                    nip66.writable if nip66 else None,
                    nip66.rtt_open if nip66 else None,
                    nip66.rtt_read if nip66 else None,
                    nip66.rtt_write if nip66 else None,
                    nip11_present,
                    sanitize(nip11.name) if nip11 else None,
                    sanitize(nip11.description) if nip11 else None,
                    sanitize(nip11.banner) if nip11 else None,
                    sanitize(nip11.icon) if nip11 else None,
                    sanitize(nip11.pubkey) if nip11 else None,
                    sanitize(nip11.contact) if nip11 else None,
                    json.dumps(sanitize(nip11.supported_nips))
                    if nip11 and nip11.supported_nips
                    else None,
                    sanitize(nip11.software) if nip11 else None,
                    sanitize(nip11.version) if nip11 else None,
                    sanitize(nip11.privacy_policy) if nip11 else None,
                    sanitize(nip11.terms_of_service) if nip11 else None,
                    json.dumps(sanitize(nip11.limitation)
                               ) if nip11 and nip11.limitation else None,
                    json.dumps(sanitize(nip11.extra_fields))
                    if nip11 and nip11.extra_fields
                    else None,
                )
            )

        async with self.pool.acquire(timeout=30) as conn:
            async with conn.transaction():
                await conn.executemany(query, args)
