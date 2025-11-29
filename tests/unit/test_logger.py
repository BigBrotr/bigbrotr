"""
Unit tests for Logger module.
"""

import json
import logging

from core.logger import (
    JsonFormatter,
    Logger,
    configure_logging,
    get_logger,
    get_request_id,
    get_trace_id,
    set_request_id,
    set_trace_id,
)


class TestJsonFormatter:
    """Tests for JsonFormatter."""

    def test_format_basic_message(self) -> None:
        """Test formatting a basic log message."""
        formatter = JsonFormatter()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert data["message"] == "Test message"
        assert data["level"] == "INFO"
        assert "timestamp" in data

    def test_format_with_extra_fields(self) -> None:
        """Test formatting with extra fields."""
        formatter = JsonFormatter()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.custom_field = "custom_value"
        record.numeric_field = 42

        output = formatter.format(record)
        data = json.loads(output)

        assert data["custom_field"] == "custom_value"
        assert data["numeric_field"] == 42

    def test_format_with_exception(self) -> None:
        """Test formatting with exception info."""
        formatter = JsonFormatter()

        try:
            raise ValueError("Test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert "exception" in data
        assert "ValueError" in data["exception"]
        assert "Test error" in data["exception"]


class TestLogger:
    """Tests for Logger class."""

    def test_init(self) -> None:
        """Test Logger initialization."""
        logger = Logger("test_service", component="TestClass")

        assert logger._name == "test_service"
        assert logger._component == "TestClass"

    def test_build_extra(self) -> None:
        """Test building extra fields."""
        logger = Logger("test_service", component="TestClass")

        extra = logger._build_extra(custom_field="value")

        assert extra["component"] == "TestClass"
        assert extra["custom_field"] == "value"

    def test_bind_creates_new_logger(self) -> None:
        """Test bind creates new logger with context."""
        logger = Logger("test_service", component="TestClass")
        bound_logger = logger.bind(request_id="123")

        assert bound_logger is not logger
        assert bound_logger._extra_context["request_id"] == "123"

    def test_bind_preserves_existing_context(self) -> None:
        """Test bind preserves existing context."""
        logger = Logger(
            "test_service", component="TestClass", extra_context={"env": "test"}
        )
        bound_logger = logger.bind(request_id="123")

        assert bound_logger._extra_context["env"] == "test"
        assert bound_logger._extra_context["request_id"] == "123"

    def test_log_methods_exist(self) -> None:
        """Test all log methods exist."""
        logger = Logger("test", component="Test")

        assert hasattr(logger, "debug")
        assert hasattr(logger, "info")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "error")
        assert hasattr(logger, "critical")
        assert hasattr(logger, "exception")


class TestConfigureLogging:
    """Tests for configure_logging function."""

    def test_configure_logging_defaults(self) -> None:
        """Test configure_logging with defaults."""
        configure_logging()

        root_logger = logging.getLogger()
        assert root_logger.level == logging.INFO

    def test_configure_logging_debug(self) -> None:
        """Test configure_logging with DEBUG level."""
        configure_logging(level="DEBUG")

        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG

    def test_configure_logging_json(self) -> None:
        """Test configure_logging with JSON format."""
        configure_logging(json_format=True, console_output=True)

        root_logger = logging.getLogger()
        # Check that a handler with JsonFormatter is attached
        has_json = any(
            isinstance(h.formatter, JsonFormatter)
            for h in root_logger.handlers
        )
        assert has_json

    def test_configure_logging_plain(self) -> None:
        """Test configure_logging with plain format."""
        configure_logging(json_format=False, console_output=True)

        root_logger = logging.getLogger()
        # Check that handlers exist
        assert len(root_logger.handlers) > 0


class TestGetLogger:
    """Tests for get_logger function."""

    def test_get_logger(self) -> None:
        """Test getting a logger."""
        logger = get_logger("my_service", component="MyClass")

        assert isinstance(logger, Logger)
        assert logger._name == "my_service"
        assert logger._component == "MyClass"

    def test_get_logger_with_context(self) -> None:
        """Test getting a logger with extra context."""
        logger = get_logger("my_service", component="MyClass", env="production")

        assert logger._extra_context["env"] == "production"


class TestTraceContext:
    """Tests for trace context functions."""

    def test_set_and_get_request_id(self) -> None:
        """Test setting and getting request ID."""
        set_request_id("req-123")
        assert get_request_id() == "req-123"

    def test_set_and_get_trace_id(self) -> None:
        """Test setting and getting trace ID."""
        set_trace_id("trace-456")
        assert get_trace_id() == "trace-456"