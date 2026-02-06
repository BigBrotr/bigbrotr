"""
Structured logging with key=value and JSON output support.

Wraps the standard library ``logging`` module to provide structured output
in two formats: human-readable key=value pairs (default) and machine-parseable
JSON for production/cloud environments.

Values containing spaces, equals signs, or quotes are automatically escaped
and wrapped in double quotes. Long values are truncated to a configurable
maximum length.

Example:
    from core.logger import Logger

    logger = Logger("finder")
    logger.info("started", cycle=1, count=42)
    # Output: started cycle=1 count=42

    json_logger = Logger("finder", json_output=True)
    json_logger.info("started", cycle=1)
    # Output: {"message": "started", "cycle": 1}
"""

import json
import logging
from typing import Any, ClassVar


def format_kv_pairs(
    kwargs: dict[str, Any],
    max_value_length: int | None = 1000,
    prefix: str = " ",
) -> str:
    """Format a dictionary as space-separated key=value pairs.

    Used by Logger and worker processes to produce consistent structured output.
    Values are truncated to ``max_value_length`` characters, and values containing
    whitespace, equals signs, or quotes are automatically escaped and quoted.

    Args:
        kwargs: Key-value pairs to format.
        max_value_length: Maximum characters per value before truncation.
            Pass None to disable truncation.
        prefix: String prepended to the output (default: single space).

    Returns:
        Formatted string, e.g. ' key1=value1 key2="value with spaces"'.
        Returns empty string if kwargs is empty.
    """
    if not kwargs:
        return ""

    parts = []
    for k, v in kwargs.items():
        s = str(v)
        if max_value_length and len(s) > max_value_length:
            s = s[:max_value_length] + f"...<truncated {len(s) - max_value_length} chars>"
        # Quote values containing whitespace or characters that would break parsing
        if not s or " " in s or "=" in s or '"' in s or "'" in s:
            escaped = s.replace("\\", "\\\\").replace('"', '\\"')
            parts.append(f'{k}="{escaped}"')
        else:
            parts.append(f"{k}={s}")

    return prefix + " ".join(parts) if parts else ""


class Logger:
    """Structured logger that appends keyword arguments as extra fields.

    Wraps a standard ``logging.Logger`` and formats keyword arguments as either
    key=value pairs or JSON, depending on configuration. All public methods
    mirror the standard logging API with an added ``**kwargs`` parameter.

    Example:
        logger = Logger("finder")
        logger.info("cycle_completed", cycle=1, duration=2.5)
        # Output: cycle_completed cycle=1 duration=2.5

        logger.info("relay_found", url="wss://relay.example.com")
        # Output: relay_found url=wss://relay.example.com
    """

    _DEFAULT_MAX_VALUE_LENGTH: ClassVar[int] = 1000

    def __init__(
        self,
        name: str,
        json_output: bool = False,
        max_value_length: int | None = None,
    ) -> None:
        """Initialize a structured logger.

        Args:
            name: Logger name, typically the service or module name.
                Maps to the underlying ``logging.getLogger(name)`` call.
            json_output: If True, emit JSON objects instead of key=value pairs.
            max_value_length: Maximum character length for individual values
                before truncation. Defaults to 1000.
        """
        if max_value_length is None:
            max_value_length = self._DEFAULT_MAX_VALUE_LENGTH
        self._logger = logging.getLogger(name)
        self._json_output = json_output
        self._max_value_length = max_value_length

    def _format_message(self, msg: str, kwargs: dict[str, Any]) -> str:
        """Format message with kwargs as key=value pairs or JSON."""
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
