"""
BigBrotr Services Package.

Service implementations that build on the core layer:
- Initializer: Database bootstrap and schema verification
- Finder: Relay discovery from events and APIs
- Monitor: Relay health monitoring
- Synchronizer: Event synchronization

All services inherit from BaseService for consistent:
- Logging
- Lifecycle management (start/stop)
- Context manager support

Example:
    from core import Pool, Brotr
    from services import Initializer, Finder, Monitor, Synchronizer

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
    Finder,
    FinderConfig,
)
from .initializer import (
    Initializer,
    InitializerConfig,
    InitializerError,
)
from .monitor import (
    Monitor,
    MonitorConfig,
)
from .synchronizer import (
    Synchronizer,
    SynchronizerConfig,
)

__all__ = [
    # Finder
    "Finder",
    "FinderConfig",
    # Initializer
    "Initializer",
    "InitializerConfig",
    "InitializerError",
    # Monitor
    "Monitor",
    "MonitorConfig",
    # Synchronizer
    "Synchronizer",
    "SynchronizerConfig",
]