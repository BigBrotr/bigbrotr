"""
BigBrotr Core Layer.

Production-ready foundation components:
- Pool: PostgreSQL connection pooling with asyncpg
- Brotr: High-level database interface with stored procedures
- BaseService: Generic base class for all services with typed config

Note: Logger is in src/logger.py (not in core) to avoid circular imports.
      Import it directly: from logger import Logger

Example:
    from core import Pool, Brotr
    from logger import Logger

    pool = Pool.from_yaml("config.yaml")
    brotr = Brotr(pool=pool)

    async with brotr:
        result = await brotr.insert_relays([...])
"""

from utils.yaml import load_yaml

from .brotr import (
    BatchConfig,
    Brotr,
    BrotrConfig,
)
from .brotr import (
    TimeoutsConfig as BrotrTimeoutsConfig,
)
from .metrics import (
    CYCLE_DURATION_SECONDS,
    SERVICE_COUNTER,
    SERVICE_GAUGE,
    SERVICE_INFO,
    MetricsConfig,
    MetricsServer,
    start_metrics_server,
)
from .pool import (
    DatabaseConfig,
    Pool,
    PoolConfig,
    RetryConfig,
    ServerSettingsConfig,
)
from .pool import (
    LimitsConfig as PoolLimitsConfig,
)
from .pool import (
    TimeoutsConfig as PoolTimeoutsConfig,
)
from .service import (
    BaseService,
    BaseServiceConfig,
    ConfigT,
    NetworkSemaphoreMixin,
)


__all__ = [
    "CYCLE_DURATION_SECONDS",
    "SERVICE_COUNTER",
    "SERVICE_GAUGE",
    "SERVICE_INFO",
    "BaseService",
    "BaseServiceConfig",
    "BatchConfig",
    "Brotr",
    "BrotrConfig",
    "BrotrTimeoutsConfig",
    "ConfigT",
    "DatabaseConfig",
    "MetricsConfig",
    "MetricsServer",
    "NetworkSemaphoreMixin",
    "Pool",
    "PoolConfig",
    "PoolLimitsConfig",
    "PoolTimeoutsConfig",
    "RetryConfig",
    "ServerSettingsConfig",
    "load_yaml",
    "start_metrics_server",
]
