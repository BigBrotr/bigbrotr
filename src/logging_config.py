"""Structured logging configuration for Bigbrotr using structlog."""
import logging
import sys
from typing import Any, Dict
import structlog


def setup_logging(
    service_name: str,
    log_level: str = "INFO",
    json_output: bool = False,
) -> None:
    """Configure structured logging for a Bigbrotr service.

    Args:
        service_name: Name of the service (e.g., "monitor", "synchronizer")
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_output: If True, output JSON format; otherwise human-readable

    Example:
        >>> setup_logging("monitor", log_level="DEBUG", json_output=False)
    """
    # Convert string log level to logging constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure structlog processors
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # Add appropriate renderer based on output format
    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(
            structlog.dev.ConsoleRenderer(
                colors=sys.stdout.isatty(),
                exception_formatter=structlog.dev.plain_traceback,
            )
        )

    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
    )

    # Set log level for third-party libraries
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    # Get logger and log initialization
    logger = structlog.get_logger(service_name)
    logger.info(
        "logging_configured",
        service=service_name,
        level=log_level,
        json_output=json_output,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a configured logger instance.

    Args:
        name: Logger name (typically module name)

    Returns:
        Configured structlog BoundLogger

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("event_processed", event_id="abc123", relay="wss://relay.example.com")
    """
    return structlog.get_logger(name)


def add_context(**kwargs: Any) -> None:
    """Add context variables to all subsequent log messages in this context.

    Args:
        **kwargs: Key-value pairs to add to logging context

    Example:
        >>> add_context(relay_url="wss://relay.example.com", worker_id=1)
        >>> logger.info("processing_started")  # Will include relay_url and worker_id
    """
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear all context variables."""
    structlog.contextvars.clear_contextvars()


class LoggerAdapter:
    """Adapter to use structlog with legacy logging.Logger interface.

    This allows gradual migration from stdlib logging to structlog.

    Example:
        >>> old_logger = LoggerAdapter("my_service")
        >>> old_logger.info("Message here", extra={"key": "value"})
    """

    def __init__(self, name: str):
        """Initialize adapter with logger name."""
        self.logger = get_logger(name)
        self.name = name

    def _log(self, level: str, msg: str, *args, **kwargs):
        """Internal log method."""
        # Extract 'extra' dict if present (stdlib logging pattern)
        extra = kwargs.pop("extra", {})
        exc_info = kwargs.pop("exc_info", None)

        # Merge args, kwargs, and extra into event dict
        event_dict: Dict[str, Any] = {"message": msg}
        if extra:
            event_dict.update(extra)
        if kwargs:
            event_dict.update(kwargs)

        # Get the appropriate log method
        log_method = getattr(self.logger, level)

        # Call with exception info if present
        if exc_info:
            log_method(exc_info=exc_info, **event_dict)
        else:
            log_method(**event_dict)

    def debug(self, msg: str, *args, **kwargs):
        """Log debug message."""
        self._log("debug", msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        """Log info message."""
        self._log("info", msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        """Log warning message."""
        self._log("warning", msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        """Log error message."""
        self._log("error", msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs):
        """Log critical message."""
        self._log("critical", msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        """Log exception with traceback."""
        kwargs["exc_info"] = True
        self._log("error", msg, *args, **kwargs)


# Example usage patterns
if __name__ == "__main__":
    # Setup logging for the service
    setup_logging("example_service", log_level="DEBUG", json_output=False)

    # Get a logger
    logger = get_logger(__name__)

    # Basic logging
    logger.info("service_started", version="1.0.0")

    # Logging with context
    add_context(relay_url="wss://relay.example.com", worker_id=1)
    logger.info("relay_connected", rtt_ms=150)
    logger.debug("event_received", event_id="abc123", kind=1)

    # Error logging
    try:
        raise ValueError("Example error")
    except Exception:
        logger.exception("processing_failed", event_id="xyz789")

    # Clear context
    clear_context()
    logger.info("context_cleared")

    # Using adapter for legacy code
    old_logger = LoggerAdapter("legacy_module")
    old_logger.info("Legacy log message", extra={"key": "value"})
