"""
Database Interface
High-level database interface for Brotr using composition pattern.
Uses a ConnectionPool instance internally for better separation of concerns.

Features:
- Stored procedure wrappers for event/relay operations
- Batch operation support
- Hex to bytea conversion for efficient storage
- Type-safe parameter handling
- Dependency injection support for testing
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator

from .pool import ConnectionPool


# ============================================================================
# Pydantic Models for Configuration Validation
# ============================================================================


class BatchConfig(BaseModel):
    """Batch operation configuration."""

    default_batch_size: int = Field(default=100, ge=1, le=10000)
    max_batch_size: int = Field(default=1000, ge=1, le=10000)

    @field_validator("max_batch_size")
    @classmethod
    def validate_max_batch_size(cls, v: int, info) -> int:
        """Ensure max_batch_size >= default_batch_size."""
        default_batch_size = info.data.get("default_batch_size", 100)
        if v < default_batch_size:
            raise ValueError(
                f"max_batch_size ({v}) must be >= default_batch_size ({default_batch_size})"
            )
        return v


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
    - Batch operation support with configurable sizes
    - Hex to bytea conversion for efficient storage
    - Type-safe parameter handling
    - Public pool property for all ConnectionPool operations

    Example usage:
        # Method 1: Default pool with custom Brotr config
        brotr = Brotr(default_batch_size=200)

        # Method 2: Inject custom pool
        pool = ConnectionPool(host="localhost", database="brotr", min_size=10)
        brotr = Brotr(pool=pool, default_batch_size=200)

        # Method 3: From dictionary (unified config, pool created internally)
        config = {
            "pool": {
                "database": {"host": "localhost", "database": "brotr"}
            },
            "batch": {"default_batch_size": 200}
        }
        brotr = Brotr.from_dict(config)

        # Method 4: From YAML (unified config with pool key)
        brotr = Brotr.from_yaml("implementations/brotr/yaml/brotr.yaml")

        # Use it
        async with brotr.pool:
            # Pool operations via brotr.pool
            result = await brotr.pool.fetch("SELECT * FROM events LIMIT 10")

            # Stored procedures via brotr
            await brotr.insert_event(...)
            deleted = await brotr.cleanup_orphans()
    """

    def __init__(
        self,
        # Dependency Injection: provide pool or None for default
        pool: Optional[ConnectionPool] = None,
        # Brotr-specific parameters
        default_batch_size: Optional[int] = None,
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
            default_batch_size: Default size for batch operations (default: 100)
            max_batch_size: Maximum batch size (default: 1000)
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
            brotr = Brotr(default_batch_size=200)

            # Option 2: Inject custom pool
            pool = ConnectionPool(host="localhost", database="brotr", min_size=10)
            brotr = Brotr(pool=pool, default_batch_size=200)

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
        if default_batch_size is not None:
            batch_dict["default_batch_size"] = default_batch_size
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

    def _validate_batch_size(self, batch_size: Optional[int]) -> int:
        """
        Validate and return batch size.

        Args:
            batch_size: Requested batch size (uses default if None)

        Returns:
            Validated batch size

        Raises:
            ValueError: If batch size exceeds maximum
        """
        batch_size = batch_size or self._config.batch.default_batch_size

        if batch_size > self._config.batch.max_batch_size:
            raise ValueError(
                f"Batch size {batch_size} exceeds maximum {self._config.batch.max_batch_size}"
            )

        return batch_size

    async def _call_delete_procedure(self, procedure_name: str) -> int:
        """
        Call a delete/cleanup stored procedure.

        Args:
            procedure_name: Name of the stored procedure to call

        Returns:
            Number of records deleted

        Raises:
            asyncpg.PostgresError: If database operation fails
        """
        query = f"SELECT {procedure_name}()"

        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                query,
                timeout=self._config.timeouts.procedure,
            )
            return result or 0

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
                "batch": {"default_batch_size": 200}
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
            default_batch_size=batch_config.get("default_batch_size"),
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

    async def insert_event(
        self,
        event_id: str,
        pubkey: str,
        created_at: int,
        kind: int,
        tags: List[List[str]],
        content: str,
        sig: str,
        relay_url: str,
        relay_network: str,
        relay_inserted_at: int,
        seen_at: int,
    ) -> None:
        """
        Insert event using stored procedure.

        Args:
            event_id: Event ID (64-char hex)
            pubkey: Public key (64-char hex)
            created_at: Event creation timestamp
            kind: Event kind number
            tags: Event tags as list of lists
            content: Event content
            sig: Event signature (128-char hex)
            relay_url: Relay WebSocket URL
            relay_network: Network type (clearnet/tor)
            relay_inserted_at: Relay insertion timestamp
            seen_at: When event was seen on relay

        Raises:
            asyncpg.PostgresError: If database operation fails
        """
        # Call stored procedure
        proc_name = self._config.procedures.insert_event
        query = f"SELECT {proc_name}($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)"

        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                bytes.fromhex(event_id),
                bytes.fromhex(pubkey),
                created_at,
                kind,
                tags,  # asyncpg handles list -> JSONB conversion
                content,
                bytes.fromhex(sig),
                relay_url,
                relay_network,
                relay_inserted_at,
                seen_at,
                timeout=self._config.timeouts.procedure,
            )

    async def insert_events_batch(
        self, events: List[Dict[str, Any]], batch_size: Optional[int] = None
    ) -> None:
        """
        Insert multiple events in batches.

        Args:
            events: List of event dictionaries with required fields
            batch_size: Optional batch size (uses default_batch_size if None)

        Raises:
            ValueError: If validation fails or batch exceeds max_batch_size
            asyncpg.PostgresError: If database operation fails

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
        """
        if not events:
            return

        # Validate and get batch size
        batch_size = self._validate_batch_size(batch_size)

        # Process in chunks
        for i in range(0, len(events), batch_size):
            batch = events[i : i + batch_size]

            # Insert each event in batch
            for event in batch:
                await self.insert_event(
                    event_id=event["event_id"],
                    pubkey=event["pubkey"],
                    created_at=event["created_at"],
                    kind=event["kind"],
                    tags=event["tags"],
                    content=event["content"],
                    sig=event["sig"],
                    relay_url=event["relay_url"],
                    relay_network=event["relay_network"],
                    relay_inserted_at=event["relay_inserted_at"],
                    seen_at=event["seen_at"],
                )

    async def insert_relay(
        self, url: str, network: str, inserted_at: int
    ) -> None:
        """
        Insert relay using stored procedure.

        Args:
            url: Relay WebSocket URL
            network: Network type (clearnet/tor)
            inserted_at: Insertion timestamp

        Raises:
            asyncpg.PostgresError: If database operation fails
        """
        # Call stored procedure
        proc_name = self._config.procedures.insert_relay
        query = f"SELECT {proc_name}($1, $2, $3)"

        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                url,
                network,
                inserted_at,
                timeout=self._config.timeouts.procedure,
            )

    async def insert_relays_batch(
        self, relays: List[Dict[str, Any]], batch_size: Optional[int] = None
    ) -> None:
        """
        Insert multiple relays in batches.

        Args:
            relays: List of relay dictionaries with required fields
            batch_size: Optional batch size (uses default_batch_size if None)

        Raises:
            ValueError: If validation fails or batch exceeds max_batch_size
            asyncpg.PostgresError: If database operation fails

        Relay dict format:
            {
                "url": "wss://...",
                "network": "clearnet" or "tor",
                "inserted_at": int
            }
        """
        if not relays:
            return

        # Validate and get batch size
        batch_size = self._validate_batch_size(batch_size)

        # Process in chunks
        for i in range(0, len(relays), batch_size):
            batch = relays[i : i + batch_size]

            for relay in batch:
                await self.insert_relay(
                    url=relay["url"],
                    network=relay["network"],
                    inserted_at=relay["inserted_at"],
                )

    async def insert_relay_metadata(
        self,
        relay_url: str,
        relay_network: str,
        relay_inserted_at: int,
        generated_at: int,
        nip66_present: bool = False,
        nip66_openable: Optional[bool] = None,
        nip66_readable: Optional[bool] = None,
        nip66_writable: Optional[bool] = None,
        nip66_rtt_open: Optional[int] = None,
        nip66_rtt_read: Optional[int] = None,
        nip66_rtt_write: Optional[int] = None,
        nip11_present: bool = False,
        nip11_name: Optional[str] = None,
        nip11_description: Optional[str] = None,
        nip11_banner: Optional[str] = None,
        nip11_icon: Optional[str] = None,
        nip11_pubkey: Optional[str] = None,
        nip11_contact: Optional[str] = None,
        nip11_supported_nips: Optional[List[int]] = None,
        nip11_software: Optional[str] = None,
        nip11_version: Optional[str] = None,
        nip11_privacy_policy: Optional[str] = None,
        nip11_terms_of_service: Optional[str] = None,
        nip11_limitation: Optional[Dict[str, Any]] = None,
        nip11_extra_fields: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Insert relay metadata using stored procedure.

        Args:
            relay_url: Relay WebSocket URL
            relay_network: Network type (clearnet/tor)
            relay_inserted_at: Relay insertion timestamp
            generated_at: Metadata generation timestamp
            nip66_present: Whether NIP-66 data is present
            nip66_openable: Relay accepts connections
            nip66_readable: Relay allows subscriptions
            nip66_writable: Relay accepts events
            nip66_rtt_open: Connection RTT (ms)
            nip66_rtt_read: Read RTT (ms)
            nip66_rtt_write: Write RTT (ms)
            nip11_present: Whether NIP-11 data is present
            nip11_name: Relay name
            nip11_description: Relay description
            nip11_banner: Banner URL
            nip11_icon: Icon URL
            nip11_pubkey: Contact pubkey
            nip11_contact: Contact info
            nip11_supported_nips: List of supported NIPs
            nip11_software: Software identifier
            nip11_version: Software version
            nip11_privacy_policy: Privacy policy URL
            nip11_terms_of_service: ToS URL
            nip11_limitation: Limitation object
            nip11_extra_fields: Extra fields

        Raises:
            asyncpg.PostgresError: If database operation fails
        """
        # Call stored procedure
        proc_name = self._config.procedures.insert_relay_metadata
        query = f"""
            SELECT {proc_name}(
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
                $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26
            )
        """

        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                relay_url,
                relay_network,
                relay_inserted_at,
                generated_at,
                nip66_present,
                nip66_openable,
                nip66_readable,
                nip66_writable,
                nip66_rtt_open,
                nip66_rtt_read,
                nip66_rtt_write,
                nip11_present,
                nip11_name,
                nip11_description,
                nip11_banner,
                nip11_icon,
                nip11_pubkey,
                nip11_contact,
                nip11_supported_nips,  # asyncpg handles list -> JSONB
                nip11_software,
                nip11_version,
                nip11_privacy_policy,
                nip11_terms_of_service,
                nip11_limitation,  # asyncpg handles dict -> JSONB
                nip11_extra_fields,  # asyncpg handles dict -> JSONB
                timeout=self._config.timeouts.procedure,
            )

    async def delete_orphan_events(self) -> int:
        """
        Delete orphaned events (events without relay associations).

        Returns:
            Number of deleted events

        Raises:
            asyncpg.PostgresError: If database operation fails
        """
        return await self._call_delete_procedure(
            self._config.procedures.delete_orphan_events
        )

    async def delete_orphan_nip11(self) -> int:
        """
        Delete orphaned NIP-11 records (not referenced by relay metadata).

        Returns:
            Number of deleted NIP-11 records

        Raises:
            asyncpg.PostgresError: If database operation fails
        """
        return await self._call_delete_procedure(
            self._config.procedures.delete_orphan_nip11
        )

    async def delete_orphan_nip66(self) -> int:
        """
        Delete orphaned NIP-66 records (not referenced by relay metadata).

        Returns:
            Number of deleted NIP-66 records

        Raises:
            asyncpg.PostgresError: If database operation fails
        """
        return await self._call_delete_procedure(
            self._config.procedures.delete_orphan_nip66
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
