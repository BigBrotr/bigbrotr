"""
BigBrotr Services Package.

Service implementations that build on the core layer:
- Initializer: Database bootstrap and schema verification
- Finder: Relay discovery from events and APIs
- Monitor: Relay health monitoring (pending)
- Synchronizer: Event synchronization (pending)

All services inherit from BaseService for consistent:
- Logging
- Lifecycle management (start/stop)
- Context manager support

Example:
    from core import Pool, Brotr
    from services import Initializer, Finder

    pool = Pool.from_yaml("config.yaml")
    brotr = Brotr(pool=pool)

    async with pool:
        # Run initializer
        initializer = Initializer(brotr=brotr)
        await initializer.run()

        # Run finder with context manager
        finder = Finder(brotr=brotr)
        async with finder:
            await finder.run_forever(interval=3600)
"""

from .finder import (
    SERVICE_NAME as FINDER_SERVICE_NAME,
    Finder,
    FinderConfig,
)
from .initializer import (
    SERVICE_NAME as INITIALIZER_SERVICE_NAME,
    Initializer,
    InitializerConfig,
    InitializerError,
)

__all__ = [
    # Initializer
    "INITIALIZER_SERVICE_NAME",
    "Initializer",
    "InitializerConfig",
    "InitializerError",
    # Finder
    "FINDER_SERVICE_NAME",
    "Finder",
    "FinderConfig",
]
