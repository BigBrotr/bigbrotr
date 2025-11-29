"""
Shared utilities for BigBrotr services.

This module contains common helper functions used across multiple services
to avoid code duplication.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional, Union

from nostr_tools import Relay


def build_relay_records(
    urls: Union[set[str], list[str]], current_time: Optional[int] = None
) -> list[dict[str, Any]]:
    """
    Build relay records from URLs with network auto-detection.

    Validates each URL using nostr-tools Relay class and extracts
    the normalized URL and network type (clearnet/tor).

    Args:
        urls: Set or list of relay URLs to process
        current_time: Unix timestamp for inserted_at field (default: now)

    Returns:
        List of relay record dicts with url, network, inserted_at
    """
    if current_time is None:
        current_time = int(time.time())

    records = []
    for url in urls:
        try:
            relay = Relay(url)
            records.append({
                "url": relay.url,
                "network": relay.network,
                "inserted_at": current_time,
            })
        except Exception:
            pass  # Skip invalid URLs
    return records


async def save_service_state(
    pool: Any,
    service_name: str,
    state_dict: dict[str, Any],
    timeout: float = 30.0,
) -> None:
    """
    Save service state to database.

    Args:
        pool: Database pool with execute method
        service_name: Unique service identifier
        state_dict: State data to persist
        timeout: Query timeout in seconds
    """
    await pool.execute(
        """
        INSERT INTO service_state (service_name, state, updated_at)
        VALUES ($1, $2::jsonb, $3)
        ON CONFLICT (service_name) DO UPDATE SET state = $2::jsonb, updated_at = $3
        """,
        service_name,
        json.dumps(state_dict),
        int(time.time()),
        timeout=timeout,
    )


async def load_service_state(
    pool: Any,
    service_name: str,
    timeout: float = 30.0,
) -> Optional[dict[str, Any]]:
    """
    Load service state from database.

    Args:
        pool: Database pool with fetchrow method
        service_name: Unique service identifier
        timeout: Query timeout in seconds

    Returns:
        State dict if found, None otherwise
    """
    row = await pool.fetchrow(
        "SELECT state FROM service_state WHERE service_name = $1",
        service_name,
        timeout=timeout,
    )

    if row and row["state"]:
        state_data = row["state"]
        if isinstance(state_data, str):
            state_data = json.loads(state_data)
        return state_data

    return None
