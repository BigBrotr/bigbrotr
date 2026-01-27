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
from typing import Any, ClassVar


def format_kv_pairs(
    kwargs: dict[str, Any],
    max_value_length: int | None = 1000,
    prefix: str = " ",
) -> str:
    """Format kwargs as key=value pairs with proper escaping.

    Shared utility for consistent formatting across Logger and worker processes.

    Args:
        kwargs: Key-value pairs to format
        max_value_length: Max chars per value (None = no limit)
        prefix: String to prepend (default: single space)

    Returns:
        Formatted string like " key1=value1 key2=\"value with spaces\""
    """
    if not kwargs:
        return ""

    parts = []
    for k, v in kwargs.items():
        s = str(v)
        # Truncate if needed
        if max_value_length and len(s) > max_value_length:
            s = s[:max_value_length] + f"...<truncated {len(s) - max_value_length} chars>"
        # Quote if contains special chars
        if not s or " " in s or "=" in s or '"' in s or "'" in s:
            escaped = s.replace("\\", "\\\\").replace('"', '\\"')
            parts.append(f'{k}="{escaped}"')
        else:
            parts.append(f"{k}={s}")

    return prefix + " ".join(parts) if parts else ""


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

    _DEFAULT_MAX_VALUE_LENGTH: ClassVar[int] = 1000

    def __init__(
        self,
        name: str,
        json_output: bool = False,
        max_value_length: int | None = None,
    ) -> None:
        """
        Initialize logger.

        Args:
            name: Logger name (typically service/module name)
            json_output: If True, output JSON instead of key=value format
            max_value_length: Maximum length for logged values (default: 1000)
        """
        if max_value_length is None:
            max_value_length = self._DEFAULT_MAX_VALUE_LENGTH
        self._logger = logging.getLogger(name)
        self._json_output = json_output
        self._max_value_length = max_value_length

    def _format_message(self, msg: str, kwargs: dict[str, Any]) -> str:
        """Format message with kwargs in appropriate format."""
        if self._json_output:
            return json.dumps({"message": msg, **kwargs}, default=str)
        return msg + format_kv_pairs(kwargs, max_value_length=self._max_value_length)

    def debug(self, msg: str, **kwargs: Any) -> None:
        """Log a DEBUG level message with optional key=value pairs."""
        self._logger.debug(self._format_message(msg, kwargs))

    def info(self, msg: str, **kwargs: Any) -> None:
        """Log an INFO level message with optional key=value pairs."""
        self._logger.info(self._format_message(msg, kwargs))

    def warning(self, msg: str, **kwargs: Any) -> None:
        """Log a WARNING level message with optional key=value pairs."""
        self._logger.warning(self._format_message(msg, kwargs))

    def error(self, msg: str, **kwargs: Any) -> None:
        """Log an ERROR level message with optional key=value pairs."""
        self._logger.error(self._format_message(msg, kwargs))

    def critical(self, msg: str, **kwargs: Any) -> None:
        """Log a CRITICAL level message with optional key=value pairs."""
        self._logger.critical(self._format_message(msg, kwargs))

    def exception(self, msg: str, **kwargs: Any) -> None:
        """Log an ERROR level message with exception traceback and optional key=value pairs."""
        self._logger.exception(self._format_message(msg, kwargs))
