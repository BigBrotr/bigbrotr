"""
Core layer providing the foundation for all BigBrotr services.

Components:
    Pool:           Async PostgreSQL connection pool with retry and health checks.
    Brotr:          High-level database interface wrapping stored procedures.
    BaseService:    Abstract generic base class for services with typed config.
    Logger:         Structured logger supporting key=value and JSON output.
    MetricsServer:  Prometheus HTTP endpoint for metrics exposition.

Example:
    from core import Pool, Brotr, Logger

    pool = Pool.from_yaml("config.yaml")
    brotr = Brotr(pool=pool)

    async with brotr:
        await brotr.insert_relays([...])
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
from .logger import Logger, format_kv_pairs
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
    "Logger",
    "MetricsConfig",
    "MetricsServer",
    "NetworkSemaphoreMixin",
    "Pool",
    "PoolConfig",
    "PoolLimitsConfig",
    "PoolTimeoutsConfig",
    "RetryConfig",
    "ServerSettingsConfig",
    "format_kv_pairs",
    "load_yaml",
    "start_metrics_server",
]
