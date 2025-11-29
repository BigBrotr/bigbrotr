"""
BigBrotr Core Layer.

Production-ready foundation components:
- Pool: PostgreSQL connection pooling with asyncpg
- Brotr: High-level database interface with stored procedures
- BaseService: Lightweight base class for all services
- Logger: Structured JSON logging

Example:
    from core import Pool, Brotr, get_logger

    pool = Pool.from_yaml("config.yaml")
    brotr = Brotr(pool=pool)
    logger = get_logger("my_service", component="MyService")

    async with pool:
        result = await brotr.insert_relays([...])
"""

from .base_service import BaseService
from .brotr import Brotr, BrotrConfig
from .logger import (
    Logger,
    configure_logging,
    get_logger,
    validate_log_level,
)
from .pool import Pool, PoolConfig

__all__ = [
    # Core components
    "Pool",
    "PoolConfig",
    "Brotr",
    "BrotrConfig",
    "BaseService",
    # Logger
    "Logger",
    "configure_logging",
    "get_logger",
    "validate_log_level",
]