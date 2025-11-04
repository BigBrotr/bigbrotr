"""Relay loading utilities for fetching relays from database or files."""
import logging
import random
import time
from typing import List, Dict, Any

import aiofiles
from bigbrotr import BigBrotr
from nostr_tools import Relay


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

    async with BigBrotr(host, port, user, password, dbname) as bigbrotr:
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


async def fetch_relays_from_file(filepath: str, shuffle: bool = True) -> List[Relay]:
    """Fetch relays from a text file (one URL per line).

    Args:
        filepath: Path to text file containing relay URLs
        shuffle: If True, randomly shuffle the relay list (default: True)

    Returns:
        List of Relay objects, optionally shuffled
    """
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

    async with BigBrotr(host, port, user, password, dbname) as bigbrotr:
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

    async with BigBrotr(host, port, user, password, dbname) as bigbrotr:
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
