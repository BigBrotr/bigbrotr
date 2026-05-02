"""Core runtime infrastructure shared by the service layer.

The core layer sits in the middle of the diamond DAG: it depends on
``bigbrotr.models`` and is consumed by ``bigbrotr.services``. It is also a
useful library surface for anyone embedding the BigBrotr runtime in custom
tooling.

Public exports:
    Pool: Async PostgreSQL connection pool with retry, health checks, and
        connection-lifecycle helpers.
    Brotr: High-level facade over the shared storage contract. Services use
        [Brotr][bigbrotr.core.brotr.Brotr], not the pool, for domain-level
        persistence and query operations.
    BaseService: Generic service base with lifecycle orchestration, config
        factories, structured logging, shutdown handling, and metrics hooks.
    Logger: Structured logger with key-value and JSON output modes.
    MetricsServer: Prometheus ``/metrics`` HTTP endpoint plus metric helpers.
    load_yaml: Safe YAML loading for deployment and service configuration.

Examples:
    ```python
    from bigbrotr.core import Pool, Brotr, Logger

    pool = Pool.from_yaml("config.yaml")
    brotr = Brotr(pool=pool)
    async with brotr:
        await brotr.insert_relay([...])
    ```

See Also:
    [bigbrotr.models][bigbrotr.models]: Pure storage and domain models consumed
        by this layer.
    [bigbrotr.services][bigbrotr.services]: Service implementations that build
        on this runtime foundation.
"""

from .base_service import (
    BaseService,
    BaseServiceConfig,
    ConfigT,
)
from .brotr import Brotr
from .brotr_config import BrotrConfig
from .logger import Logger, StructuredFormatter, format_kv_pairs
from .metrics import (
    CYCLE_DURATION_SECONDS,
    SERVICE_COUNTER,
    SERVICE_GAUGE,
    SERVICE_INFO,
    MetricsServer,
    start_metrics_server,
)
from .pool import Pool
from .pool_config import PoolConfig
from .yaml import load_yaml


__all__ = [
    "CYCLE_DURATION_SECONDS",
    "SERVICE_COUNTER",
    "SERVICE_GAUGE",
    "SERVICE_INFO",
    "BaseService",
    "BaseServiceConfig",
    "Brotr",
    "BrotrConfig",
    "ConfigT",
    "Logger",
    "MetricsServer",
    "Pool",
    "PoolConfig",
    "StructuredFormatter",
    "format_kv_pairs",
    "load_yaml",
    "start_metrics_server",
]
