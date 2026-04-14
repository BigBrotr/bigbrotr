"""Ten independent services plus shared utilities.

Services are the top layer of the diamond DAG, depending on
[bigbrotr.core][bigbrotr.core], [bigbrotr.nips][bigbrotr.nips],
[bigbrotr.utils][bigbrotr.utils], and [bigbrotr.models][bigbrotr.models].
Each service extends [BaseService][bigbrotr.core.base_service.BaseService]
and implements ``async def run()`` for one cycle of work. All services
communicate exclusively through the shared PostgreSQL database.

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
    Refresher: Periodic current-state and analytics refresh in dependency order.
        Provides per-target logging, timing, and error isolation.
    Ranker: Private DuckDB-backed NIP-85 ranking service. Syncs canonical
        follow-graph facts and later computes/export ranks.
    Api: REST API for read-only database access via FastAPI with
        auto-generated paginated endpoints.
    Dvm: NIP-90 Data Vending Machine exposing public read-model queries
        via the Nostr protocol with per-read-model pricing.
    Assertor: NIP-85 Trusted Assertions publisher. Reads facts and rank
        snapshots and publishes kind 30382/30383/30384/30385 events.

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

from .api import (
    Api,
    ApiConfig,
)
from .assertor import (
    Assertor,
    AssertorConfig,
)
from .dvm import (
    Dvm,
    DvmConfig,
)
from .finder import (
    Finder,
    FinderConfig,
)
from .monitor import (
    Monitor,
    MonitorConfig,
)
from .ranker import (
    Ranker,
    RankerConfig,
)
from .refresher import (
    Refresher,
    RefresherConfig,
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
    "Api",
    "ApiConfig",
    "Assertor",
    "AssertorConfig",
    "Dvm",
    "DvmConfig",
    "Finder",
    "FinderConfig",
    "Monitor",
    "MonitorConfig",
    "Ranker",
    "RankerConfig",
    "Refresher",
    "RefresherConfig",
    "Seeder",
    "SeederConfig",
    "Synchronizer",
    "SynchronizerConfig",
    "Validator",
    "ValidatorConfig",
]
