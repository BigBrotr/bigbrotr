"""
Structured Logging for BigBrotr.

Supports two output formats:
- Key-value pairs (default): message key1=value1 key2="value with spaces"
- JSON (for cloud/production): {"message": "...", "key1": "value1", ...}

Usage:
    from core.logger import Logger

    logger = Logger("finder")
    logger.info("started", cycle=1, count=42)

    # JSON output for production
    json_logger = Logger("finder", json_output=True)
    json_logger.info("started", cycle=1)  # {"message": "started", "cycle": 1}
"""

import json
import logging
from typing import Any


class Logger:
    """
    Logger wrapper that supports keyword arguments as extra fields.

    Features:
    - Automatic value escaping for key=value format
    - Optional JSON output for structured logging systems
    - Values with spaces, equals signs, or quotes are automatically quoted

    Example:
        logger = Logger("finder")
        logger.info("cycle_completed", cycle=1, duration=2.5)
        # Output: cycle_completed cycle=1 duration=2.5

        logger.info("error", message="hello world", path="/my path/file")
        # Output: error message="hello world" path="/my path/file"
    """

    def __init__(self, name: str, json_output: bool = False) -> None:
        """
        Initialize logger.

        Args:
            name: Logger name (typically service/module name)
            json_output: If True, output JSON instead of key=value format
        """
        self._logger = logging.getLogger(name)
        self._json_output = json_output

    def _format_value(self, value: Any) -> str:
        """Format a single value, quoting if necessary."""
        s = str(value)
        # Quote if contains spaces, equals, quotes, or is empty
        if not s or " " in s or "=" in s or '"' in s or "'" in s:
            # Escape internal quotes
            escaped = s.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        return s

    def _format_message(self, msg: str, kwargs: dict[str, Any]) -> str:
        """Format message with kwargs in appropriate format."""
        if self._json_output:
            return json.dumps({"message": msg, **kwargs}, default=str)

        if not kwargs:
            return msg

        pairs = " ".join(f"{k}={self._format_value(v)}" for k, v in kwargs.items())
        return f"{msg} {pairs}"

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._logger.debug(self._format_message(msg, kwargs))

    def info(self, msg: str, **kwargs: Any) -> None:
        self._logger.info(self._format_message(msg, kwargs))

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._logger.warning(self._format_message(msg, kwargs))

    def error(self, msg: str, **kwargs: Any) -> None:
        self._logger.error(self._format_message(msg, kwargs))

    def critical(self, msg: str, **kwargs: Any) -> None:
        self._logger.critical(self._format_message(msg, kwargs))

    def exception(self, msg: str, **kwargs: Any) -> None:
        self._logger.exception(self._format_message(msg, kwargs))
