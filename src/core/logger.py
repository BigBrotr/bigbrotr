"""
Structured Logging for BigBrotr.

Usage:
    from core.logger import Logger

    logger = Logger("finder")
    logger.info("started", cycle=1, count=42)
"""

import logging
from typing import Any


class Logger:
    """
    Logger wrapper that supports keyword arguments as extra fields.

    Example:
        logger = Logger("finder")
        logger.info("cycle_completed", cycle=1, duration=2.5)
        # Output: 2025-01-01 12:00:00 INFO finder: cycle_completed cycle=1 duration=2.5
    """

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def _format_kwargs(self, kwargs: dict[str, Any]) -> str:
        """Format kwargs as key=value pairs."""
        if not kwargs:
            return ""
        pairs = " ".join(f"{k}={v}" for k, v in kwargs.items())
        return f" {pairs}"

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._logger.debug(f"{msg}{self._format_kwargs(kwargs)}")

    def info(self, msg: str, **kwargs: Any) -> None:
        self._logger.info(f"{msg}{self._format_kwargs(kwargs)}")

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._logger.warning(f"{msg}{self._format_kwargs(kwargs)}")

    def error(self, msg: str, **kwargs: Any) -> None:
        self._logger.error(f"{msg}{self._format_kwargs(kwargs)}")

    def exception(self, msg: str, **kwargs: Any) -> None:
        self._logger.exception(f"{msg}{self._format_kwargs(kwargs)}")
