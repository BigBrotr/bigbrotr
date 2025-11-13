"""
Service Wrapper for Lifecycle Management

This module provides a generic Service wrapper that adds common functionality
to any service: logging, health checks, statistics, and lifecycle management.

Features:
- Automatic logging for all operations
- Health check endpoints
- Performance metrics and statistics
- Graceful startup and shutdown
- Warmup capabilities
- Context manager support

Example usage:
    from core.service import Service
    from core.pool import ConnectionPool

    pool = ConnectionPool(host="localhost", database="mydb")
    service = Service(pool, name="database_pool")

    async with service:
        # Service handles logging, warmup, health checks
        result = await service.instance.fetch("SELECT 1")
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Generic, Optional, Protocol, TypeVar

from pydantic import BaseModel, Field


# ============================================================================
# Service Protocol - Define what a "manageable service" looks like
# ============================================================================


class ManagedService(Protocol):
    """
    Protocol defining the interface for services that can be managed.

    A service must implement:
    - connect() or start(): Initialize the service
    - close() or stop(): Cleanup the service
    - is_connected or is_running: Check if service is active
    """

    async def connect(self) -> None:
        """Initialize the service (can also be called 'start')."""
        ...

    async def close(self) -> None:
        """Cleanup the service (can also be called 'stop')."""
        ...

    @property
    def is_connected(self) -> bool:
        """Check if service is active (can also be 'is_running')."""
        ...


# Type variable for the wrapped service
T = TypeVar("T")


# ============================================================================
# Configuration
# ============================================================================


class ServiceConfig(BaseModel):
    """Configuration for Service wrapper."""

    # Logging
    enable_logging: bool = Field(default=True, description="Enable automatic logging")
    log_level: str = Field(default="INFO", description="Log level (DEBUG, INFO, WARNING, ERROR)")

    # Health checks
    enable_health_checks: bool = Field(default=True, description="Enable health check functionality")
    health_check_interval: float = Field(
        default=60.0, ge=1.0, description="Interval between health checks (seconds)"
    )
    health_check_timeout: float = Field(
        default=5.0, ge=0.1, description="Timeout for health check operations"
    )

    # Warmup
    enable_warmup: bool = Field(default=False, description="Enable warmup on service start")
    warmup_timeout: float = Field(default=10.0, ge=0.1, description="Timeout for warmup operation")

    # Statistics
    enable_stats: bool = Field(default=True, description="Enable statistics collection")


@dataclass
class ServiceStats:
    """Runtime statistics for a service."""

    name: str
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    uptime_seconds: float = 0.0
    health_checks_performed: int = 0
    health_checks_failed: int = 0
    last_health_check: Optional[datetime] = None
    last_health_status: bool = False
    custom_stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "name": self.name,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
            "uptime_seconds": self.uptime_seconds,
            "health_checks": {
                "total": self.health_checks_performed,
                "failed": self.health_checks_failed,
                "success_rate": (
                    (self.health_checks_performed - self.health_checks_failed)
                    / self.health_checks_performed
                    * 100
                    if self.health_checks_performed > 0
                    else 0.0
                ),
                "last_check": self.last_health_check.isoformat() if self.last_health_check else None,
                "last_status": "healthy" if self.last_health_status else "unhealthy",
            },
            "custom": self.custom_stats,
        }


# ============================================================================
# Service Wrapper
# ============================================================================


class Service(Generic[T]):
    """
    Generic service wrapper that adds lifecycle management, logging, and monitoring.

    This wrapper can be used with any service that implements the ManagedService protocol
    (has connect/start, close/stop, and is_connected/is_running).

    Features:
    - Automatic logging for startup, shutdown, and errors
    - Health check functionality
    - Runtime statistics
    - Graceful startup and shutdown
    - Context manager support

    Example:
        pool = ConnectionPool(host="localhost")
        service = Service(pool, name="db_pool")

        async with service:
            result = await service.instance.fetch("SELECT 1")

        # Check health
        is_healthy = await service.health_check()

        # Get statistics
        stats = service.get_stats()
    """

    def __init__(
        self,
        instance: T,
        name: str,
        config: Optional[ServiceConfig] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize Service wrapper.

        Args:
            instance: The service instance to wrap
            name: Human-readable name for the service (used in logs)
            config: Service configuration (uses defaults if None)
            logger: Custom logger (creates one if None)
        """
        self._instance = instance
        self._name = name
        self._config = config or ServiceConfig()
        self._stats = ServiceStats(name=name)

        # Setup logger
        if logger:
            self._logger = logger
        else:
            self._logger = logging.getLogger(f"service.{name}")
            self._logger.setLevel(getattr(logging, self._config.log_level))

        # Health check task
        self._health_check_task: Optional[asyncio.Task] = None
        self._is_running = False

    @property
    def instance(self) -> T:
        """Get the wrapped service instance."""
        return self._instance

    @property
    def name(self) -> str:
        """Get service name."""
        return self._name

    @property
    def is_running(self) -> bool:
        """Check if service is running."""
        return self._is_running

    def _log(self, level: str, message: str, **kwargs):
        """Internal logging helper."""
        if self._config.enable_logging:
            log_func = getattr(self._logger, level.lower())
            log_func(f"[{self._name}] {message}", **kwargs)

    async def start(self) -> None:
        """
        Start the service.

        This will:
        1. Call connect() or start() on the wrapped instance
        2. Optionally perform warmup
        3. Start health check monitoring
        4. Update statistics
        """
        if self._is_running:
            self._log("warning", "Service is already running")
            return

        self._log("info", "Starting service...")
        start_time = time.time()

        try:
            # Call connect() or start() on wrapped instance
            if hasattr(self._instance, "connect"):
                await self._instance.connect()
            elif hasattr(self._instance, "start"):
                await self._instance.start()
            else:
                raise AttributeError(
                    f"Service instance must have 'connect()' or 'start()' method"
                )

            # Warmup if enabled
            if self._config.enable_warmup:
                self._log("info", "Performing warmup...")
                await self._warmup()

            # Start health checks if enabled
            if self._config.enable_health_checks:
                self._health_check_task = asyncio.create_task(self._health_check_loop())

            # Update stats
            self._is_running = True
            self._stats.started_at = datetime.now()

            elapsed = time.time() - start_time
            self._log("info", f"Service started successfully in {elapsed:.2f}s")

        except Exception as e:
            self._log("error", f"Failed to start service: {e}", exc_info=True)
            raise

    async def stop(self) -> None:
        """
        Stop the service gracefully.

        This will:
        1. Stop health check monitoring
        2. Call close() or stop() on the wrapped instance
        3. Update statistics
        """
        if not self._is_running:
            self._log("warning", "Service is not running")
            return

        self._log("info", "Stopping service...")
        start_time = time.time()

        try:
            # Stop health check task
            if self._health_check_task:
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass
                self._health_check_task = None

            # Call close() or stop() on wrapped instance
            if hasattr(self._instance, "close"):
                await self._instance.close()
            elif hasattr(self._instance, "stop"):
                await self._instance.stop()
            else:
                raise AttributeError(
                    f"Service instance must have 'close()' or 'stop()' method"
                )

            # Update stats
            self._is_running = False
            self._stats.stopped_at = datetime.now()
            if self._stats.started_at:
                self._stats.uptime_seconds = (
                    self._stats.stopped_at - self._stats.started_at
                ).total_seconds()

            elapsed = time.time() - start_time
            self._log("info", f"Service stopped gracefully in {elapsed:.2f}s")

        except Exception as e:
            self._log("error", f"Error while stopping service: {e}", exc_info=True)
            raise

    async def health_check(self, timeout: Optional[float] = None) -> bool:
        """
        Perform a health check on the service.

        Args:
            timeout: Timeout for health check (uses config default if None)

        Returns:
            True if service is healthy, False otherwise
        """
        timeout = timeout or self._config.health_check_timeout

        try:
            # Check if service is connected/running
            is_connected = False
            if hasattr(self._instance, "is_connected"):
                is_connected = self._instance.is_connected
            elif hasattr(self._instance, "is_running"):
                is_connected = self._instance.is_running

            if not is_connected:
                return False

            # Try to perform a simple operation if available
            if hasattr(self._instance, "fetchval"):
                # For database pools
                await asyncio.wait_for(
                    self._instance.fetchval("SELECT 1", timeout=timeout), timeout=timeout
                )
            elif hasattr(self._instance, "ping"):
                # For services with ping method
                await asyncio.wait_for(self._instance.ping(), timeout=timeout)

            return True

        except Exception as e:
            self._log("debug", f"Health check failed: {e}")
            return False

    async def _health_check_loop(self):
        """Background task that performs periodic health checks."""
        while True:
            try:
                await asyncio.sleep(self._config.health_check_interval)

                is_healthy = await self.health_check()

                # Update stats
                self._stats.health_checks_performed += 1
                self._stats.last_health_check = datetime.now()
                self._stats.last_health_status = is_healthy

                if not is_healthy:
                    self._stats.health_checks_failed += 1
                    self._log("warning", "Health check failed")
                else:
                    self._log("debug", "Health check passed")

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._log("error", f"Error in health check loop: {e}", exc_info=True)

    async def _warmup(self):
        """Perform warmup operations on the service."""
        if hasattr(self._instance, "warmup"):
            try:
                await asyncio.wait_for(
                    self._instance.warmup(), timeout=self._config.warmup_timeout
                )
            except asyncio.TimeoutError:
                self._log("warning", f"Warmup timed out after {self._config.warmup_timeout}s")
            except Exception as e:
                self._log("warning", f"Warmup failed: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get runtime statistics for the service.

        Returns:
            Dictionary with service statistics
        """
        if self._config.enable_stats:
            # Update uptime if service is running
            if self._is_running and self._stats.started_at:
                self._stats.uptime_seconds = (
                    datetime.now() - self._stats.started_at
                ).total_seconds()

            return self._stats.to_dict()
        return {"name": self._name, "stats_disabled": True}

    def update_custom_stats(self, key: str, value: Any):
        """
        Update custom statistics.

        Args:
            key: Stat key
            value: Stat value
        """
        if self._config.enable_stats:
            self._stats.custom_stats[key] = value

    async def __aenter__(self) -> "Service[T]":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.stop()

    def __repr__(self) -> str:
        """String representation."""
        status = "running" if self._is_running else "stopped"
        return f"Service(name={self._name}, status={status})"
