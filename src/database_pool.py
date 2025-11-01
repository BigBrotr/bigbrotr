"""Database connection pool management for Bigbrotr.

This module provides a lightweight wrapper around asyncpg connection pools,
handling connection lifecycle and providing generic database operations.

Key Responsibilities:
    - Connection pool creation and management
    - Generic SQL operations (execute, fetch, fetchone)
    - Connection validation and health checks
    - Async context manager support

Dependencies:
    - asyncpg: PostgreSQL async driver with connection pooling
    - db_error_handler: Automatic retry logic for transient errors
"""
import asyncpg
from typing import Optional, List, Any
from db_error_handler import retry_on_db_error

__all__ = ['DatabasePool']


class DatabasePool:
    """
    Async database connection pool manager using asyncpg.

    Provides connection pool lifecycle management and generic database
    operations with automatic retry on transient errors.

    Attributes:
        host (str): Database host
        port (int): Database port
        user (str): Database user
        password (str): Database password
        dbname (str): Database name
        pool (asyncpg.Pool): Connection pool
        min_pool_size (int): Minimum connections in pool
        max_pool_size (int): Maximum connections in pool
        command_timeout (int): Timeout for database commands
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
        """Initialize DatabasePool instance with connection parameters.

        Args:
            host: Database host
            port: Database port
            user: Database user
            password: Database password
            dbname: Database name
            min_pool_size: Minimum connections in pool (default: 5)
            max_pool_size: Maximum connections in pool (default: 20)
            command_timeout: Timeout for database commands in seconds (default: 60)

        Raises:
            TypeError: If parameters have incorrect types
        """
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
        """Create connection pool.

        Creates an asyncpg connection pool with configured parameters.
        Safe to call multiple times - will not recreate if pool already exists.
        """
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
        """Close connection pool.

        Closes all connections in the pool and releases resources.
        Safe to call multiple times - will not error if pool already closed.
        """
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def __aenter__(self):
        """Async context manager entry.

        Usage:
            async with DatabasePool(...) as pool:
                await pool.execute(query)
        """
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    @property
    def is_connected(self) -> bool:
        """Check if connection pool is active.

        Returns:
            True if pool is initialized, False otherwise
        """
        return self.pool is not None

    @property
    def is_valid(self) -> bool:
        """Check if instance is valid (has required attributes).

        Returns:
            True if all required connection parameters are set
        """
        return all([self.host, self.port, self.user, self.password, self.dbname])

    async def execute(self, query: str, *args: Any, timeout: float = 30) -> str:
        """Execute a query without returning results with automatic retry on transient errors.

        Args:
            query: SQL query to execute
            *args: Query parameters
            timeout: Timeout in seconds for acquiring connection from pool (default: 30)

        Returns:
            Status string from database

        Raises:
            TypeError: If query is not a string
            RuntimeError: If connection pool not initialized
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

        Returns:
            List of database records

        Raises:
            TypeError: If query is not a string
            RuntimeError: If connection pool not initialized
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

        Returns:
            Single database record or None if no results

        Raises:
            TypeError: If query is not a string
            RuntimeError: If connection pool not initialized
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
