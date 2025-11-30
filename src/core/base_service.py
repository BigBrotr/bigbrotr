"""
Base Service for BigBrotr Services.

Provides abstract base class for all services with:
- Logging
- Lifecycle management (start/stop)
- State persistence (load/save to database)
- Factory methods (from_yaml/from_dict)
"""

import asyncio
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel

from .brotr import Brotr
from .logger import Logger


class BaseService(ABC):
    """
    Abstract base class for all BigBrotr services.

    Subclasses must:
    - Set SERVICE_NAME class attribute
    - Set CONFIG_CLASS for automatic config parsing
    - Implement run() method for main service logic

    Attributes:
        _brotr: Database interface (access pool via _brotr.pool)
        _config: Service configuration (Pydantic model)
        _state: Service state (dict, persisted to database)
        _logger: Structured logger
        _is_running: True while service is active
        _shutdown_event: Event for graceful shutdown
    """

    SERVICE_NAME: str = "base_service"
    CONFIG_CLASS: Optional[type[BaseModel]] = None

    def __init__(self, brotr: Brotr, config: Optional[BaseModel] = None) -> None:
        self._brotr = brotr
        self._config = config
        self._state: dict[str, Any] = {}
        self._is_running = False
        self._logger = Logger(self.SERVICE_NAME)
        self._shutdown_event = asyncio.Event()

    @abstractmethod
    async def run(self) -> None:
        """Execute main service logic."""
        ...

    async def health_check(self) -> bool:
        """Check if service is healthy."""
        try:
            result = await self._brotr.pool.fetchval("SELECT 1")
            return result == 1
        except Exception:
            return False

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

    async def run_forever(self, interval: float) -> None:
        """
        Run service continuously with interval between cycles.

        Calls run() repeatedly until shutdown is requested.
        Each cycle is followed by an interruptible wait.

        Args:
            interval: Seconds to wait between run() cycles
        """
        self._logger.info("run_forever_started", interval=interval)

        while self._is_running:
            try:
                await self.run()
            except Exception as e:
                self._logger.error("run_cycle_error", error=str(e))

            if await self.wait(interval):
                break

        self._logger.info("run_forever_stopped")

    # -------------------------------------------------------------------------
    # State Persistence
    # -------------------------------------------------------------------------

    async def _load_state(self) -> None:
        """
        Load service state from database.

        Populates self._state with persisted state or empty dict if none exists.
        Called automatically on context entry (__aenter__).
        """
        row = await self._brotr.pool.fetchrow(
            "SELECT state FROM service_state WHERE service_name = $1",
            self.SERVICE_NAME,
        )

        if row is not None:
            self._state = dict(row["state"])
            self._logger.debug("state_loaded", keys=list(self._state.keys()))
        else:
            self._state = {}
            self._logger.debug("state_empty")

    async def _save_state(self) -> None:
        """
        Save service state to database.

        Persists self._state using upsert (INSERT ... ON CONFLICT UPDATE).
        Called automatically on context exit (__aexit__).
        """
        if not self._state:
            return

        await self._brotr.pool.execute(
            """
            INSERT INTO service_state (service_name, state, updated_at)
            VALUES ($1, $2, $3)
            ON CONFLICT (service_name) DO UPDATE
            SET state = $2, updated_at = $3
            """,
            self.SERVICE_NAME,
            self._state,
            int(time.time()),
        )
        self._logger.debug("state_saved", keys=list(self._state.keys()))

    @property
    def state(self) -> dict[str, Any]:
        """Get current service state."""
        return self._state

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

    async def __aenter__(self) -> "BaseService":
        """Start service on context entry. Loads persisted state."""
        self._is_running = True
        self._shutdown_event.clear()
        await self._load_state()
        self._logger.info("started")
        return self

    async def __aexit__(self, _exc_type: Any, _exc_val: Any, _exc_tb: Any) -> None:
        """Stop service on context exit. Saves state to database."""
        self._is_running = False
        self._shutdown_event.set()
        await self._save_state()
        self._logger.info("stopped")

    @property
    def config(self) -> BaseModel:
        """Get service configuration."""
        return self._config
