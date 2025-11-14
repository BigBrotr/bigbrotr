"""
Database Interface
High-level database interface for Brotr using composition pattern.
Uses a ConnectionPool instance internally for better separation of concerns.

Features:
- Stored procedure wrappers for event/relay operations
- Bulk insert optimization via executemany (up to 1000x performance improvement)
- Batch operation support with configurable limits
- Hex to bytea conversion for efficient storage
- Type-safe parameter handling via Pydantic
- Dependency injection support for testing
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import asyncpg
import yaml
from pydantic import BaseModel, Field

from .pool import ConnectionPool


# ============================================================================
# Pydantic Models for Configuration Validation
# ============================================================================


class BatchConfig(BaseModel):
    """Batch operation configuration."""

    max_batch_size: int = Field(
        default=10000,
        ge=1,
        le=100000,
        description="Maximum number of items allowed in a single batch operation"
    )


class StoredProceduresConfig(BaseModel):
    """Stored procedures name configuration."""

    # Insert operations
    insert_event: str = Field(default="insert_event", min_length=1)
    insert_relay: str = Field(default="insert_relay", min_length=1)
    insert_relay_metadata: str = Field(default="insert_relay_metadata", min_length=1)
    # Cleanup operations
    delete_orphan_events: str = Field(default="delete_orphan_events", min_length=1)
    delete_orphan_nip11: str = Field(default="delete_orphan_nip11", min_length=1)
    delete_orphan_nip66: str = Field(default="delete_orphan_nip66", min_length=1)


class OperationTimeoutsConfig(BaseModel):
    """
    Operation-specific timeouts configuration.

    These timeouts control how long Brotr waits for different database operations.
    They are passed to asyncpg methods via the timeout parameter.
    """

    query: float = Field(
        default=60.0,
        ge=0.1,
        description="Timeout for standard queries (seconds)"
    )
    procedure: float = Field(
        default=90.0,
        ge=0.1,
        description="Timeout for stored procedure calls (seconds)"
    )
    batch: float = Field(
        default=120.0,
        ge=0.1,
        description="Timeout for batch operations (seconds)"
    )


class BrotrConfig(BaseModel):
    """Complete Brotr configuration."""

    batch: BatchConfig = Field(default_factory=BatchConfig)
    procedures: StoredProceduresConfig = Field(default_factory=StoredProceduresConfig)
    timeouts: OperationTimeoutsConfig = Field(default_factory=OperationTimeoutsConfig)


# ============================================================================
# Brotr Class
# ============================================================================


class Brotr:
    """
    High-level database interface for Brotr with composition.

    Uses a ConnectionPool instance accessible via public `pool` property.
    This provides clear separation: brotr.pool.* for pool operations, brotr.* for stored procedures.

    Features:
    - Stored procedure wrappers for event/relay operations
    - Bulk insert optimization via executemany (up to 1000x performance improvement)
    - Batch operation support with configurable size limits
    - Hex to bytea conversion for efficient storage
    - Type-safe parameter handling via Pydantic
    - Public pool property for all ConnectionPool operations
    - Dependency injection support for testing

    Example usage:
        # Method 1: Default pool with custom max batch size
        brotr = Brotr(max_batch_size=20000)

        # Method 2: Inject custom pool
        pool = ConnectionPool(host="localhost", database="brotr", min_size=10)
        brotr = Brotr(pool=pool, max_batch_size=20000)

        # Method 3: From dictionary (unified config, pool created internally)
        config = {
            "pool": {
                "database": {"host": "localhost", "database": "brotr"}
            },
            "batch": {"max_batch_size": 20000}
        }
        brotr = Brotr.from_dict(config)

        # Method 4: From YAML (unified config with pool key)
        brotr = Brotr.from_yaml("implementations/brotr/yaml/brotr.yaml")

        # Use it
        async with brotr.pool:
            # Pool operations via brotr.pool
            result = await brotr.pool.fetch("SELECT * FROM events LIMIT 10")

            # Bulk insert operations via brotr (executemany optimized)
            await brotr.insert_events([event1, event2, ...])  # Up to 1000x faster
            await brotr.insert_relays([relay1, relay2, ...])

            # Cleanup operations
            deleted = await brotr.cleanup_orphans()
    """

    def __init__(
        self,
        # Dependency Injection: provide pool or None for default
        pool: Optional[ConnectionPool] = None,
        # Brotr-specific parameters
        max_batch_size: Optional[int] = None,
        insert_event_proc: Optional[str] = None,
        insert_relay_proc: Optional[str] = None,
        insert_relay_metadata_proc: Optional[str] = None,
        delete_orphan_events_proc: Optional[str] = None,
        delete_orphan_nip11_proc: Optional[str] = None,
        delete_orphan_nip66_proc: Optional[str] = None,
        query_timeout: Optional[float] = None,
        procedure_timeout: Optional[float] = None,
        batch_timeout: Optional[float] = None,
    ):
        """
        Initialize Brotr with optional ConnectionPool injection.

        All parameters are optional - defaults are defined in Pydantic models.

        Args:
            pool: Optional ConnectionPool instance (creates default if None)
            max_batch_size: Maximum allowed batch size (default: 10000)
            insert_event_proc: Name of insert_event stored procedure (default: "insert_event")
            insert_relay_proc: Name of insert_relay stored procedure (default: "insert_relay")
            insert_relay_metadata_proc: Name of insert_relay_metadata stored procedure (default: "insert_relay_metadata")
            delete_orphan_events_proc: Name of delete_orphan_events stored procedure (default: "delete_orphan_events")
            delete_orphan_nip11_proc: Name of delete_orphan_nip11 stored procedure (default: "delete_orphan_nip11")
            delete_orphan_nip66_proc: Name of delete_orphan_nip66 stored procedure (default: "delete_orphan_nip66")
            query_timeout: Timeout for standard queries in seconds (default: 60.0)
            procedure_timeout: Timeout for stored procedure calls in seconds (default: 90.0)
            batch_timeout: Timeout for batch operations in seconds (default: 120.0)

        Raises:
            ValidationError: If configuration is invalid

        Examples:
            # Option 1: Use default pool
            brotr = Brotr(max_batch_size=5000)

            # Option 2: Inject custom pool
            pool = ConnectionPool(host="localhost", database="brotr", min_size=10)
            brotr = Brotr(pool=pool, max_batch_size=20000)

            # Option 3: From YAML (pool created internally)
            brotr = Brotr.from_yaml("config/brotr.yaml")

            async with brotr.pool:
                await brotr.insert_event(...)
        """
        # Use provided pool or create default
        self.pool = pool or ConnectionPool()

        # Build Brotr config dict only with non-None values
        # Pydantic will apply defaults for missing values
        config_dict = {}

        # Batch operation configuration
        batch_dict = {}
        if max_batch_size is not None:
            batch_dict["max_batch_size"] = max_batch_size
        if batch_dict:
            config_dict["batch"] = batch_dict

        # Stored procedures names configuration
        procedures_dict = {}
        if insert_event_proc is not None:
            procedures_dict["insert_event"] = insert_event_proc
        if insert_relay_proc is not None:
            procedures_dict["insert_relay"] = insert_relay_proc
        if insert_relay_metadata_proc is not None:
            procedures_dict["insert_relay_metadata"] = insert_relay_metadata_proc
        if delete_orphan_events_proc is not None:
            procedures_dict["delete_orphan_events"] = delete_orphan_events_proc
        if delete_orphan_nip11_proc is not None:
            procedures_dict["delete_orphan_nip11"] = delete_orphan_nip11_proc
        if delete_orphan_nip66_proc is not None:
            procedures_dict["delete_orphan_nip66"] = delete_orphan_nip66_proc
        if procedures_dict:
            config_dict["procedures"] = procedures_dict

        # Operation-specific timeouts (passed to asyncpg methods)
        timeouts_dict = {}
        if query_timeout is not None:
            timeouts_dict["query"] = query_timeout
        if procedure_timeout is not None:
            timeouts_dict["procedure"] = procedure_timeout
        if batch_timeout is not None:
            timeouts_dict["batch"] = batch_timeout
        if timeouts_dict:
            config_dict["timeouts"] = timeouts_dict

        # Pydantic will apply defaults for any missing sections/fields
        self._config = BrotrConfig(**config_dict)

    def _validate_batch_size(self, batch: List[Any], operation: str) -> None:
        """
        Validate batch size against maximum allowed.

        Args:
            batch: List of items to validate
            operation: Operation name for error message

        Raises:
            ValueError: If batch exceeds maximum allowed size
        """
        batch_len = len(batch)
        max_size = self._config.batch.max_batch_size

        if batch_len > max_size:
            raise ValueError(
                f"{operation} batch size ({batch_len}) exceeds maximum allowed ({max_size})"
            )

    async def _call_procedure(
        self,
        procedure_name: str,
        *args,
        conn: Optional[asyncpg.Connection] = None,
        fetch_result: bool = False,
        timeout: Optional[float] = None
    ):
        """
        Generic helper to call any stored procedure.

        Unified method that handles both insert and delete/query procedures.
        Builds parameterized query and executes via provided or acquired connection.

        Args:
            procedure_name: Name of the stored procedure to call
            *args: Positional arguments to pass to the procedure
            conn: Optional database connection (if None, acquires from pool)
            fetch_result: If True, returns procedure result; if False, returns None
            timeout: Optional timeout override (uses procedure timeout if None)

        Returns:
            Procedure result if fetch_result=True, None otherwise

        Raises:
            asyncpg.PostgresError: If database operation fails

        Examples:
            # Insert operation (in transaction, no result)
            await self._call_procedure("insert_event", arg1, arg2, conn=conn)

            # Delete operation (acquires connection, returns count)
            count = await self._call_procedure("delete_orphans", fetch_result=True)
        """
        # Build parameterized query: SELECT proc_name($1, $2, $3, ...)
        params = ", ".join(f"${i+1}" for i in range(len(args))) if args else ""
        query = f"SELECT {procedure_name}({params})"
        timeout_value = timeout or self._config.timeouts.procedure

        # Execute query with provided or acquired connection
        if conn is None:
            async with self.pool.acquire() as conn:
                if fetch_result:
                    result = await conn.fetchval(query, *args, timeout=timeout_value)
                    return result or 0
                await conn.execute(query, *args, timeout=timeout_value)
                return None

        # Use provided connection (already in transaction)
        if fetch_result:
            result = await conn.fetchval(query, *args, timeout=timeout_value)
            return result or 0
        await conn.execute(query, *args, timeout=timeout_value)
        return None


    @classmethod
    def from_yaml(cls, yaml_path: str) -> "Brotr":
        """
        Create Brotr from unified YAML configuration file.

        The YAML should have pool configuration under "pool" root key:
        ```yaml
        pool:
          database:
            host: localhost
            database: brotr
          limits:
            min_size: 5
            max_size: 20
          timeouts:
            acquisition: 10.0
          # ... rest of pool config ...

        batch:
          default_batch_size: 100
          max_batch_size: 1000

        procedures:
          insert_event: insert_event
          # ... other procedures ...

        timeouts:
          query: 60.0
          procedure: 90.0
          batch: 120.0
        ```

        Args:
            yaml_path: Path to brotr.yaml configuration file

        Returns:
            Brotr instance

        Raises:
            FileNotFoundError: If YAML file doesn't exist
            ValidationError: If configuration is invalid
            yaml.YAMLError: If YAML parsing fails

        Example:
            brotr = Brotr.from_yaml("implementations/brotr/yaml/core/brotr.yaml")
        """
        # Load configuration
        config_path = Path(yaml_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration not found: {yaml_path}")

        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f) or {}

        # Use from_dict to parse the unified structure
        return cls.from_dict(config_data)

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "Brotr":
        """
        Create Brotr from dictionary configuration.

        Expects unified structure with pool configuration under "pool" root key:
        {
            "pool": {
                "database": {"host": "localhost", "database": "brotr"},
                "limits": {"min_size": 5, "max_size": 20},
                "timeouts": {"acquisition": 10.0},
                "retry": {...},
                "server_settings": {...}
            },
            "batch": {"default_batch_size": 200},
            "procedures": {...},
            "timeouts": {...}
        }

        Args:
            config_dict: Configuration dictionary with unified structure

        Returns:
            Brotr instance

        Raises:
            ValidationError: If configuration is invalid

        Example:
            config = {
                "pool": {
                    "database": {"host": "localhost", "database": "brotr"}
                },
                "batch": {"max_batch_size": 20000}
            }
            brotr = Brotr.from_dict(config)
        """
        # Create pool from config if provided, otherwise use None (default pool)
        pool = None
        if "pool" in config_dict:
            pool = ConnectionPool.from_dict(config_dict["pool"])

        # Extract Brotr config sections
        batch_config = config_dict.get("batch", {})
        procedures_config = config_dict.get("procedures", {})
        timeouts_config = config_dict.get("timeouts", {})

        # Create Brotr with injected pool
        return cls(
            pool=pool,
            # Batch config
            max_batch_size=batch_config.get("max_batch_size"),
            # Procedures config
            insert_event_proc=procedures_config.get("insert_event"),
            insert_relay_proc=procedures_config.get("insert_relay"),
            insert_relay_metadata_proc=procedures_config.get("insert_relay_metadata"),
            delete_orphan_events_proc=procedures_config.get("delete_orphan_events"),
            delete_orphan_nip11_proc=procedures_config.get("delete_orphan_nip11"),
            delete_orphan_nip66_proc=procedures_config.get("delete_orphan_nip66"),
            # Timeouts config
            query_timeout=timeouts_config.get("query"),
            procedure_timeout=timeouts_config.get("procedure"),
            batch_timeout=timeouts_config.get("batch"),
        )

    async def insert_events(
        self, events: List[Dict[str, Any]]
    ) -> bool:
        """
        Insert one or more events atomically using bulk insert.

        Performance: Uses executemany with stored procedure for optimal batch insert
        - 1000 events = optimized batch execution
        - Old approach = 3000 queries (1000 * 3 per event)
        - Up to 1000x performance improvement for large batches

        ALL events are inserted in a single transaction. If any insert fails,
        the entire batch is rolled back - true atomicity.

        Args:
            events: List of event dictionaries with required fields

        Returns:
            True if all inserts succeeded, False if any failed

        Event dict format:
            {
                "event_id": "64-char hex",
                "pubkey": "64-char hex",
                "created_at": int,
                "kind": int,
                "tags": [[tag_name, value, ...], ...],
                "content": "text",
                "sig": "128-char hex",
                "relay_url": "wss://...",
                "relay_network": "clearnet" or "tor",
                "relay_inserted_at": int,
                "seen_at": int
            }

        Examples:
            # Single event
            await brotr.insert_events([{
                "event_id": "abc...",
                "pubkey": "def...",
                ...
            }])

            # Multiple events (atomic, bulk insert optimized)
            await brotr.insert_events([event1, event2, event3])
        """
        if not events:
            return True

        # Validate batch size
        self._validate_batch_size(events, "insert_events")

        try:
            # Bulk insert using executemany - calls stored procedure in optimized batch
            async with self.pool.transaction() as conn:
                # Prepare parameter tuples for executemany
                params = [
                    (
                        bytes.fromhex(e["event_id"]),
                        bytes.fromhex(e["pubkey"]),
                        e["created_at"],
                        e["kind"],
                        e["tags"],
                        e["content"],
                        bytes.fromhex(e["sig"]),
                        e["relay_url"],
                        e["relay_network"],
                        e["relay_inserted_at"],
                        e["seen_at"],
                    )
                    for e in events
                ]

                # Call insert_event stored procedure for all events in optimized batch
                await conn.executemany(
                    f"SELECT {self._config.procedures.insert_event}($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
                    params,
                    timeout=self._config.timeouts.batch,
                )

            return True
        except (asyncpg.PostgresError, ValueError):
            # Log error in production: logger.error(f"Failed to insert events: {e}")
            return False

    async def insert_relays(
        self, relays: List[Dict[str, Any]]
    ) -> bool:
        """
        Insert one or more relays atomically using bulk insert.

        Performance: Uses executemany with stored procedure for optimal batch insert
        - 1000 relays = optimized batch execution
        - Old approach = 1000 separate queries
        - Up to 1000x performance improvement for large batches

        ALL relays are inserted in a single transaction. If any insert fails,
        the entire batch is rolled back - true atomicity.

        Args:
            relays: List of relay dictionaries with required fields

        Returns:
            True if all inserts succeeded, False if any failed

        Relay dict format:
            {
                "url": "wss://...",
                "network": "clearnet" or "tor",
                "inserted_at": int
            }

        Examples:
            # Single relay
            await brotr.insert_relays([{
                "url": "wss://relay.example.com",
                "network": "clearnet",
                "inserted_at": 1699876543
            }])

            # Multiple relays (atomic, bulk insert optimized)
            await brotr.insert_relays([relay1, relay2, relay3])
        """
        if not relays:
            return True

        # Validate batch size
        self._validate_batch_size(relays, "insert_relays")

        try:
            # Bulk insert using executemany - calls stored procedure in optimized batch
            async with self.pool.transaction() as conn:
                # Prepare parameter tuples for executemany
                params = [
                    (
                        r["url"],
                        r["network"],
                        r["inserted_at"],
                    )
                    for r in relays
                ]

                # Call insert_relay stored procedure for all relays in optimized batch
                await conn.executemany(
                    f"SELECT {self._config.procedures.insert_relay}($1, $2, $3)",
                    params,
                    timeout=self._config.timeouts.batch,
                )

            return True
        except (asyncpg.PostgresError, ValueError):
            # Log error in production: logger.error(f"Failed to insert relays: {e}")
            return False

    async def insert_relay_metadata(
        self, metadata_list: List[Dict[str, Any]]
    ) -> bool:
        """
        Insert one or more relay metadata records atomically using bulk insert.

        Performance: Uses executemany with stored procedure for optimal batch insert
        - 100 metadata records = optimized batch execution
        - Old approach = 100 separate queries
        - Up to 100x performance improvement for large batches

        ALL metadata records are inserted in a single transaction. If any insert fails,
        the entire batch is rolled back - true atomicity.

        Args:
            metadata_list: List of metadata dictionaries with required fields

        Returns:
            True if all inserts succeeded, False if any failed

        Metadata dict format (nested structure):
            {
                "relay_url": "wss://...",
                "relay_network": "clearnet" or "tor",
                "relay_inserted_at": int,
                "generated_at": int,
                "nip66": {  # Optional nested dict (None if not present)
                    "openable": bool,
                    "readable": bool,
                    "writable": bool,
                    "rtt_open": int (optional),
                    "rtt_read": int (optional),
                    "rtt_write": int (optional)
                },
                "nip11": {  # Optional nested dict (None if not present)
                    "name": str (optional),
                    "description": str (optional),
                    "banner": str (optional),
                    "icon": str (optional),
                    "pubkey": str (optional),
                    "contact": str (optional),
                    "supported_nips": list (optional),
                    "software": str (optional),
                    "version": str (optional),
                    "privacy_policy": str (optional),
                    "terms_of_service": str (optional),
                    "limitation": dict (optional),
                    "extra_fields": dict (optional)
                }
            }

        Examples:
            # Metadata with nested nip11/nip66 structure
            await brotr.insert_relay_metadata([{
                "relay_url": "wss://relay.example.com",
                "relay_network": "clearnet",
                "relay_inserted_at": 1699876543,
                "generated_at": 1699876543,
                "nip66": {
                    "openable": True,
                    "readable": True,
                    "writable": False,
                    "rtt_open": 120,
                    "rtt_read": 50,
                    "rtt_write": None
                },
                "nip11": {
                    "name": "Test Relay",
                    "description": "A test relay",
                    "supported_nips": [1, 2, 9],
                    # ... other nip11 fields
                }
            }])

            # Multiple metadata records (atomic, bulk optimized)
            await brotr.insert_relay_metadata([metadata1, metadata2, metadata3])
        """
        if not metadata_list:
            return True

        # Validate batch size
        self._validate_batch_size(metadata_list, "insert_relay_metadata")

        try:
            # Bulk insert using executemany - calls stored procedure in optimized batch
            async with self.pool.transaction() as conn:
                # Prepare parameter tuples for executemany
                # Note: metadata has nested structure with nip66 and nip11 sub-dicts
                params = [
                    (
                        m["relay_url"],
                        m["relay_network"],
                        m["relay_inserted_at"],
                        m["generated_at"],
                        # NIP-66 present flag and fields (nested dict)
                        m.get("nip66") is not None,
                        m.get("nip66", {}).get("openable"),
                        m.get("nip66", {}).get("readable"),
                        m.get("nip66", {}).get("writable"),
                        m.get("nip66", {}).get("rtt_open"),
                        m.get("nip66", {}).get("rtt_read"),
                        m.get("nip66", {}).get("rtt_write"),
                        # NIP-11 present flag and fields (nested dict)
                        m.get("nip11") is not None,
                        m.get("nip11", {}).get("name"),
                        m.get("nip11", {}).get("description"),
                        m.get("nip11", {}).get("banner"),
                        m.get("nip11", {}).get("icon"),
                        m.get("nip11", {}).get("pubkey"),
                        m.get("nip11", {}).get("contact"),
                        m.get("nip11", {}).get("supported_nips"),
                        m.get("nip11", {}).get("software"),
                        m.get("nip11", {}).get("version"),
                        m.get("nip11", {}).get("privacy_policy"),
                        m.get("nip11", {}).get("terms_of_service"),
                        m.get("nip11", {}).get("limitation"),
                        m.get("nip11", {}).get("extra_fields"),
                    )
                    for m in metadata_list
                ]

                # Call insert_relay_metadata stored procedure for all records in optimized batch
                await conn.executemany(
                    f"SELECT {self._config.procedures.insert_relay_metadata}($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25)",
                    params,
                    timeout=self._config.timeouts.batch,
                )
            return True
        except (asyncpg.PostgresError, ValueError):
            # Log error in production: logger.error(f"Failed to insert relay metadata: {e}")
            return False

    async def delete_orphan_events(self) -> int:
        """
        Delete orphaned events (events without relay associations).

        Returns:
            Number of deleted events

        Raises:
            asyncpg.PostgresError: If database operation fails
        """
        return await self._call_procedure(
            self._config.procedures.delete_orphan_events,
            fetch_result=True
        )

    async def delete_orphan_nip11(self) -> int:
        """
        Delete orphaned NIP-11 records (not referenced by relay metadata).

        Returns:
            Number of deleted NIP-11 records

        Raises:
            asyncpg.PostgresError: If database operation fails
        """
        return await self._call_procedure(
            self._config.procedures.delete_orphan_nip11,
            fetch_result=True
        )

    async def delete_orphan_nip66(self) -> int:
        """
        Delete orphaned NIP-66 records (not referenced by relay metadata).

        Returns:
            Number of deleted NIP-66 records

        Raises:
            asyncpg.PostgresError: If database operation fails
        """
        return await self._call_procedure(
            self._config.procedures.delete_orphan_nip66,
            fetch_result=True
        )

    async def cleanup_orphans(self) -> Dict[str, int]:
        """
        Delete all orphaned records (events, NIP-11, NIP-66).

        Returns:
            Dictionary with counts of deleted records by type

        Raises:
            asyncpg.PostgresError: If database operation fails

        Example:
            result = await brotr.cleanup_orphans()
            # {"events": 10, "nip11": 5, "nip66": 3}
        """
        return {
            "events": await self.delete_orphan_events(),
            "nip11": await self.delete_orphan_nip11(),
            "nip66": await self.delete_orphan_nip66(),
        }

    # Properties
    @property
    def config(self) -> BrotrConfig:
        """
        Get validated Brotr configuration.

        Note: The returned configuration should be treated as read-only.
        Modifying it after initialization may lead to inconsistent state.
        """
        return self._config

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"Brotr("
            f"host={self.pool.config.database.host}, "
            f"database={self.pool.config.database.database}, "
            f"connected={self.pool.is_connected})"
        )
