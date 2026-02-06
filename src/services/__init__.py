"""BigBrotr services package.

Provides the five service implementations that build on the core layer:

- **Seeder**: One-shot seeding of initial relay URLs for validation.
- **Finder**: Continuous relay URL discovery from external APIs and stored events.
- **Validator**: Validates candidate relays by testing if they speak Nostr protocol.
- **Monitor**: Comprehensive relay health monitoring with NIP-11 and NIP-66 checks.
- **Synchronizer**: High-throughput event collection from relays via multiprocessing.

All services inherit from ``BaseService`` and share a consistent interface for
logging, lifecycle management (start/stop), and async context manager support.

Example::

    from core import Brotr
    from services import Seeder, Finder

    brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
    async with brotr.pool:
        # One-shot seeding
        seeder = Seeder(brotr=brotr)
        await seeder.run()

        # Continuous discovery
        finder = Finder.from_yaml("yaml/services/finder.yaml", brotr=brotr)
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
