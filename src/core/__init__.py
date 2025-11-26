"""
BigBrotr Core Layer

Production-ready foundation components for the BigBrotr system.

Components:
- ConnectionPool: PostgreSQL connection pooling with asyncpg
- Brotr: High-level database interface with stored procedure wrappers
- Service: Generic service lifecycle wrapper with health checks
- ServiceLogger: Structured JSON logging

Example:
    from core import ConnectionPool, Brotr, Service

    pool = ConnectionPool.from_yaml("config/pool.yaml")
    brotr = Brotr(pool=pool)

    async with Service(pool, name="database"):
        await brotr.insert_events([...])
"""

from .pool import ConnectionPool, ConnectionPoolConfig
from .brotr import Brotr, BrotrConfig
from .service import (
    Service,
    ServiceConfig,
    DatabaseService,
    BackgroundService,
    HealthCheckConfig,
    CircuitBreakerConfig,
)
from .logger import (
    ServiceLogger,
    configure_logging,
    get_service_logger,
    get_logger,
)

__all__ = [
    # Pool
    "ConnectionPool",
    "ConnectionPoolConfig",
    # Brotr
    "Brotr",
    "BrotrConfig",
    # Service
    "Service",
    "ServiceConfig",
    "DatabaseService",
    "BackgroundService",
    "HealthCheckConfig",
    "CircuitBreakerConfig",
    # Logger
    "ServiceLogger",
    "configure_logging",
    "get_service_logger",
    "get_logger",
]
