"""Core layer providing the foundation for all BigBrotr services.

Sits in the middle of the diamond DAG -- depends only on
`bigbrotr.models` and is depended upon by `bigbrotr.services`.

Attributes:
    Pool: Async PostgreSQL connection pool with retry/backoff and health checks.
    Brotr: High-level database facade wrapping stored procedures via
        `_call_procedure()`. Services use Brotr, never Pool directly.
    BaseService: Abstract generic base class with lifecycle management
        (`run`/`run_forever`/shutdown), factory methods (`from_yaml`,
        `from_dict`), and Prometheus metrics integration.
    Logger: Structured logger supporting key=value and JSON output modes.
    MetricsServer: Prometheus `/metrics` HTTP endpoint for metrics exposition.
    Exceptions: `BigBrotrError` hierarchy with transient vs permanent distinction.
    YAML: Safe YAML loading with `yaml.safe_load()` to prevent code execution.

Examples:
    ```python
    from bigbrotr.core import Pool, Brotr, Logger

    pool = Pool.from_yaml("config.yaml")
    brotr = Brotr(pool=pool)
    async with brotr:
        await brotr.insert_relay([...])
    ```
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
