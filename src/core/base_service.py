"""
Base Service for BigBrotr Services.

Provides abstract base class for all services with:
- Logging
- Lifecycle management (start/stop)
- Factory methods (from_yaml/from_dict)
- Graceful error handling with max consecutive failures

Services that need state persistence should implement their own
storage using dedicated database tables.
"""

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, Generic, TypeVar, cast

import yaml
from pydantic import BaseModel

from .brotr import Brotr
from .logger import Logger


# Type variable for service configuration
ConfigT = TypeVar("ConfigT", bound=BaseModel)


class BaseService(ABC, Generic[ConfigT]):
    """
    Abstract base class for all BigBrotr services.

    Subclasses must:
    - Set SERVICE_NAME class attribute
    - Set CONFIG_CLASS for automatic config parsing
    - Implement run() method for main service logic

    Services that need persistent state should implement their own
    storage mechanism using dedicated database tables.

    Class Attributes:
        SERVICE_NAME: Unique identifier for the service (used in logging)
        CONFIG_CLASS: Pydantic model class for configuration parsing
        _DEFAULT_MAX_CONSECUTIVE_FAILURES: Default limit before run_forever stops

    Instance Attributes:
        _brotr: Database interface (access pool via _brotr.pool)
        _config: Service configuration (Pydantic model, uses CONFIG_CLASS defaults if not provided)
        _logger: Structured logger
        _shutdown_event: Event for graceful shutdown (single source of truth)
                        Not set = service is running
                        Set = shutdown requested
    """

    SERVICE_NAME: ClassVar[str] = "base_service"
    CONFIG_CLASS: ClassVar[type[BaseModel]]
    _DEFAULT_MAX_CONSECUTIVE_FAILURES: ClassVar[int] = 5

    def __init__(self, brotr: Brotr, config: ConfigT | None = None) -> None:
        self._brotr = brotr
        self._config: ConfigT = (
            config if config is not None else cast("ConfigT", self.CONFIG_CLASS())
        )
        self._logger = Logger(self.SERVICE_NAME)
        # Use shutdown event as single source of truth to avoid race conditions
        # Event not set = service is running, Event set = shutdown requested
        self._shutdown_event = asyncio.Event()

    @property
    def config(self) -> ConfigT:
        """Get service configuration (typed to CONFIG_CLASS)."""
        return self._config

    @abstractmethod
    async def run(self) -> None:
        """Execute main service logic."""
        ...

    def request_shutdown(self) -> None:
        """
        Request graceful shutdown (sync-safe for signal handlers).

        Thread-safe: Setting an asyncio.Event is atomic and safe to call
        from signal handlers or other threads.
        """
        self._shutdown_event.set()

    @property
    def is_running(self) -> bool:
        """
        Check if service is running.

        Returns True if shutdown has NOT been requested.
        """
        return not self._shutdown_event.is_set()

    async def wait(self, timeout: float) -> bool:
        """
        Wait for shutdown event or timeout.

        Returns True if shutdown was requested, False if timeout expired.
        Use in service loops for interruptible waits.
        """
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def run_forever(
        self,
        interval: float,
        max_consecutive_failures: int | None = None,
    ) -> None:
        """
        Run service continuously with interval between cycles.

        Calls run() repeatedly until shutdown is requested or max consecutive
        failures is reached. Each cycle is followed by an interruptible wait.

        Args:
            interval: Seconds to wait between run() cycles
            max_consecutive_failures: Stop after this many consecutive errors
                                      (0 = unlimited, None = use class default)

        Example:
            >>> async with MyService(brotr, config) as service:
            ...     # Run every 5 minutes, stop after 3 consecutive failures
            ...     await service.run_forever(interval=300, max_consecutive_failures=3)

        Note:
            - Use request_shutdown() to stop gracefully from signal handlers
            - Consecutive failure counter resets after each successful run()
            - CancelledError, KeyboardInterrupt, SystemExit propagate immediately
        """
        if max_consecutive_failures is None:
            max_consecutive_failures = self._DEFAULT_MAX_CONSECUTIVE_FAILURES

        self._logger.info(
            "run_forever_started",
            interval=interval,
            max_consecutive_failures=max_consecutive_failures,
        )

        consecutive_failures = 0

        # Use is_running property which checks shutdown_event atomically
        while self.is_running:
            try:
                await self.run()
                consecutive_failures = 0  # Reset on success
                self._logger.info("cycle_completed", next_run_in_seconds=interval)
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                # Let these propagate to allow proper shutdown
                raise
            except Exception as e:
                consecutive_failures += 1
                self._logger.error(
                    "run_cycle_error",
                    error=str(e),
                    consecutive_failures=consecutive_failures,
                )

                if (
                    max_consecutive_failures > 0
                    and consecutive_failures >= max_consecutive_failures
                ):
                    self._logger.critical(
                        "max_consecutive_failures_reached",
                        failures=consecutive_failures,
                        limit=max_consecutive_failures,
                    )
                    break

            if await self.wait(interval):
                break

        self._logger.info("run_forever_stopped")

    # -------------------------------------------------------------------------
    # Factory Methods
    # -------------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, config_path: str, brotr: Brotr, **kwargs: Any) -> "BaseService[ConfigT]":
        """Create service from YAML configuration file."""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        return cls.from_dict(data, brotr=brotr, **kwargs)

    @classmethod
    def from_dict(cls, data: dict[str, Any], brotr: Brotr, **kwargs: Any) -> "BaseService[ConfigT]":
        """Create service from dictionary configuration."""
        config = cls.CONFIG_CLASS(**data)
        return cls(brotr=brotr, config=config, **kwargs)  # type: ignore[arg-type]

    # -------------------------------------------------------------------------
    # Context Manager
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> "BaseService[ConfigT]":
        """Start service on context entry."""
        # Clear shutdown event to mark service as running
        self._shutdown_event.clear()
        self._logger.info("started")
        return self

    async def __aexit__(self, _exc_type: Any, _exc_val: Any, _exc_tb: Any) -> None:
        """Stop service on context exit."""
        # Set shutdown event to mark service as stopped
        self._shutdown_event.set()
        self._logger.info("stopped")
