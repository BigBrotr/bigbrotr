"""
Structured Logging Module

This module provides structured logging capabilities for BigBrotr services.
Uses Python's standard logging with JSON formatting for production-ready
structured logs.

Features:
- JSON-formatted structured logging
- Contextual fields (service_name, service_type, etc.)
- Request ID and trace ID support
- Configurable log levels
- Console and file output support
- Integration with Service wrapper

Example usage:
    from core.logger import get_service_logger, configure_logging

    # Configure logging once at application startup
    configure_logging(level="INFO", output_file="logs/app.log")

    # Get logger for a service
    logger = get_service_logger("database_pool", "ConnectionPool")

    # Log with structured fields
    logger.info("service_started", elapsed_seconds=1.23, config={"max_size": 20})

    # Log with additional context
    logger.error("connection_failed", error=str(e), retry_attempt=3)
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


# ============================================================================
# Structured Formatter
# ============================================================================


class StructuredFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.

    Converts log records to JSON format with structured fields:
    - timestamp: ISO 8601 timestamp
    - level: Log level (INFO, WARNING, ERROR, etc.)
    - message: Log message
    - service_name: Name of the service (if provided)
    - service_type: Type of service (if provided)
    - **extra: Any additional fields passed to logger
    """

    def __init__(
        self,
        include_timestamp: bool = True,
        include_level: bool = True,
        include_logger_name: bool = False,
        datetime_format: str = "iso",
    ):
        """
        Initialize structured formatter.

        Args:
            include_timestamp: Include timestamp in output
            include_level: Include log level in output
            include_logger_name: Include Python logger name
            datetime_format: 'iso' for ISO 8601, 'unix' for Unix timestamp
        """
        super().__init__()
        self.include_timestamp = include_timestamp
        self.include_level = include_level
        self.include_logger_name = include_logger_name
        self.datetime_format = datetime_format

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.

        Args:
            record: Log record to format

        Returns:
            JSON-formatted log string
        """
        log_data: Dict[str, Any] = {}

        # Timestamp
        if self.include_timestamp:
            if self.datetime_format == "iso":
                log_data["timestamp"] = datetime.fromtimestamp(record.created).isoformat()
            else:  # unix
                log_data["timestamp"] = record.created

        # Level
        if self.include_level:
            log_data["level"] = record.levelname

        # Logger name (optional)
        if self.include_logger_name:
            log_data["logger"] = record.name

        # Message
        log_data["message"] = record.getMessage()

        # Add all extra fields from record
        # These come from logger.info("msg", extra={...})
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "message", "pathname", "process", "processName",
                "relativeCreated", "thread", "threadName", "exc_info",
                "exc_text", "stack_info", "taskName"
            }:
                log_data[key] = value

        # Exception info
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str)


# ============================================================================
# Service Logger
# ============================================================================


class ServiceLogger:
    """
    Structured logger for services with contextual fields.

    This wrapper adds service-specific context to all log messages:
    - service_name: Name of the service instance
    - service_type: Type/class of the service

    Example:
        logger = ServiceLogger("database_pool", "ConnectionPool")
        logger.info("connected", host="localhost", port=5432)
        # Output: {"timestamp": "...", "level": "INFO", "message": "connected",
        #          "service_name": "database_pool", "service_type": "ConnectionPool",
        #          "host": "localhost", "port": 5432}
    """

    def __init__(
        self,
        service_name: str,
        service_type: str,
        logger: Optional[logging.Logger] = None,
        extra_context: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize service logger.

        Args:
            service_name: Name of the service instance
            service_type: Type/class of the service
            logger: Python logger instance (creates one if None)
            extra_context: Additional context fields to include in all logs
        """
        self._service_name = service_name
        self._service_type = service_type
        self._logger = logger or logging.getLogger(f"service.{service_name}")
        self._extra_context = extra_context or {}

    def _build_extra(self, **kwargs) -> Dict[str, Any]:
        """
        Build extra fields for log record.

        Combines service context with additional kwargs.
        """
        extra = {
            "service_name": self._service_name,
            "service_type": self._service_type,
        }
        extra.update(self._extra_context)
        extra.update(kwargs)
        return extra

    def debug(self, message: str, **kwargs):
        """Log debug message with structured fields."""
        self._logger.debug(message, extra=self._build_extra(**kwargs))

    def info(self, message: str, **kwargs):
        """Log info message with structured fields."""
        self._logger.info(message, extra=self._build_extra(**kwargs))

    def warning(self, message: str, **kwargs):
        """Log warning message with structured fields."""
        self._logger.warning(message, extra=self._build_extra(**kwargs))

    def error(self, message: str, **kwargs):
        """Log error message with structured fields."""
        self._logger.error(message, extra=self._build_extra(**kwargs))

    def critical(self, message: str, **kwargs):
        """Log critical message with structured fields."""
        self._logger.critical(message, extra=self._build_extra(**kwargs))

    def exception(self, message: str, **kwargs):
        """Log exception with traceback and structured fields."""
        self._logger.exception(message, extra=self._build_extra(**kwargs))

    def bind(self, **kwargs) -> "ServiceLogger":
        """
        Create a new logger with additional context fields.

        Args:
            **kwargs: Additional context to bind

        Returns:
            New ServiceLogger instance with updated context

        Example:
            logger = ServiceLogger("pool", "ConnectionPool")
            request_logger = logger.bind(request_id="abc123")
            request_logger.info("query_executed")  # Includes request_id
        """
        new_context = {**self._extra_context, **kwargs}
        return ServiceLogger(
            service_name=self._service_name,
            service_type=self._service_type,
            logger=self._logger,
            extra_context=new_context,
        )


# ============================================================================
# Configuration Functions
# ============================================================================


def configure_logging(
    level: str = "INFO",
    output_file: Optional[str] = None,
    console_output: bool = True,
    structured: bool = True,
    datetime_format: str = "iso",
):
    """
    Configure logging for the application.

    Should be called once at application startup.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        output_file: Path to log file (None for no file output)
        console_output: Enable console output
        structured: Use structured JSON format (True) or plain text (False)
        datetime_format: 'iso' for ISO 8601, 'unix' for Unix timestamp

    Example:
        # Development: plain text to console
        configure_logging(level="DEBUG", structured=False)

        # Production: JSON to file and console
        configure_logging(
            level="INFO",
            output_file="logs/app.log",
            console_output=True,
            structured=True
        )
    """
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Remove existing handlers
    root_logger.handlers.clear()

    # Create formatter
    if structured:
        formatter = StructuredFormatter(datetime_format=datetime_format)
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
        # Create directory if needed
        log_path = Path(output_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(output_file)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def get_service_logger(
    service_name: str,
    service_type: str,
    extra_context: Optional[Dict[str, Any]] = None,
) -> ServiceLogger:
    """
    Get a structured logger for a service.

    Args:
        service_name: Name of the service instance
        service_type: Type/class of the service
        extra_context: Additional context fields

    Returns:
        ServiceLogger instance

    Example:
        logger = get_service_logger("database_pool", "ConnectionPool")
        logger.info("connected", host="localhost", port=5432)
    """
    return ServiceLogger(service_name, service_type, extra_context=extra_context)


def get_logger(name: str) -> logging.Logger:
    """
    Get a standard Python logger.

    Use this for non-service logging (utilities, scripts, etc.).

    Args:
        name: Logger name

    Returns:
        Python Logger instance
    """
    return logging.getLogger(name)


# ============================================================================
# Context Variables (for request/trace IDs)
# ============================================================================

try:
    import contextvars

    # Context variables for distributed tracing
    request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
        "request_id", default=None
    )
    trace_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
        "trace_id", default=None
    )

    def set_request_id(request_id: str):
        """Set request ID for current context."""
        request_id_var.set(request_id)

    def get_request_id() -> Optional[str]:
        """Get request ID from current context."""
        return request_id_var.get()

    def set_trace_id(trace_id: str):
        """Set trace ID for current context."""
        trace_id_var.set(trace_id)

    def get_trace_id() -> Optional[str]:
        """Get trace ID from current context."""
        return trace_id_var.get()

    def get_trace_context() -> Dict[str, Optional[str]]:
        """
        Get current trace context.

        Returns:
            Dictionary with request_id and trace_id
        """
        return {
            "request_id": get_request_id(),
            "trace_id": get_trace_id(),
        }

except ImportError:
    # contextvars not available (Python < 3.7)
    def set_request_id(request_id: str):
        pass

    def get_request_id() -> Optional[str]:
        return None

    def set_trace_id(trace_id: str):
        pass

    def get_trace_id() -> Optional[str]:
        return None

    def get_trace_context() -> Dict[str, Optional[str]]:
        return {"request_id": None, "trace_id": None}
