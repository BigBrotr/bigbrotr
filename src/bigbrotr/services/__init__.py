"""The five-service processing pipeline plus shared utilities.

Services are the top layer of the diamond DAG, depending on
[bigbrotr.core][bigbrotr.core], [bigbrotr.nips][bigbrotr.nips],
[bigbrotr.utils][bigbrotr.utils], and [bigbrotr.models][bigbrotr.models].
Each service extends [BaseService][bigbrotr.core.base_service.BaseService]
and implements ``async def run()`` for one cycle of work.

```text
Seeder (one-shot) -> Finder -> Validator -> Monitor -> Synchronizer
```

Attributes:
    Seeder: One-shot bootstrapping of initial relay URLs from a seed file.
    Finder: Continuous relay URL discovery from events (kind 2, 3, 10002)
        and external HTTP APIs.
    Validator: Continuous WebSocket testing to verify candidates speak Nostr.
        Promotes valid candidates to the relay table.
    Monitor: Continuous NIP-11 + NIP-66 health checks with per-network
        semaphore concurrency. Publishes kind 10166/30166 Nostr events.
    Synchronizer: Continuous event collection from relays using cursor-based
        pagination with per-relay state tracking.

Note:
    All services follow the same lifecycle pattern: instantiate with a
    [Brotr][bigbrotr.core.brotr.Brotr] instance, then call ``run()`` for
    a single cycle or ``run_forever()`` for continuous operation. Services
    that need setup/teardown should be used as async context managers.

See Also:
    [BaseService][bigbrotr.core.base_service.BaseService]: Abstract base
        class all services extend.
    [Brotr][bigbrotr.core.brotr.Brotr]: High-level database facade passed
        to every service.
    [common][bigbrotr.services.common]: Shared constants, configs, mixins,
        and query functions used across all services.

Examples:
    ```python
    from bigbrotr.core import Brotr
    from bigbrotr.services import Seeder, Finder

    brotr = Brotr.from_yaml("config/brotr.yaml")
    async with brotr:
        seeder = Seeder(brotr=brotr)
        await seeder.run()
    ```
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
    "Finder",
    "FinderConfig",
    "Monitor",
    "MonitorConfig",
    "Seeder",
    "SeederConfig",
    "Synchronizer",
    "SynchronizerConfig",
    "Validator",
    "ValidatorConfig",
]
