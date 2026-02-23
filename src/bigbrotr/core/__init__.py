"""Core layer providing the foundation for all BigBrotr services.

Sits in the middle of the diamond DAG -- depends only on
``bigbrotr.models`` and is depended upon by ``bigbrotr.services``.

Attributes:
    Pool: Async PostgreSQL connection pool with retry/backoff and health checks.
        See [Pool][bigbrotr.core.pool.Pool].
    Brotr: High-level database facade wrapping stored procedures via
        ``_call_procedure()``.
        Services use [Brotr][bigbrotr.core.brotr.Brotr], never
        [Pool][bigbrotr.core.pool.Pool] directly.
    BaseService: Abstract generic base class with lifecycle management
        ([run()][bigbrotr.core.base_service.BaseService.run] /
        [run_forever()][bigbrotr.core.base_service.BaseService.run_forever] /
        shutdown), factory methods
        ([from_yaml()][bigbrotr.core.base_service.BaseService.from_yaml],
        [from_dict()][bigbrotr.core.base_service.BaseService.from_dict]),
        and Prometheus metrics integration.
    Logger: Structured logger supporting key=value and JSON output modes.
        See [Logger][bigbrotr.core.logger.Logger].
    MetricsServer: Prometheus ``/metrics`` HTTP endpoint for metrics exposition.
        See [MetricsServer][bigbrotr.core.metrics.MetricsServer].
    YAML: Safe YAML loading with ``yaml.safe_load()`` to prevent code execution.
        See [load_yaml()][bigbrotr.core.yaml.load_yaml].

Examples:
    ```python
    from bigbrotr.core import Pool, Brotr, Logger

    pool = Pool.from_yaml("config.yaml")
    brotr = Brotr(pool=pool)
    async with brotr:
        await brotr.insert_relay([...])
    ```

See Also:
    [bigbrotr.models][bigbrotr.models]: Pure dataclass models consumed by this layer.
    [bigbrotr.services][bigbrotr.services]: Service implementations that depend on
        this layer.
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
    PoolLimitsConfig,
    PoolRetryConfig,
    PoolTimeoutsConfig,
    ServerSettingsConfig,
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
