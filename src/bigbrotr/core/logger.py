"""
Structured logging with key=value and JSON output support.

Wraps the standard library ``logging`` module to provide structured output
in two formats: human-readable key=value pairs (default) and machine-parseable
JSON for production/cloud environments.

Values containing spaces, equals signs, or quotes are automatically escaped
and wrapped in double quotes. Long values are truncated to a configurable
maximum length.

The ``StructuredFormatter`` is a stdlib ``logging.Formatter`` that reads
structured data from the ``structured_kv`` extra field (attached by Logger)
and appends it as key=value pairs. When installed on the root handler, it
unifies output from both ``Logger`` and plain ``logging.getLogger()`` calls
used in the models and utils layers.

Examples:
    ```python
    from core.logger import Logger

    logger = Logger("finder")
    logger.info("started", cycle=1, count=42)
    # Output: started cycle=1 count=42

    json_logger = Logger("finder", json_output=True)
    json_logger.info("started", cycle=1)
    # Output: {"message": "started", "cycle": 1}
    ```
"""

import datetime
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


class StructuredFormatter(logging.Formatter):
    """Formats all log records as structured key=value output.

    Reads structured data from the ``structured_kv`` extra field
    (attached by Logger) and appends it as key=value pairs.  When no
    ``structured_kv`` is present (e.g. plain ``logging.getLogger()``
    calls from models/utils), the message is emitted as-is with the
    same ``level name message`` prefix for consistency.
    """

    def format(self, record: logging.LogRecord) -> str:
        base = f"{record.levelname.lower()} {record.name} {record.getMessage()}"
        extra: dict[str, Any] = getattr(record, "structured_kv", {})
        if extra:
            base += format_kv_pairs(extra)
        return base


class Logger:
    """Structured logger that appends keyword arguments as extra fields.

    Wraps a standard ``logging.Logger`` and formats keyword arguments as either
    key=value pairs or JSON, depending on configuration. All public methods
    mirror the standard logging API with an added ``**kwargs`` parameter.

    Examples:
        ```python
        logger = Logger("finder")
        logger.info("cycle_completed", cycle=1, duration=2.5)
        # Output: cycle_completed cycle=1 duration=2.5

        logger.info("relay_found", url="wss://relay.example.com")
        # Output: relay_found url=wss://relay.example.com
        ```
    """

    _DEFAULT_MAX_VALUE_LENGTH: ClassVar[int] = 1000

    def __init__(
        self,
        name: str,
        *,
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

    def _format_json(self, msg: str, level: str, kwargs: dict[str, Any]) -> str:
        """Format message and kwargs as a JSON string for cloud logging.

        Includes standard fields expected by log aggregators:
        ``timestamp`` (ISO 8601), ``level``, ``service`` (logger name).
        """
        record = {
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "level": level,
            "service": self._logger.name,
            "message": msg,
            **kwargs,
        }
        return json.dumps(record, default=str)

    def _make_extra(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Build the ``extra`` dict for structured log records.

        Applies ``max_value_length`` truncation so the StructuredFormatter
        receives pre-truncated values.
        """
        if not kwargs:
            return {}
        # Pre-truncate values so the formatter receives clean data
        truncated: dict[str, Any] = {}
        for k, v in kwargs.items():
            s = str(v)
            if self._max_value_length and len(s) > self._max_value_length:
                truncated[k] = (
                    s[: self._max_value_length]
                    + f"...<truncated {len(s) - self._max_value_length} chars>"
                )
            else:
                truncated[k] = v
        return {"structured_kv": truncated}

    def debug(self, msg: str, **kwargs: Any) -> None:
        """Log a DEBUG level message with optional key=value pairs."""
        if self._json_output:
            self._logger.debug(self._format_json(msg, "debug", kwargs))
        else:
            self._logger.debug(msg, extra=self._make_extra(kwargs))

    def info(self, msg: str, **kwargs: Any) -> None:
        """Log an INFO level message with optional key=value pairs."""
        if self._json_output:
            self._logger.info(self._format_json(msg, "info", kwargs))
        else:
            self._logger.info(msg, extra=self._make_extra(kwargs))

    def warning(self, msg: str, **kwargs: Any) -> None:
        """Log a WARNING level message with optional key=value pairs."""
        if self._json_output:
            self._logger.warning(self._format_json(msg, "warning", kwargs))
        else:
            self._logger.warning(msg, extra=self._make_extra(kwargs))

    def error(self, msg: str, **kwargs: Any) -> None:
        """Log an ERROR level message with optional key=value pairs."""
        if self._json_output:
            self._logger.error(self._format_json(msg, "error", kwargs))
        else:
            self._logger.error(msg, extra=self._make_extra(kwargs))

    def critical(self, msg: str, **kwargs: Any) -> None:
        """Log a CRITICAL level message with optional key=value pairs."""
        if self._json_output:
            self._logger.critical(self._format_json(msg, "critical", kwargs))
        else:
            self._logger.critical(msg, extra=self._make_extra(kwargs))

    def exception(self, msg: str, **kwargs: Any) -> None:
        """Log an ERROR level message with exception traceback and optional key=value pairs."""
        if self._json_output:
            self._logger.exception(self._format_json(msg, "error", kwargs))
        else:
            self._logger.exception(msg, extra=self._make_extra(kwargs))
