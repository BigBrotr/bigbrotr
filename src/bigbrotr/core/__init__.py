"""
Core layer providing the foundation for all BigBrotr services.

Components:
    Pool:           Async PostgreSQL connection pool with retry and health checks.
    Brotr:          High-level database interface wrapping stored procedures.
    BaseService:    Abstract generic base class for services with typed config.
    Logger:         Structured logger supporting key=value and JSON output.
    MetricsServer:  Prometheus HTTP endpoint for metrics exposition.

Example:
    from bigbrotr.core import Pool, Brotr, Logger

    pool = Pool.from_yaml("config.yaml")
    brotr = Brotr(pool=pool)

    async with brotr:
        await brotr.insert_relay([...])
"""

from .base_service import (
    BaseService,
    BaseServiceConfig,
    ConfigT,
)
from .brotr import (
    BatchConfig,
    Brotr,
    BrotrConfig,
    BrotrTimeoutsConfig,
)
from .logger import Logger, StructuredFormatter, format_kv_pairs
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
    PoolRetryConfig,
    PoolTimeoutsConfig,
    ServerSettingsConfig,
)
from .pool import (
    LimitsConfig as PoolLimitsConfig,
)
from .yaml import load_yaml


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
    "Pool",
    "PoolConfig",
    "PoolLimitsConfig",
    "PoolRetryConfig",
    "PoolTimeoutsConfig",
    "ServerSettingsConfig",
    "StructuredFormatter",
    "format_kv_pairs",
    "load_yaml",
    "start_metrics_server",
]
