"""
Structured Logging Module for BigBrotr.

Provides consistent JSON-formatted logging across all components.

Features:
- JSON-formatted structured logging
- Contextual fields (component, service_name)
- Request/trace ID support for distributed tracing
- Configurable log levels and output

Usage:
    from core.logger import get_logger, configure_logging

    # Configure once at startup
    configure_logging(level="INFO")

    # Get logger for any component
    logger = get_logger("pool", component="Pool")
    logger.info("connected", host="localhost", port=5432)

    # Output: {"timestamp": "...", "level": "INFO", "message": "connected",
    #          "component": "Pool", "name": "pool", "host": "localhost", "port": 5432}
"""

import contextvars
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Valid log levels
VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

# Context variables for distributed tracing
request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_id", default=None
)
trace_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "trace_id", default=None
)


def validate_log_level(level: str) -> str:
    """
    Validate and normalize a log level string.

    Args:
        level: Log level string (case-insensitive)

    Returns:
        Uppercase log level string

    Raises:
        ValueError: If log level is not valid
    """
    level_upper = level.upper()
    if level_upper not in VALID_LOG_LEVELS:
        raise ValueError(f"Invalid log level: {level}. Must be one of {VALID_LOG_LEVELS}")
    return level_upper


# ============================================================================
# JSON Formatter
# ============================================================================


class JsonFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.

    Converts log records to JSON format with:
    - timestamp: ISO 8601 format
    - level: Log level name
    - message: Log message
    - name: Logger name
    - All extra fields passed via logger methods
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "name": record.name,
        }

        # Add trace context if available
        if request_id := request_id_var.get():
            log_data["request_id"] = request_id
        if trace_id := trace_id_var.get():
            log_data["trace_id"] = trace_id

        # Add extra fields (skip standard LogRecord attributes)
        skip_fields = {
            "name", "msg", "args", "created", "filename", "funcName",
            "levelname", "levelno", "lineno", "module", "msecs", "message",
            "pathname", "process", "processName", "relativeCreated",
            "thread", "threadName", "exc_info", "exc_text", "stack_info", "taskName",
        }
        for key, value in record.__dict__.items():
            if key not in skip_fields:
                log_data[key] = value

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str)


# ============================================================================
# Logger Class
# ============================================================================


class Logger:
    """
    Structured logger with contextual fields.

    Wraps Python's logging.Logger to add structured context to all messages.

    Example:
        logger = Logger("pool", component="Pool")
        logger.info("connected", host="localhost")
        # Logs: {"name": "pool", "component": "Pool", "message": "connected", "host": "localhost"}
    """

    def __init__(
        self,
        name: str,
        component: Optional[str] = None,
        extra_context: Optional[dict[str, Any]] = None,
    ):
        """
        Initialize logger.

        Args:
            name: Logger name (typically service/module name)
            component: Component type (e.g., "Pool", "Brotr", "Finder")
            extra_context: Additional context fields for all log messages
        """
        self._name = name
        self._component = component
        self._logger = logging.getLogger(name)
        self._extra_context = extra_context or {}

    def _build_extra(self, **kwargs) -> dict[str, Any]:
        """Build extra fields for log record."""
        extra = {}
        if self._component:
            extra["component"] = self._component
        extra.update(self._extra_context)
        extra.update(kwargs)
        return extra

    def debug(self, message: str, **kwargs) -> None:
        """Log debug message."""
        self._logger.debug(message, extra=self._build_extra(**kwargs))

    def info(self, message: str, **kwargs) -> None:
        """Log info message."""
        self._logger.info(message, extra=self._build_extra(**kwargs))

    def warning(self, message: str, **kwargs) -> None:
        """Log warning message."""
        self._logger.warning(message, extra=self._build_extra(**kwargs))

    def error(self, message: str, **kwargs) -> None:
        """Log error message."""
        self._logger.error(message, extra=self._build_extra(**kwargs))

    def critical(self, message: str, **kwargs) -> None:
        """Log critical message."""
        self._logger.critical(message, extra=self._build_extra(**kwargs))

    def exception(self, message: str, **kwargs) -> None:
        """Log exception with traceback."""
        self._logger.exception(message, extra=self._build_extra(**kwargs))

    def bind(self, **kwargs) -> "Logger":
        """
        Create a new logger with additional context.

        Args:
            **kwargs: Additional context to bind

        Returns:
            New Logger instance with updated context
        """
        new_context = {**self._extra_context, **kwargs}
        return Logger(
            name=self._name,
            component=self._component,
            extra_context=new_context,
        )

    def set_level(self, level: str) -> None:
        """Set log level for this logger."""
        self._logger.setLevel(getattr(logging, validate_log_level(level)))


# ============================================================================
# Configuration Functions
# ============================================================================


def configure_logging(
    level: str = "INFO",
    output_file: Optional[str] = None,
    console_output: bool = True,
    json_format: bool = True,
) -> None:
    """
    Configure logging for the application.

    Call once at application startup.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        output_file: Optional path to log file
        console_output: Enable console output (default: True)
        json_format: Use JSON format (default: True)
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, validate_log_level(level)))
    root_logger.handlers.clear()

    # Create formatter
    if json_format:
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    # Console handler
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # File handler
    if output_file:
        log_path = Path(output_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(output_file)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def get_logger(
    name: str,
    component: Optional[str] = None,
    **extra_context,
) -> Logger:
    """
    Get a structured logger.

    Args:
        name: Logger name (typically service/module name)
        component: Component type (e.g., "Pool", "Brotr")
        **extra_context: Additional context fields

    Returns:
        Logger instance

    Example:
        logger = get_logger("finder", component="Finder")
        logger.info("discovery_started", cycle=1)
    """
    return Logger(name=name, component=component, extra_context=extra_context or None)


# ============================================================================
# Trace Context Functions
# ============================================================================


def set_request_id(request_id: str) -> None:
    """Set request ID for current context."""
    request_id_var.set(request_id)


def get_request_id() -> Optional[str]:
    """Get request ID from current context."""
    return request_id_var.get()


def set_trace_id(trace_id: str) -> None:
    """Set trace ID for current context."""
    trace_id_var.set(trace_id)


def get_trace_id() -> Optional[str]:
    """Get trace ID from current context."""
    return trace_id_var.get()


def clear_trace_context() -> None:
    """Clear all trace context variables."""
    request_id_var.set(None)
    trace_id_var.set(None)


# ============================================================================
# Backwards Compatibility (deprecated, will be removed)
# ============================================================================


def get_service_logger(
    service_name: str,
    service_type: str,
    extra_context: Optional[dict[str, Any]] = None,
) -> Logger:
    """
    DEPRECATED: Use get_logger() instead.

    This function is kept for backwards compatibility during migration.
    """
    return Logger(
        name=service_name,
        component=service_type,
        extra_context=extra_context,
    )


# Alias for backwards compatibility
ServiceLogger = Logger