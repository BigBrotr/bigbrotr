"""
BigBrotr Services Package.

Service implementations that build on the core layer:
- Seeder: Seed initial relay data for validation
- Finder: Relay discovery from events and APIs
- Validator: Candidate relay validation
- Monitor: Relay health monitoring
- Synchronizer: Event synchronization

All services inherit from BaseService for consistent:
- Logging
- Lifecycle management (start/stop)
- Context manager support

Example:
    from core import Pool, Brotr
    from services import Seeder, Finder, Validator, Monitor, Synchronizer

    brotr = Brotr.from_yaml("yaml/core/brotr.yaml")

    async with brotr:
        # Run seeder
        seeder = Seeder(brotr=brotr)
        await seeder.run()

        # Run finder with context manager
        finder = Finder(brotr=brotr)
        async with finder:
            await finder.run_forever()
"""

from .finder import (
    Finder,
    FinderConfig,
)
from .monitor import (
    Monitor,
    MonitorConfig,
)
from .seeder import (
    Seeder,
    SeederConfig,
)
from .synchronizer import (
    Synchronizer,
    SynchronizerConfig,
)
from .validator import (
    Validator,
    ValidatorConfig,
)


__all__ = [
    # Finder
    "Finder",
    "FinderConfig",
    # Monitor
    "Monitor",
    "MonitorConfig",
    # Seeder
    "Seeder",
    "SeederConfig",
    # Synchronizer
    "Synchronizer",
    "SynchronizerConfig",
    # Validator
    "Validator",
    "ValidatorConfig",
]
