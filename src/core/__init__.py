"""
BigBrotr Core Layer

Production-ready foundation components for the BigBrotr system.

Components:
- Pool: PostgreSQL pooling with asyncpg
- Brotr: High-level database interface with stored procedure wrappers
- Service: Generic service lifecycle wrapper with health checks
- ServiceLogger: Structured JSON logging

Example:
    from core import Pool, Brotr, Service

    pool = Pool.from_yaml("config/pool.yaml")
    brotr = Brotr(pool=pool)

    async with Service(pool, name="database"):
        await brotr.insert_events([...])
"""

from .brotr import Brotr, BrotrConfig
from .logger import (
    ServiceLogger,
    configure_logging,
    get_logger,
    get_service_logger,
)
from .pool import Pool, PoolConfig
from .service import (
    BackgroundService,
    CircuitBreakerConfig,
    DatabaseService,
    HealthCheckConfig,
    Service,
    ServiceConfig,
)

__all__ = [
    "BackgroundService",
    # Brotr
    "Brotr",
    "BrotrConfig",
    "CircuitBreakerConfig",
    "DatabaseService",
    "HealthCheckConfig",
    # Pool
    "Pool",
    "PoolConfig",
    # Service
    "Service",
    "ServiceConfig",
    # Logger
    "ServiceLogger",
    "configure_logging",
    "get_logger",
    "get_service_logger",
]
