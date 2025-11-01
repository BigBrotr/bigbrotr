"""Relay loading utilities for fetching relays from database or files.

This module provides functions to load relay lists from various sources:
- Database queries (with filtering by metadata freshness and readability)
- Files (seed_relays.txt, priority_relays.txt)

Key Functions:
    - fetch_relays_from_database: Query database for relays with recent metadata
    - fetch_relays_from_database_paginated: Memory-efficient paginated version
    - fetch_relays_from_file: Load relays from text file
    - fetch_relays_needing_metadata: Find relays that need metadata updates
    - fetch_relays_needing_metadata_paginated: Memory-efficient paginated version

Features:
    - Metadata freshness filtering: Only fetch relays updated within threshold
    - Readable relay filtering: Only fetch relays marked as readable
    - Network shuffling: Randomize relay order for load distribution
    - Pagination support: Async generators for memory-efficient processing
    - Legacy config support: Backward compatible with old config key names

Dependencies:
    - bigbrotr: Database wrapper for async operations
    - nostr_tools: Relay URL parsing and validation
"""
import logging
import random
import time
from typing import List, Dict, Any, AsyncGenerator

from bigbrotr import Bigbrotr
from nostr_tools import Relay

__all__ = [
    'fetch_relays_from_database',
    'fetch_relays_from_database_paginated',
    'fetch_relays_from_file',
    'fetch_all_relays_from_database',
    'fetch_relays_needing_metadata',
    'fetch_relays_needing_metadata_paginated'
]


def _get_db_config(config: Dict[str, Any]) -> tuple:
    """Extract database configuration with fallback for legacy keys.

    Args:
        config: Configuration dictionary

    Returns:
        Tuple of (host, port, user, password, dbname)
    """
    host = config.get("database_host") or config.get("dbhost")
    port = config.get("database_port") or config.get("dbport")
    user = config.get("database_user") or config.get("dbuser")
    password = config.get("database_password") or config.get("dbpass")
    dbname = config.get("database_name") or config.get("dbname")
    return host, port, user, password, dbname


async def fetch_relays_from_database(
    config: Dict[str, Any],
    threshold_hours: int = 12,
    readable_only: bool = True,
    shuffle: bool = True
) -> List[Relay]:
    """Fetch relays from database with optional filtering.

    Args:
        config: Configuration dictionary with database connection info
        threshold_hours: Only fetch relays with metadata newer than this many hours
        readable_only: If True, only fetch relays marked as readable
        shuffle: If True, randomly shuffle the relay list (default: True)

    Returns:
        List of Relay objects, optionally shuffled
    """
    logging.info("📦 Fetching relay metadata from database...")

    host, port, user, password, dbname = _get_db_config(config)

    # Use window function for better performance (O(N) instead of O(N²))
    # Avoids correlated subquery that runs for each row
    if readable_only:
        query = """
            WITH ranked_metadata AS (
                SELECT
                    relay_url,
                    generated_at,
                    ROW_NUMBER() OVER (PARTITION BY relay_url ORDER BY generated_at DESC) as rn
                FROM relay_metadata rm
                JOIN nip66 n ON rm.nip66_id = n.id
                WHERE rm.generated_at > $1 AND n.readable = TRUE
            )
            SELECT relay_url
            FROM ranked_metadata
            WHERE rn = 1
        """
    else:
        query = """
            WITH ranked_metadata AS (
                SELECT
                    relay_url,
                    generated_at,
                    ROW_NUMBER() OVER (PARTITION BY relay_url ORDER BY generated_at DESC) as rn
                FROM relay_metadata
                WHERE generated_at > $1
            )
            SELECT relay_url
            FROM ranked_metadata
            WHERE rn = 1
        """

    threshold = int(time.time()) - 60 * 60 * threshold_hours

    async with Bigbrotr(host, port, user, password, dbname) as bigbrotr:
        rows = await bigbrotr.fetch(query, threshold)

    relays: List[Relay] = []
    for row in rows:
        relay_url = row[0].strip()
        try:
            relay = Relay(relay_url)
            relays.append(relay)
        except Exception as e:
            logging.warning(f"⚠️ Invalid relay: {relay_url}. Error: {e}")
            continue

    logging.info(f"📦 {len(relays)} relays fetched from database.")
    if shuffle:
        random.shuffle(relays)
    return relays


async def fetch_relays_from_database_paginated(
    config: Dict[str, Any],
    threshold_hours: int = 12,
    readable_only: bool = True,
    page_size: int = 1000
) -> AsyncGenerator[List[Relay], None]:
    """Fetch relays from database in pages using async generator.

    This is a memory-efficient alternative to fetch_relays_from_database that yields
    relays in batches instead of loading all into memory at once.

    Args:
        config: Configuration dictionary with database connection info
        threshold_hours: Only fetch relays with metadata newer than this many hours
        readable_only: If True, only fetch relays marked as readable
        page_size: Number of relays to yield per batch (default: 1000)

    Yields:
        Lists of Relay objects in batches of page_size
    """
    logging.info("📦 Fetching relay metadata from database (paginated)...")

    host, port, user, password, dbname = _get_db_config(config)

    # Use window function with ORDER BY for consistent pagination
    if readable_only:
        query = """
            WITH ranked_metadata AS (
                SELECT
                    relay_url,
                    generated_at,
                    ROW_NUMBER() OVER (PARTITION BY relay_url ORDER BY generated_at DESC) as rn
                FROM relay_metadata rm
                JOIN nip66 n ON rm.nip66_id = n.id
                WHERE rm.generated_at > $1 AND n.readable = TRUE
            )
            SELECT relay_url
            FROM ranked_metadata
            WHERE rn = 1
            ORDER BY relay_url
            LIMIT $2 OFFSET $3
        """
    else:
        query = """
            WITH ranked_metadata AS (
                SELECT
                    relay_url,
                    generated_at,
                    ROW_NUMBER() OVER (PARTITION BY relay_url ORDER BY generated_at DESC) as rn
                FROM relay_metadata
                WHERE generated_at > $1
            )
            SELECT relay_url
            FROM ranked_metadata
            WHERE rn = 1
            ORDER BY relay_url
            LIMIT $2 OFFSET $3
        """

    threshold = int(time.time()) - 60 * 60 * threshold_hours
    offset = 0
    total_relays = 0

    async with Bigbrotr(host, port, user, password, dbname) as bigbrotr:
        while True:
            rows = await bigbrotr.fetch(query, threshold, page_size, offset)

            if not rows:
                break

            page_relays: List[Relay] = []
            for row in rows:
                relay_url = row[0].strip()
                try:
                    relay = Relay(relay_url)
                    page_relays.append(relay)
                except Exception as e:
                    logging.warning(f"⚠️ Invalid relay: {relay_url}. Error: {e}")
                    continue

            if page_relays:
                total_relays += len(page_relays)
                yield page_relays

            # If we got fewer rows than page_size, we've reached the end
            if len(rows) < page_size:
                break

            offset += page_size

    logging.info(f"📦 {total_relays} relays fetched from database (paginated).")


async def fetch_relays_from_file(filepath: str, shuffle: bool = True) -> List[Relay]:
    """Fetch relays from a text file (one URL per line).

    Args:
        filepath: Path to text file containing relay URLs
        shuffle: If True, randomly shuffle the relay list (default: True)

    Returns:
        List of Relay objects, optionally shuffled
    """
    import aiofiles

    logging.info(f"📦 Loading relays from file: {filepath}")
    relays: List[Relay] = []

    async with aiofiles.open(filepath, "r", encoding="utf-8") as file:
        async for line in file:
            relay_url = line.strip()
            if not relay_url or relay_url.startswith("#"):
                # Skip empty lines and comments
                continue

            try:
                relay = Relay(relay_url)
                relays.append(relay)
            except Exception as e:
                logging.warning(f"⚠️ Invalid relay: {relay_url}. Error: {e}")
                continue

    logging.info(f"📦 {len(relays)} relays loaded from file.")
    if shuffle:
        random.shuffle(relays)
    return relays


async def fetch_all_relays_from_database(config: Dict[str, Any]) -> List[Relay]:
    """Fetch all relays from database registry.

    Args:
        config: Configuration dictionary with database connection info

    Returns:
        List of all Relay objects from the relays table
    """
    logging.info("📦 Fetching all relays from database registry...")

    host, port, user, password, dbname = _get_db_config(config)

    query = "SELECT url FROM relays"

    async with Bigbrotr(host, port, user, password, dbname) as bigbrotr:
        rows = await bigbrotr.fetch(query)

    relays: List[Relay] = []
    for row in rows:
        relay_url = row[0].strip()
        try:
            relay = Relay(relay_url)
            relays.append(relay)
        except Exception as e:
            logging.warning(f"⚠️ Invalid relay: {relay_url}. Error: {e}")
            continue

    logging.info(f"📦 {len(relays)} total relays fetched from database.")
    return relays


async def fetch_relays_needing_metadata(
    config: Dict[str, Any],
    frequency_hours: int
) -> List[Relay]:
    """Fetch relays that need metadata updates (for monitor service).

    Args:
        config: Configuration dictionary with database connection info
        frequency_hours: Fetch relays with metadata older than this many hours

    Returns:
        List of Relay objects that need metadata updates
    """
    logging.info("📦 Fetching relays needing metadata updates...")

    host, port, user, password, dbname = _get_db_config(config)

    # Use LATERAL join for better performance on large tables
    query = """
    SELECT r.url
    FROM relays r
    LEFT JOIN LATERAL (
        SELECT generated_at
        FROM relay_metadata
        WHERE relay_url = r.url
        ORDER BY generated_at DESC
        LIMIT 1
    ) rm ON TRUE
    WHERE rm.generated_at IS NULL OR rm.generated_at < $1
    """

    threshold = int(time.time()) - 60 * 60 * frequency_hours

    async with Bigbrotr(host, port, user, password, dbname) as bigbrotr:
        rows = await bigbrotr.fetch(query, threshold)

    relays: List[Relay] = []
    for row in rows:
        try:
            relay = Relay(row[0])
            relays.append(relay)
        except Exception as e:
            logging.warning(f"⚠️ Invalid relay: {row[0]}. Error: {e}")
            continue

    logging.info(f"📦 {len(relays)} relays need metadata updates.")
    return relays


async def fetch_relays_needing_metadata_paginated(
    config: Dict[str, Any],
    frequency_hours: int,
    page_size: int = 1000
) -> AsyncGenerator[List[Relay], None]:
    """Fetch relays that need metadata updates in pages using async generator.

    This is a memory-efficient alternative to fetch_relays_needing_metadata that yields
    relays in batches instead of loading all into memory at once.

    Args:
        config: Configuration dictionary with database connection info
        frequency_hours: Fetch relays with metadata older than this many hours
        page_size: Number of relays to yield per batch (default: 1000)

    Yields:
        Lists of Relay objects that need metadata updates in batches of page_size
    """
    logging.info("📦 Fetching relays needing metadata updates (paginated)...")

    host, port, user, password, dbname = _get_db_config(config)

    # Use LATERAL join with ORDER BY for consistent pagination
    query = """
    SELECT r.url
    FROM relays r
    LEFT JOIN LATERAL (
        SELECT generated_at
        FROM relay_metadata
        WHERE relay_url = r.url
        ORDER BY generated_at DESC
        LIMIT 1
    ) rm ON TRUE
    WHERE rm.generated_at IS NULL OR rm.generated_at < $1
    ORDER BY r.url
    LIMIT $2 OFFSET $3
    """

    threshold = int(time.time()) - 60 * 60 * frequency_hours
    offset = 0
    total_relays = 0

    async with Bigbrotr(host, port, user, password, dbname) as bigbrotr:
        while True:
            rows = await bigbrotr.fetch(query, threshold, page_size, offset)

            if not rows:
                break

            page_relays: List[Relay] = []
            for row in rows:
                try:
                    relay = Relay(row[0])
                    page_relays.append(relay)
                except Exception as e:
                    logging.warning(f"⚠️ Invalid relay: {row[0]}. Error: {e}")
                    continue

            if page_relays:
                total_relays += len(page_relays)
                yield page_relays

            # If we got fewer rows than page_size, we've reached the end
            if len(rows) < page_size:
                break

            offset += page_size

    logging.info(f"📦 {total_relays} relays need metadata updates (paginated).")
