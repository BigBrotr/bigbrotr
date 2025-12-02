"""
BigBrotr Core Layer.

Production-ready foundation components:
- Pool: PostgreSQL connection pooling with asyncpg
- Brotr: High-level database interface with stored procedures
- BaseService: Generic base class for all services with typed config
- Logger: Structured logging with JSON support

Example:
    from core import Pool, Brotr, Logger

    pool = Pool.from_yaml("config.yaml")
    brotr = Brotr(pool=pool)

    # Using Brotr context manager (recommended)
    async with brotr:
        result = await brotr.insert_relays([...])
"""

from .base_service import (
    BaseService,
    ConfigT,
)
from .brotr import (
    BatchConfig,
    Brotr,
    BrotrConfig,
    TimeoutsConfig as BrotrTimeoutsConfig,
)
from .logger import Logger
from .pool import (
    DatabaseConfig,
    LimitsConfig as PoolLimitsConfig,
    Pool,
    PoolConfig,
    RetryConfig,
    ServerSettingsConfig,
    TimeoutsConfig as PoolTimeoutsConfig,
)

__all__ = [
    # Base Service
    "BaseService",
    "ConfigT",
    # Brotr
    "BatchConfig",
    "Brotr",
    "BrotrConfig",
    "BrotrTimeoutsConfig",
    # Pool
    "DatabaseConfig",
    # Logger
    "Logger",
    "Pool",
    "PoolConfig",
    "PoolLimitsConfig",
    "PoolTimeoutsConfig",
    "RetryConfig",
    "ServerSettingsConfig",
]