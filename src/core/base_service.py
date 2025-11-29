"""
Base Service for BigBrotr Services.

Provides a lightweight base class that all services can inherit from.
Handles common concerns: logging, state persistence, lifecycle.

Design Philosophy:
    - Simple inheritance instead of complex wrapper pattern
    - Services work standalone or in Docker
    - No unnecessary complexity (no circuit breaker, prometheus, etc.)
    - Each service still owns its business logic

Usage:
    class MyService(BaseService):
        SERVICE_NAME = "my_service"

        async def run(self) -> Outcome:
            # Service logic here
            return Outcome(success=True, message="Done")

        async def health_check(self) -> bool:
            return self._brotr.pool.is_connected
"""

import asyncio
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, Optional, TypeVar

import yaml
from pydantic import BaseModel

from .brotr import Brotr
from .logger import Logger, get_logger

# Type variable for service-specific state
StateT = TypeVar("StateT")


# =============================================================================
# Shared Types
# =============================================================================


@dataclass
class Step:
    """
    An individual operation step within a service run.

    Used to track the outcome of discrete operations such as
    verification checks, data loading, or processing phases.

    Attributes:
        name: Identifier for this step (e.g., "extensions", "tables")
        success: Whether the step completed successfully
        message: Human-readable description of the outcome
        details: Additional structured data about the step
        duration_ms: Time taken in milliseconds
    """

    name: str
    success: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "success": self.success,
            "message": self.message,
            "details": self.details,
            "duration_ms": round(self.duration_ms, 2),
        }


@dataclass
class Outcome:
    """
    Standard outcome for a service operation.

    Provides a consistent structure for reporting the result of service
    operations like initialization, discovery cycles, or sync runs.

    Attributes:
        success: Whether the operation completed successfully
        message: Human-readable summary of the outcome
        steps: Individual step outcomes (if applicable)
        duration_s: Total operation time in seconds
        errors: List of error messages encountered
        metrics: Service-specific metrics (counts, stats, etc.)
    """

    success: bool
    message: str
    steps: list[Step] = field(default_factory=list)
    duration_s: float = 0.0
    errors: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "message": self.message,
            "steps": [s.to_dict() for s in self.steps],
            "duration_s": round(self.duration_s, 3),
            "errors": self.errors,
            "metrics": self.metrics,
        }


# =============================================================================
# Base State
# =============================================================================


@dataclass
class BaseState:
    """
    Base state that all services share.

    Services should extend this with their own fields.
    """

    last_run_at: int = 0
    run_count: int = 0
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for persistence."""
        return {
            "last_run_at": self.last_run_at,
            "run_count": self.run_count,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BaseState":
        """Create from dictionary."""
        return cls(
            last_run_at=data.get("last_run_at", 0),
            run_count=data.get("run_count", 0),
            last_error=data.get("last_error", ""),
        )


class BaseService(ABC, Generic[StateT]):
    """
    Abstract base class for all BigBrotr services.

    Provides:
    - Structured logging via self._logger
    - State persistence via _load_state() / _save_state()
    - Lifecycle management via start() / stop()
    - Factory methods from_yaml() / from_dict()

    Subclasses must implement:
    - SERVICE_NAME: Class attribute with unique service identifier
    - run(): Main service logic, returns Outcome
    - health_check(): Returns True if service is healthy
    - _create_state(): Create service-specific state from dict
    """

    # Subclasses MUST override this
    SERVICE_NAME: str = "base"

    # Subclasses SHOULD override this for automatic from_dict() support
    CONFIG_CLASS: Optional[type[BaseModel]] = None

    def __init__(
        self,
        brotr: Brotr,
        config: Optional[BaseModel] = None,
    ) -> None:
        """
        Initialize service.

        Args:
            brotr: Brotr instance for database operations
            config: Service-specific Pydantic config (optional)
        """
        self._brotr = brotr
        self._pool = brotr.pool  # Convenience reference
        self._config = config
        self._is_running = False
        self._state: StateT = self._create_default_state()
        self._logger: Logger = get_logger(self.SERVICE_NAME, component=self.__class__.__name__)
        self._shutdown_event: Optional[asyncio.Event] = None

    # -------------------------------------------------------------------------
    # Abstract Methods (subclasses MUST implement)
    # -------------------------------------------------------------------------

    @abstractmethod
    async def run(self) -> Outcome:
        """
        Execute the main service logic.

        Returns:
            Outcome with success status, message, and metrics
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if service is healthy.

        Returns:
            True if healthy, False otherwise
        """
        ...

    @abstractmethod
    def _create_default_state(self) -> StateT:
        """
        Create default state instance.

        Returns:
            Service-specific state dataclass
        """
        ...

    @abstractmethod
    def _state_from_dict(self, data: dict[str, Any]) -> StateT:
        """
        Create state from dictionary.

        Args:
            data: State dictionary from database

        Returns:
            Service-specific state dataclass
        """
        ...

    # -------------------------------------------------------------------------
    # Lifecycle Methods
    # -------------------------------------------------------------------------

    async def start(self) -> None:
        """
        Start the service.

        Loads persisted state and marks service as running.
        """
        if self._is_running:
            self._logger.warning("already_running")
            return

        self._shutdown_event = asyncio.Event()
        await self._load_state()
        self._is_running = True
        self._logger.info("started", state=self._state_to_dict())

    async def stop(self) -> None:
        """
        Stop the service.

        Saves state and marks service as stopped.
        """
        if not self._is_running:
            return

        self._is_running = False
        if self._shutdown_event:
            self._shutdown_event.set()
        await self._save_state()
        self._logger.info("stopped")

    @property
    def is_running(self) -> bool:
        """Check if service is running."""
        return self._is_running

    # -------------------------------------------------------------------------
    # Continuous Run Loop (for long-running services)
    # -------------------------------------------------------------------------

    async def run_forever(self, interval: float = 3600.0) -> None:
        """
        Run service continuously at specified interval.

        Args:
            interval: Seconds between runs (default: 1 hour)
        """
        if not self._shutdown_event:
            raise RuntimeError("Service not started. Call start() first.")

        cycle = 0
        self._logger.info("run_forever_started", interval=interval)

        while self._is_running and not self._shutdown_event.is_set():
            cycle += 1
            self._logger.info("cycle_starting", cycle=cycle)

            try:
                result = await self.run()
                self._logger.info(
                    "cycle_completed",
                    cycle=cycle,
                    success=result.success,
                    duration_s=round(result.duration_s, 2),
                )
            except Exception as e:
                self._logger.error("cycle_failed", cycle=cycle, error=str(e))

            # Wait for next cycle (interruptible)
            if self._is_running and not self._shutdown_event.is_set():
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=interval)
                    break  # Shutdown requested
                except asyncio.TimeoutError:
                    pass  # Normal timeout, continue
                except asyncio.CancelledError:
                    break

        self._logger.info("run_forever_stopped", total_cycles=cycle)

    # -------------------------------------------------------------------------
    # State Persistence
    # -------------------------------------------------------------------------

    async def _load_state(self) -> None:
        """Load state from database."""
        try:
            row = await self._pool.fetchrow(
                "SELECT state FROM service_state WHERE service_name = $1",
                self.SERVICE_NAME,
                timeout=30.0,
            )

            if row and row["state"]:
                state_data = row["state"]
                if isinstance(state_data, str):
                    state_data = json.loads(state_data)
                self._state = self._state_from_dict(state_data)
                self._logger.debug("state_loaded", state=self._state_to_dict())
            else:
                self._state = self._create_default_state()

        except Exception as e:
            self._logger.warning("state_load_failed", error=str(e))
            self._state = self._create_default_state()

    async def _save_state(self) -> None:
        """Save state to database."""
        try:
            state_json = json.dumps(self._state_to_dict())
            await self._pool.execute(
                """
                INSERT INTO service_state (service_name, state, updated_at)
                VALUES ($1, $2::jsonb, $3)
                ON CONFLICT (service_name) DO UPDATE SET state = $2::jsonb, updated_at = $3
                """,
                self.SERVICE_NAME,
                state_json,
                int(time.time()),
                timeout=30.0,
            )
        except Exception as e:
            self._logger.warning("state_save_failed", error=str(e))

    def _state_to_dict(self) -> dict[str, Any]:
        """Convert state to dictionary."""
        if hasattr(self._state, "to_dict"):
            return self._state.to_dict()
        return {}

    # -------------------------------------------------------------------------
    # Factory Methods
    # -------------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, config_path: str, brotr: Brotr, **kwargs: Any) -> "BaseService":
        """
        Create service from YAML configuration file.

        Args:
            config_path: Path to YAML config file
            brotr: Brotr instance for database operations
            **kwargs: Additional arguments passed to from_dict()

        Returns:
            Service instance
        """
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        return cls.from_dict(data, brotr=brotr, **kwargs)

    @classmethod
    def from_dict(cls, data: dict[str, Any], brotr: Brotr, **kwargs: Any) -> "BaseService":
        """
        Create service from dictionary configuration.

        If the subclass defines CONFIG_CLASS, the config is parsed automatically.
        Otherwise, subclasses should override this method.

        Args:
            data: Configuration dictionary
            brotr: Brotr instance for database operations
            **kwargs: Additional arguments passed to __init__

        Returns:
            Service instance
        """
        config = None
        if cls.CONFIG_CLASS is not None:
            config = cls.CONFIG_CLASS(**data)
        return cls(brotr=brotr, config=config, **kwargs)

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------

    @property
    def config(self) -> Optional[BaseModel]:
        """Get configuration."""
        return self._config

    @property
    def state(self) -> StateT:
        """Get current state."""
        return self._state

    @property
    def logger(self) -> Logger:
        """Get logger instance."""
        return self._logger

    # -------------------------------------------------------------------------
    # Context Manager Support
    # -------------------------------------------------------------------------

    async def __aenter__(self) -> "BaseService":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.stop()

    def __repr__(self) -> str:
        """String representation."""
        return f"{self.__class__.__name__}(running={self._is_running})"