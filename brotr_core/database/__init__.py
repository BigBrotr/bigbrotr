"""Brotr database layer with repository pattern.

This module provides the database layer using the repository pattern,
enabling flexible storage strategies through plugin system.

Key Components:
    - Brotr: Unified database interface (auto-selects implementation via plugin system)
    - DatabasePool: Connection pool management
    - BaseEventRepository: Abstract base for event storage
    - RelayRepository: Relay operations (shared)
    - MetadataRepository: Metadata operations (shared)

Usage:
    from brotr_core.database import Brotr
    
    # Bigbrotr mode (full storage)
    async with Brotr(..., mode='bigbrotr') as db:
        await db.insert_event(event, relay)
    
    # Lilbrotr mode (minimal storage)
    async with Brotr(..., mode='lilbrotr') as db:
        await db.insert_event(event, relay)
    
    # Your custom implementation
    async with Brotr(..., mode='yourbrotr') as db:
        await db.insert_event(event, relay)
"""

# Empty __all__ to prevent circular imports
# Import specific classes directly from their modules when needed
__all__ = []

