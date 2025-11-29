"""
BigBrotr Services Package.

Service implementations that build on the core layer:
- Initializer: Database bootstrap and schema verification
- Finder: Relay discovery from events and APIs
- Monitor: Relay health monitoring (pending)
- Synchronizer: Event synchronization (pending)

All services inherit from BaseService for consistent:
- Logging
- State persistence
- Lifecycle management (start/stop)
- Context manager support

Example:
    from core import Pool
    from services import Initializer, Finder

    pool = Pool.from_yaml("config.yaml")

    async with pool:
        # Run initializer
        initializer = Initializer(pool=pool)
        result = await initializer.run()

        # Run finder with context manager
        finder = Finder(pool=pool)
        async with finder:
            await finder.run_forever(interval=3600)
"""

from core.base_service import Outcome, Step

from .finder import (
    SERVICE_NAME as FINDER_SERVICE_NAME,
    Finder,
    FinderConfig,
    FinderState,
)
from .initializer import (
    SERVICE_NAME as INITIALIZER_SERVICE_NAME,
    Initializer,
    InitializerConfig,
    InitializerState,
)

__all__ = [
    # Types (from core)
    "Outcome",
    "Step",
    # Initializer
    "INITIALIZER_SERVICE_NAME",
    "Initializer",
    "InitializerConfig",
    "InitializerState",
    # Finder
    "FINDER_SERVICE_NAME",
    "Finder",
    "FinderConfig",
    "FinderState",
]