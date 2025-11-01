"""Metadata repository for relay metadata database operations.

This module provides high-level operations for storing and managing relay
metadata (NIP-11 and NIP-66) in the database. Uses stored procedures for
efficient batch operations and hash-based deduplication.

Key Responsibilities:
    - Insert single relay metadata with NIP-11 and NIP-66 data
    - Batch insert metadata for better performance
    - Handle JSON serialization for metadata fields

Dependencies:
    - database_pool: Generic database connection pool
    - nostr_tools: RelayMetadata type and sanitize function
"""
import json
from typing import List
from nostr_tools import RelayMetadata, sanitize
from brotr_core.database.database_pool import DatabasePool

__all__ = ['MetadataRepository']


class MetadataRepository:
    """
    Repository for relay metadata database operations.

    Provides high-level methods for storing NIP-11 (relay information) and
    NIP-66 (connection test results) metadata. All operations use stored
    procedures defined in init.sql with hash-based deduplication.

    Attributes:
        pool (DatabasePool): Database connection pool for executing queries
    """

    def __init__(self, pool: DatabasePool):
        """Initialize MetadataRepository with database pool.

        Args:
            pool: DatabasePool instance for database operations

        Raises:
            TypeError: If pool is not a DatabasePool instance
        """
        if not isinstance(pool, DatabasePool):
            raise TypeError(f"pool must be a DatabasePool, not {type(pool)}")
        self.pool = pool

    async def insert_relay_metadata(self, relay_metadata: RelayMetadata) -> None:
        """Insert relay metadata into the database.

        Uses the insert_relay_metadata() stored procedure which handles:
        - NIP-11 deduplication (by SHA-256 hash of metadata)
        - NIP-66 deduplication (by SHA-256 hash of metadata)
        - Relay registration
        - Time-series metadata snapshot creation

        Args:
            relay_metadata: RelayMetadata to insert containing NIP-11 and NIP-66 data

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

        await self.pool.execute(
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

        Uses executemany for better performance when inserting multiple
        metadata records. Each metadata record is independently deduplicated.

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

        async with self.pool.pool.acquire(timeout=30) as conn:
            async with conn.transaction():
                await conn.executemany(query, args)
