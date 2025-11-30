"""
BigBrotr Core Layer.

Production-ready foundation components:
- Pool: PostgreSQL connection pooling with asyncpg
- Brotr: High-level database interface with stored procedures
- BaseService: Generic base class for all services with typed config
- Logger: Structured logging

Example:
    from core import Pool, Brotr, Logger

    pool = Pool.from_yaml("config.yaml")
    brotr = Brotr(pool=pool)

    # Using Brotr context manager (recommended)
    async with brotr:
        result = await brotr.insert_relays([...])
"""

from .base_service import BaseService, ConfigT
from .brotr import Brotr, BrotrConfig
from .logger import Logger
from .pool import Pool, PoolConfig

__all__ = [
    "Pool",
    "PoolConfig",
    "Brotr",
    "BrotrConfig",
    "BaseService",
    "ConfigT",
    "Logger",
]
