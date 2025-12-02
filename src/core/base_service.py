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
from typing import Any, ClassVar, Generic, Optional, TypeVar

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
        MAX_CONSECUTIVE_FAILURES: Default limit before run_forever stops

    Instance Attributes:
        _brotr: Database interface (access pool via _brotr.pool)
        _config: Service configuration (Pydantic model)
        _logger: Structured logger
        _is_running: True while service is active
        _shutdown_event: Event for graceful shutdown
    """

    SERVICE_NAME: ClassVar[str] = "base_service"
    CONFIG_CLASS: ClassVar[Optional[type[BaseModel]]] = None
    MAX_CONSECUTIVE_FAILURES: ClassVar[int] = 5

    def __init__(self, brotr: Brotr, config: Optional[ConfigT] = None) -> None:
        self._brotr = brotr
        self._config: Optional[ConfigT] = config
        self._is_running = False
        self._logger = Logger(self.SERVICE_NAME)
        self._shutdown_event = asyncio.Event()

    @abstractmethod
    async def run(self) -> None:
        """Execute main service logic."""
        ...

    def request_shutdown(self) -> None:
        """Request graceful shutdown (sync-safe for signal handlers)."""
        self._is_running = False
        self._shutdown_event.set()

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
        max_consecutive_failures: Optional[int] = None,
    ) -> None:
        """
        Run service continuously with interval between cycles.

        Calls run() repeatedly until shutdown is requested or max consecutive
        failures is reached. Each cycle is followed by an interruptible wait.

        Args:
            interval: Seconds to wait between run() cycles
            max_consecutive_failures: Stop after this many consecutive errors
                                      (0 = unlimited, None = use class default)
        """
        failure_limit = (
            max_consecutive_failures
            if max_consecutive_failures is not None
            else self.MAX_CONSECUTIVE_FAILURES
        )

        self._logger.info(
            "run_forever_started",
            interval=interval,
            max_consecutive_failures=failure_limit,
        )

        consecutive_failures = 0

        while self._is_running:
            try:
                await self.run()
                consecutive_failures = 0  # Reset on success
            except Exception as e:
                consecutive_failures += 1
                self._logger.error(
                    "run_cycle_error",
                    error=str(e),
                    consecutive_failures=consecutive_failures,
                )

                if failure_limit > 0 and consecutive_failures >= failure_limit:
                    self._logger.critical(
                        "max_consecutive_failures_reached",
                        failures=consecutive_failures,
                        limit=failure_limit,
                    )
                    break

            self._logger.info("cycle_completed", next_run_in_seconds=interval)

            if await self.wait(interval):
                break

        self._logger.info("run_forever_stopped")

    # -------------------------------------------------------------------------
    # Factory Methods
    # -------------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, config_path: str, brotr: Brotr, **kwargs: Any) -> "BaseService":
        """Create service from YAML configuration file."""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        return cls.from_dict(data, brotr=brotr, **kwargs)

    @classmethod
    def from_dict(cls, data: dict[str, Any], brotr: Brotr, **kwargs: Any) -> "BaseService":
        """Create service from dictionary configuration."""
        config = None
        if cls.CONFIG_CLASS is not None:
            config = cls.CONFIG_CLASS(**data)
        return cls(brotr=brotr, config=config, **kwargs)

    # -------------------------------------------------------------------------
    # Context Manager
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> "BaseService":
        """Start service on context entry."""
        self._is_running = True
        self._shutdown_event.clear()
        self._logger.info("started")
        return self

    async def __aexit__(self, _exc_type: Any, _exc_val: Any, _exc_tb: Any) -> None:
        """Stop service on context exit."""
        self._is_running = False
        self._shutdown_event.set()
        self._logger.info("stopped")

    @property
    def config(self) -> Optional[ConfigT]:
        """Get service configuration (typed to CONFIG_CLASS)."""
        return self._config
