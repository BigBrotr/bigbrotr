"""
Service Wrapper for Lifecycle Management
Generic service wrapper that adds lifecycle management, logging, monitoring,
and fault tolerance to any service implementing the ManagedService protocol.

Features:
- Automatic structured logging for all operations
- Health check functionality with configurable callbacks
- Circuit breaker pattern for fault tolerance
- Runtime statistics with Prometheus export
- Graceful startup and shutdown with warmup support
- Thread-safe statistics collection
- Context manager support
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Generic, Optional, Protocol, Tuple, TypeVar, Union

from pydantic import BaseModel, Field, field_validator

# Try to import structured logger, fallback to standard logging
try:
    from .logger import ServiceLogger, get_service_logger
    STRUCTURED_LOGGING_AVAILABLE = True
except ImportError:
    STRUCTURED_LOGGING_AVAILABLE = False


# ============================================================================
# Service Protocols
# ============================================================================


class DatabaseService(Protocol):
    """
    Protocol for database-style services.

    Services implementing this protocol use connect/close nomenclature.
    Examples: ConnectionPool, Brotr
    """

    async def connect(self) -> None:
        """Initialize the database connection."""
        ...

    async def close(self) -> None:
        """Close the database connection."""
        ...

    @property
    def is_connected(self) -> bool:
        """Check if database is connected."""
        ...


class BackgroundService(Protocol):
    """
    Protocol for background services.

    Services implementing this protocol use start/stop nomenclature.
    Examples: Finder, Monitor, Synchronizer
    """

    async def start(self) -> None:
        """Start the background service."""
        ...

    async def stop(self) -> None:
        """Stop the background service."""
        ...

    @property
    def is_running(self) -> bool:
        """Check if service is running."""
        ...


# Union type for any manageable service
ManagedService = Union[DatabaseService, BackgroundService]

# Type variable for the wrapped service
T = TypeVar("T")

# Type alias for health check callback
HealthCheckCallback = Optional[Callable[[Any], Awaitable[bool]]]


# ============================================================================
# Pydantic Models for Configuration Validation
# ============================================================================


class LoggingConfig(BaseModel):
    """Logging configuration."""

    enable_logging: bool = Field(default=True, description="Enable automatic logging")
    log_level: str = Field(default="INFO", description="Log level")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Ensure log level is valid."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}, got: {v}")
        return v_upper


class HealthCheckConfig(BaseModel):
    """Health check configuration."""

    enable_health_checks: bool = Field(default=True, description="Enable health check functionality")
    health_check_interval: float = Field(
        default=60.0,
        ge=0.1,
        description="Interval between health checks (seconds)"
    )
    health_check_timeout: float = Field(
        default=5.0,
        ge=0.1,
        description="Timeout for health check operations (seconds)"
    )
    health_check_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Number of retry attempts for health check before reporting failure"
    )
    health_check_retry_delay: float = Field(
        default=1.0,
        ge=0.1,
        description="Delay between health check retry attempts (seconds)"
    )


class WarmupConfig(BaseModel):
    """Warmup configuration."""

    enable_warmup: bool = Field(default=False, description="Enable warmup on service start")
    warmup_timeout: float = Field(
        default=10.0,
        ge=0.1,
        description="Timeout for warmup operation (seconds)"
    )
    warmup_required: bool = Field(
        default=False,
        description="If True, service startup fails if warmup fails"
    )


class CircuitBreakerConfig(BaseModel):
    """Circuit breaker configuration."""

    enable_circuit_breaker: bool = Field(default=False, description="Enable circuit breaker pattern")
    circuit_breaker_threshold: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Failed health checks before opening circuit"
    )
    circuit_breaker_timeout: float = Field(
        default=300.0,
        ge=0.1,
        description="Cooldown period before attempting reset (seconds)"
    )


class MetricsConfig(BaseModel):
    """Metrics export configuration."""

    enable_stats: bool = Field(default=True, description="Enable statistics collection")
    enable_prometheus_metrics: bool = Field(
        default=False,
        description="Enable Prometheus metrics export"
    )


class ServiceConfig(BaseModel):
    """
    Complete service wrapper configuration.

    Structured configuration with clear separation of concerns:
    - logging: Logging behavior and level
    - health_check: Health check interval and timeout
    - warmup: Warmup behavior on startup
    - circuit_breaker: Fault tolerance settings
    - metrics: Statistics and metrics export
    """

    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    health_check: HealthCheckConfig = Field(default_factory=HealthCheckConfig)
    warmup: WarmupConfig = Field(default_factory=WarmupConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)


# ============================================================================
# Circuit Breaker State
# ============================================================================


@dataclass
class CircuitBreakerState:
    """
    Circuit breaker state tracking.

    Tracks consecutive failures, circuit state, and provides thread-safe
    state management with async locks.
    """

    consecutive_failures: int = 0
    is_open: bool = False
    opened_at: Optional[datetime] = None
    total_opens: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def record_success(self) -> None:
        """
        Record a successful health check.

        Resets consecutive failures and closes circuit if open.
        """
        async with self._lock:
            self.consecutive_failures = 0
            if self.is_open:
                self.is_open = False
                self.opened_at = None

    async def record_failure(self) -> None:
        """Record a failed health check."""
        async with self._lock:
            self.consecutive_failures += 1

    async def open_circuit(self) -> None:
        """Open the circuit breaker."""
        async with self._lock:
            if not self.is_open:
                self.is_open = True
                self.opened_at = datetime.now()
                self.total_opens += 1

    async def should_attempt_reset(self, timeout: float) -> bool:
        """
        Check if enough time has passed to attempt reset.

        Args:
            timeout: Cooldown period in seconds

        Returns:
            True if should attempt reset, False otherwise
        """
        async with self._lock:
            if not self.is_open or not self.opened_at:
                return False
            elapsed = (datetime.now() - self.opened_at).total_seconds()
            return elapsed >= timeout

    async def check_and_should_reset(self, timeout: float) -> Tuple[bool, bool]:
        """
        Atomically check if circuit is open and if reset should be attempted.

        This method performs both checks in a single lock acquisition to avoid
        race conditions in the health check loop.

        Args:
            timeout: Cooldown period in seconds

        Returns:
            Tuple of (is_open, should_attempt_reset)
        """
        async with self._lock:
            if not self.is_open:
                return (False, False)

            if not self.opened_at:
                return (True, False)

            elapsed = (datetime.now() - self.opened_at).total_seconds()
            should_reset = elapsed >= timeout
            return (True, should_reset)

    async def to_dict(self) -> Dict[str, Any]:
        """
        Convert circuit breaker state to dictionary (thread-safe).

        Returns:
            Dictionary with circuit breaker state
        """
        async with self._lock:
            return {
                "is_open": self.is_open,
                "consecutive_failures": self.consecutive_failures,
                "opened_at": self.opened_at.isoformat() if self.opened_at else None,
                "total_opens": self.total_opens,
            }


# ============================================================================
# Service Statistics
# ============================================================================


@dataclass
class ServiceStats:
    """
    Runtime statistics for a service.

    Tracks health checks, uptime, and custom metrics with thread-safe
    operations using async locks.
    """

    name: str
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    uptime_seconds: float = 0.0
    health_checks_performed: int = 0
    health_checks_failed: int = 0
    last_health_check: Optional[datetime] = None
    last_health_status: bool = False
    custom_stats: Dict[str, Any] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def record_health_check(self, is_healthy: bool) -> None:
        """
        Record a health check result (thread-safe).

        Args:
            is_healthy: Whether the health check passed
        """
        async with self._lock:
            self.health_checks_performed += 1
            self.last_health_check = datetime.now()
            self.last_health_status = is_healthy
            if not is_healthy:
                self.health_checks_failed += 1

    async def update_custom_stat(self, key: str, value: Any) -> None:
        """
        Update custom statistic (thread-safe).

        Args:
            key: Stat key
            value: Stat value
        """
        async with self._lock:
            self.custom_stats[key] = value

    async def to_dict(self) -> Dict[str, Any]:
        """
        Convert stats to dictionary (thread-safe).

        Returns:
            Dictionary with service statistics
        """
        async with self._lock:
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
                "custom": self.custom_stats.copy(),  # Return a copy to prevent external mutation
            }

    async def to_prometheus(self) -> str:
        """
        Export statistics in Prometheus format (thread-safe).

        Returns:
            Prometheus-formatted metrics string
        """
        async with self._lock:
            metrics = []
            service_label = f'service="{self.name}"'

            # Uptime
            metrics.append(f"# HELP service_uptime_seconds Service uptime in seconds")
            metrics.append(f"# TYPE service_uptime_seconds gauge")
            metrics.append(f"service_uptime_seconds{{{service_label}}} {self.uptime_seconds}")

            # Health checks
            metrics.append(f"# HELP service_health_checks_total Total health checks performed")
            metrics.append(f"# TYPE service_health_checks_total counter")
            metrics.append(f"service_health_checks_total{{{service_label}}} {self.health_checks_performed}")

            metrics.append(f"# HELP service_health_checks_failed_total Failed health checks")
            metrics.append(f"# TYPE service_health_checks_failed_total counter")
            metrics.append(f"service_health_checks_failed_total{{{service_label}}} {self.health_checks_failed}")

            # Success rate
            success_rate = (
                (self.health_checks_performed - self.health_checks_failed)
                / self.health_checks_performed
                if self.health_checks_performed > 0
                else 1.0
            )
            metrics.append(f"# HELP service_health_check_success_rate Health check success rate (0-1)")
            metrics.append(f"# TYPE service_health_check_success_rate gauge")
            metrics.append(f"service_health_check_success_rate{{{service_label}}} {success_rate}")

            # Status
            status_value = 1 if self.last_health_status else 0
            metrics.append(f"# HELP service_status Current service status (1=healthy, 0=unhealthy)")
            metrics.append(f"# TYPE service_status gauge")
            metrics.append(f"service_status{{{service_label}}} {status_value}")

            # Custom stats (iterate over a copy to avoid holding lock during string operations)
            custom_stats_copy = self.custom_stats.copy()

        # Process custom stats outside lock (only string operations, no shared state access)
        for key, value in custom_stats_copy.items():
            if isinstance(value, (int, float)):
                safe_key = key.replace("-", "_").replace(" ", "_")
                metrics.append(f"# HELP service_custom_{safe_key} Custom metric: {key}")
                metrics.append(f"# TYPE service_custom_{safe_key} gauge")
                metrics.append(f"service_custom_{safe_key}{{{service_label}}} {value}")

        return "\n".join(metrics)


# ============================================================================
# Service Wrapper Class
# ============================================================================


class Service(Generic[T]):
    """
    Generic service wrapper for lifecycle management and monitoring.

    Wraps any service implementing ManagedService protocol and adds:
    - Automatic structured logging
    - Health check monitoring with circuit breaker
    - Runtime statistics and Prometheus metrics
    - Graceful startup/shutdown with warmup
    - Thread-safe statistics collection

    Features:
    - Dual protocol support (DatabaseService and BackgroundService)
    - Configurable health check callbacks
    - Circuit breaker for fault tolerance
    - Structured JSON logging (if logger.py available)
    - Prometheus metrics export
    - Context manager support

    Example usage:
        # Basic usage
        pool = ConnectionPool(host="localhost", database="mydb")
        service = Service(pool, name="database_pool")

        async with service:
            result = await service.instance.fetch("SELECT 1")

        # Advanced usage with custom health check
        async def check_pool(pool: ConnectionPool) -> bool:
            return await pool.fetchval("SELECT 1") == 1

        config = ServiceConfig(
            circuit_breaker=CircuitBreakerConfig(
                enable_circuit_breaker=True,
                circuit_breaker_threshold=3
            )
        )

        service = Service(
            pool,
            name="db_pool",
            config=config,
            health_check_callback=check_pool
        )

        async with service:
            # Check health manually
            is_healthy = await service.health_check()

            # Get statistics
            stats = service.get_stats()

            # Export Prometheus metrics
            metrics = service.export_prometheus_metrics()

            # Check circuit breaker state
            cb_state = service.get_circuit_breaker_state()
    """

    def __init__(
        self,
        instance: T,
        name: str,
        config: Optional[ServiceConfig] = None,
        logger: Optional[logging.Logger] = None,
        health_check_callback: HealthCheckCallback = None,
    ):
        """
        Initialize Service wrapper.

        Args:
            instance: The service instance to wrap
            name: Human-readable name for the service (used in logs)
            config: Service configuration (uses defaults if None)
            logger: Custom logger (creates one if None)
            health_check_callback: Optional custom health check function

        Example:
            # Minimal
            service = Service(pool, name="db_pool")

            # With config
            config = ServiceConfig(...)
            service = Service(pool, name="db_pool", config=config)

            # With custom health check
            service = Service(
                pool,
                name="db_pool",
                health_check_callback=lambda p: p.fetchval("SELECT 1") == 1
            )
        """
        self._instance = instance
        self._name = name
        self._config = config or ServiceConfig()
        self._stats = ServiceStats(name=name)
        self._circuit_breaker = CircuitBreakerState()
        self._health_check_callback = health_check_callback

        # Setup logger (structured if available)
        if logger:
            self._logger = logger
            self._structured_logger = None
        elif STRUCTURED_LOGGING_AVAILABLE:
            # Use structured logger
            self._structured_logger = get_service_logger(name, type(instance).__name__)
            self._logger = logging.getLogger(f"service.{name}")
            self._logger.setLevel(getattr(logging, self._config.logging.log_level))
        else:
            # Fallback to standard logger
            self._structured_logger = None
            self._logger = logging.getLogger(f"service.{name}")
            self._logger.setLevel(getattr(logging, self._config.logging.log_level))

        # Health check task
        self._health_check_task: Optional[asyncio.Task] = None
        self._is_running = False

    @property
    def instance(self) -> T:
        """
        Get the wrapped service instance.

        Returns:
            The wrapped service instance
        """
        return self._instance

    @property
    def name(self) -> str:
        """
        Get service name.

        Returns:
            Service name
        """
        return self._name

    @property
    def config(self) -> ServiceConfig:
        """
        Get validated configuration.

        Note: The returned configuration should be treated as read-only.

        Returns:
            ServiceConfig instance
        """
        return self._config

    @property
    def is_running(self) -> bool:
        """
        Check if service is running.

        Returns:
            True if service is running, False otherwise
        """
        return self._is_running

    def _log(self, level: str, message: str, **kwargs):
        """
        Internal logging helper with structured logging support.

        Args:
            level: Log level (debug, info, warning, error, critical)
            message: Log message
            **kwargs: Additional structured fields (exc_info, etc.)
        """
        if not self._config.logging.enable_logging:
            return

        # Extract exc_info if present
        exc_info = kwargs.pop("exc_info", False)

        if self._structured_logger:
            # Use structured logger with service context
            log_func = getattr(self._structured_logger, level.lower())
            log_func(message, **kwargs)
        else:
            # Fallback to standard logger
            log_func = getattr(self._logger, level.lower())
            log_func(f"[{self._name}] {message}", exc_info=exc_info)

    async def start(self) -> None:
        """
        Start the service.

        This will:
        1. Call connect() or start() on the wrapped instance
        2. Optionally perform warmup
        3. Start health check monitoring
        4. Update statistics

        Raises:
            AttributeError: If service doesn't have connect/start method
            Exception: If warmup_required=True and warmup fails
        """
        if self._is_running:
            self._log("warning", "service_already_running")
            return

        self._log("info", "service_starting")
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
            if self._config.warmup.enable_warmup:
                self._log("info", "warmup_starting", timeout=self._config.warmup.warmup_timeout)
                await self._warmup()

            # Start health checks if enabled
            if self._config.health_check.enable_health_checks:
                self._health_check_task = asyncio.create_task(self._health_check_loop())

            # Update stats
            self._is_running = True
            self._stats.started_at = datetime.now()

            elapsed = time.time() - start_time
            self._log(
                "info",
                "service_started",
                elapsed_seconds=round(elapsed, 3),
                warmup_enabled=self._config.warmup.enable_warmup,
                health_checks_enabled=self._config.health_check.enable_health_checks,
                circuit_breaker_enabled=self._config.circuit_breaker.enable_circuit_breaker,
            )

        except Exception as e:
            elapsed = time.time() - start_time
            self._log(
                "error",
                "service_start_failed",
                error=str(e),
                error_type=type(e).__name__,
                elapsed_seconds=round(elapsed, 3),
                exc_info=True,
            )
            raise

    async def stop(self) -> None:
        """
        Stop the service gracefully.

        This will:
        1. Stop health check monitoring
        2. Call close() or stop() on the wrapped instance
        3. Update statistics

        Raises:
            AttributeError: If service doesn't have close/stop method
        """
        if not self._is_running:
            self._log("warning", "service_not_running")
            return

        self._log("info", "service_stopping")
        start_time = time.time()

        try:
            # Signal shutdown FIRST to stop health check loop
            self._is_running = False

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
            self._stats.stopped_at = datetime.now()
            if self._stats.started_at:
                self._stats.uptime_seconds = (
                    self._stats.stopped_at - self._stats.started_at
                ).total_seconds()

            elapsed = time.time() - start_time
            self._log(
                "info",
                "service_stopped",
                elapsed_seconds=round(elapsed, 3),
                total_uptime_seconds=round(self._stats.uptime_seconds, 3),
                health_checks_performed=self._stats.health_checks_performed,
            )

        except Exception as e:
            self._log(
                "error",
                "service_stop_failed",
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True,
            )
            raise

    async def health_check(
        self,
        timeout: Optional[float] = None,
        retries: Optional[int] = None,
    ) -> bool:
        """
        Perform a health check on the service with retry support.

        Health check priority:
        1. Custom health_check_callback (if provided)
        2. Service's own health_check() method
        3. fetchval("SELECT 1") for database pools
        4. ping() for services with ping method
        5. Just check is_connected/is_running

        Args:
            timeout: Timeout for health check (uses config default if None)
            retries: Number of retry attempts (uses config default if None)

        Returns:
            True if service is healthy, False otherwise
        """
        timeout = timeout or self._config.health_check.health_check_timeout
        max_retries = retries if retries is not None else self._config.health_check.health_check_retries
        retry_delay = self._config.health_check.health_check_retry_delay

        for attempt in range(max_retries):
            result = await self._perform_single_health_check(timeout)
            if result:
                return True

            # If not last attempt, wait before retry
            if attempt < max_retries - 1:
                self._log(
                    "debug",
                    "health_check_retry",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                )
                await asyncio.sleep(retry_delay)

        return False

    async def _perform_single_health_check(self, timeout: float) -> bool:
        """
        Perform a single health check attempt.

        Args:
            timeout: Timeout for this health check attempt

        Returns:
            True if service is healthy, False otherwise
        """
        try:
            # Check if service is connected/running first
            is_connected = False
            if hasattr(self._instance, "is_connected"):
                is_connected = self._instance.is_connected
            elif hasattr(self._instance, "is_running"):
                is_connected = self._instance.is_running

            if not is_connected:
                return False

            # Use custom callback if provided
            if self._health_check_callback:
                result = await asyncio.wait_for(
                    self._health_check_callback(self._instance),
                    timeout=timeout
                )
                return bool(result)

            # Try service's own health_check method
            if hasattr(self._instance, "health_check"):
                result = await asyncio.wait_for(
                    self._instance.health_check(),
                    timeout=timeout
                )
                return bool(result)

            # For database pools - use fetchval
            if hasattr(self._instance, "fetchval"):
                await self._instance.fetchval("SELECT 1", timeout=timeout)
                return True

            # For services with ping method
            if hasattr(self._instance, "ping"):
                await asyncio.wait_for(self._instance.ping(), timeout=timeout)
                return True

            # If no specific check available, return connection status
            return True

        except Exception as e:
            self._log("debug", f"Health check attempt failed: {e}")
            return False

    async def _health_check_loop(self):
        """
        Background task for periodic health checks.

        Integrates with circuit breaker:
        - Opens circuit after threshold failures
        - Attempts reset after cooldown period
        - Logs circuit breaker state changes
        """
        while self._is_running:
            try:
                await asyncio.sleep(self._config.health_check.health_check_interval)

                # Double-check still running after sleep
                if not self._is_running:
                    break

                # Check if circuit breaker should attempt reset
                # Uses atomic check to avoid race conditions
                if self._config.circuit_breaker.enable_circuit_breaker:
                    is_open, should_reset = await self._circuit_breaker.check_and_should_reset(
                        self._config.circuit_breaker.circuit_breaker_timeout
                    )

                    if is_open and not should_reset:
                        # Circuit open, timeout not reached - skip health check
                        self._log("debug", "circuit_breaker_open_skipping_check")
                        continue
                    elif should_reset:
                        # Circuit open, timeout reached - attempt reset
                        self._log("info", "circuit_breaker_attempting_reset")

                # Perform health check
                is_healthy = await self.health_check()

                # Update stats (thread-safe)
                await self._stats.record_health_check(is_healthy)

                # Update circuit breaker
                if self._config.circuit_breaker.enable_circuit_breaker:
                    if is_healthy:
                        was_open = self._circuit_breaker.is_open
                        await self._circuit_breaker.record_success()
                        if was_open:
                            self._log("info", "circuit_breaker_closed_service_recovered")
                        else:
                            self._log("debug", "health_check_passed")
                    else:
                        await self._circuit_breaker.record_failure()

                        # Check if threshold reached
                        if (self._circuit_breaker.consecutive_failures >=
                            self._config.circuit_breaker.circuit_breaker_threshold):
                            await self._circuit_breaker.open_circuit()
                            self._log(
                                "error",
                                "circuit_breaker_opened",
                                consecutive_failures=self._circuit_breaker.consecutive_failures,
                                threshold=self._config.circuit_breaker.circuit_breaker_threshold,
                            )
                        else:
                            self._log(
                                "warning",
                                "health_check_failed",
                                consecutive_failures=self._circuit_breaker.consecutive_failures,
                                threshold=self._config.circuit_breaker.circuit_breaker_threshold,
                            )
                else:
                    # No circuit breaker, just log
                    if not is_healthy:
                        self._log("warning", "health_check_failed")
                    else:
                        self._log("debug", "health_check_passed")

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._log("error", f"Error in health check loop: {e}", exc_info=True)

    async def _warmup(self):
        """
        Perform warmup operations on the service.

        Raises:
            TimeoutError: If warmup_required=True and warmup times out
            Exception: If warmup_required=True and warmup fails
        """
        if hasattr(self._instance, "warmup"):
            try:
                await asyncio.wait_for(
                    self._instance.warmup(),
                    timeout=self._config.warmup.warmup_timeout
                )
                self._log("info", "warmup_completed")
            except asyncio.TimeoutError as e:
                error_msg = f"Warmup timed out after {self._config.warmup.warmup_timeout}s"
                if self._config.warmup.warmup_required:
                    self._log("error", "warmup_timeout", timeout=self._config.warmup.warmup_timeout)
                    raise TimeoutError(error_msg) from e
                else:
                    self._log("warning", "warmup_timeout", timeout=self._config.warmup.warmup_timeout)
            except Exception as e:
                if self._config.warmup.warmup_required:
                    self._log("error", "warmup_failed", error=str(e), exc_info=True)
                    raise
                else:
                    self._log("warning", "warmup_failed", error=str(e))

    async def get_stats(self) -> Dict[str, Any]:
        """
        Get runtime statistics for the service (thread-safe).

        Includes circuit breaker state if enabled.

        Returns:
            Dictionary with service statistics
        """
        if self._config.metrics.enable_stats:
            # Update uptime if service is running (thread-safe)
            if self._is_running and self._stats.started_at:
                async with self._stats._lock:
                    self._stats.uptime_seconds = (
                        datetime.now() - self._stats.started_at
                    ).total_seconds()

            stats = await self._stats.to_dict()

            # Add circuit breaker state if enabled
            if self._config.circuit_breaker.enable_circuit_breaker:
                stats["circuit_breaker"] = await self._circuit_breaker.to_dict()

            return stats
        return {"name": self._name, "stats_disabled": True}

    async def update_custom_stats(self, key: str, value: Any):
        """
        Update custom statistics (thread-safe).

        Args:
            key: Stat key
            value: Stat value
        """
        if self._config.metrics.enable_stats:
            await self._stats.update_custom_stat(key, value)

    async def export_prometheus_metrics(self) -> str:
        """
        Export service metrics in Prometheus format (thread-safe).

        Returns:
            Prometheus-formatted metrics string

        Example:
            metrics = await service.export_prometheus_metrics()
            # # HELP service_uptime_seconds Service uptime in seconds
            # # TYPE service_uptime_seconds gauge
            # service_uptime_seconds{service="db_pool"} 3600.5
        """
        if not self._config.metrics.enable_prometheus_metrics:
            return f"# Prometheus metrics disabled for service '{self._name}'\n"

        # Update uptime (thread-safe)
        if self._is_running and self._stats.started_at:
            async with self._stats._lock:
                self._stats.uptime_seconds = (
                    datetime.now() - self._stats.started_at
                ).total_seconds()

        metrics = [await self._stats.to_prometheus()]

        # Add circuit breaker metrics if enabled
        if self._config.circuit_breaker.enable_circuit_breaker:
            cb = self._circuit_breaker
            service_label = f'service="{self._name}"'

            # Read circuit breaker state (thread-safe)
            async with cb._lock:
                is_open = cb.is_open
                consecutive_failures = cb.consecutive_failures
                total_opens = cb.total_opens

            metrics.append(f"\n# HELP service_circuit_breaker_open Circuit breaker state (1=open, 0=closed)")
            metrics.append(f"# TYPE service_circuit_breaker_open gauge")
            metrics.append(f"service_circuit_breaker_open{{{service_label}}} {1 if is_open else 0}")

            metrics.append(f"# HELP service_circuit_breaker_consecutive_failures Consecutive health check failures")
            metrics.append(f"# TYPE service_circuit_breaker_consecutive_failures gauge")
            metrics.append(f"service_circuit_breaker_consecutive_failures{{{service_label}}} {consecutive_failures}")

            metrics.append(f"# HELP service_circuit_breaker_total_opens Total times circuit breaker opened")
            metrics.append(f"# TYPE service_circuit_breaker_total_opens counter")
            metrics.append(f"service_circuit_breaker_total_opens{{{service_label}}} {total_opens}")

        return "\n".join(metrics)

    async def get_circuit_breaker_state(self) -> Dict[str, Any]:
        """
        Get current circuit breaker state (thread-safe).

        Returns:
            Dictionary with circuit breaker state
        """
        if self._config.circuit_breaker.enable_circuit_breaker:
            return await self._circuit_breaker.to_dict()
        return {"circuit_breaker_disabled": True}

    async def reset_circuit_breaker(self) -> bool:
        """
        Manually reset circuit breaker.

        Returns:
            True if circuit breaker was open and got reset, False otherwise
        """
        if not self._config.circuit_breaker.enable_circuit_breaker:
            return False

        was_open = self._circuit_breaker.is_open
        await self._circuit_breaker.record_success()

        if was_open:
            self._log("info", "circuit_breaker_manually_reset")
            return True
        return False

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
