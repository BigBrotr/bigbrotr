"""Brotr Core - Extensible Plugin Architecture for Nostr Archiving.

This package provides a plugin-based architecture that enables unlimited custom
implementations through automatic discovery and registration.

🔌 Plugin System:
    - Automatic discovery of implementations in implementations/ directory
    - Convention-based configuration
    - Zero core code changes to add new implementations
    - Factory pattern for runtime selection

Main Components:
    - registry: Plugin discovery and registration system
    - database: Repository pattern with factory for flexible storage
    - services: Base service classes for monitoring and synchronization
    - processors: Shared event processing logic

Usage:
    # List available implementations (auto-discovered)
    from brotr_core.registry import list_implementations
    print(list_implementations())  # ['bigbrotr', 'lilbrotr', 'yourbrotr']
    
    # Use Brotr with auto-selection based on BROTR_MODE env var
    from brotr_core.database.brotr import Brotr
    async with Brotr(host, port, user, password, dbname, mode='lilbrotr') as db:
        await db.insert_event(event, relay)

Creating New Implementations:
    1. Create folder: implementations/yourbrotr/
    2. Add SQL schema: sql/init.sql
    3. Add repository: repositories/event_repository.py
    4. System automatically discovers and registers it!
    
    See docs/HOW_TO_CREATE_BROTR.md for detailed guide.
"""

__version__ = '2.0.0'
__author__ = 'Brotr Contributors'
__all__ = ['registry', 'database', 'services']

