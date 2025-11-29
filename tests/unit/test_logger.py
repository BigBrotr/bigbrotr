"""
Unit tests for Logger module.
"""

import json
import logging

from core.logger import (
    ServiceLogger,
    StructuredFormatter,
    configure_logging,
    get_logger,
    get_request_id,
    get_service_logger,
    get_trace_context,
    get_trace_id,
    set_request_id,
    set_trace_id,
)


class TestStructuredFormatter:
    """Tests for StructuredFormatter."""

    def test_format_basic_message(self) -> None:
        """Test formatting a basic log message."""
        formatter = StructuredFormatter()

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
        formatter = StructuredFormatter()

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

    def test_format_without_timestamp(self) -> None:
        """Test formatting without timestamp."""
        formatter = StructuredFormatter(include_timestamp=False)

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

        assert "timestamp" not in data

    def test_format_with_unix_timestamp(self) -> None:
        """Test formatting with Unix timestamp."""
        formatter = StructuredFormatter(datetime_format="unix")

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

        # Unix timestamp should be a number
        assert isinstance(data["timestamp"], float)

    def test_format_with_exception(self) -> None:
        """Test formatting with exception info."""
        formatter = StructuredFormatter()

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


class TestServiceLogger:
    """Tests for ServiceLogger."""

    def test_init(self) -> None:
        """Test ServiceLogger initialization."""
        logger = ServiceLogger("test_service", "TestClass")

        assert logger._service_name == "test_service"
        assert logger._service_type == "TestClass"

    def test_build_extra(self) -> None:
        """Test building extra fields."""
        logger = ServiceLogger("test_service", "TestClass")

        extra = logger._build_extra(custom_field="value")

        assert extra["service_name"] == "test_service"
        assert extra["service_type"] == "TestClass"
        assert extra["custom_field"] == "value"

    def test_bind_creates_new_logger(self) -> None:
        """Test bind creates new logger with context."""
        logger = ServiceLogger("test_service", "TestClass")
        bound_logger = logger.bind(request_id="123")

        assert bound_logger is not logger
        assert bound_logger._extra_context["request_id"] == "123"
        assert "request_id" not in logger._extra_context

    def test_bind_preserves_existing_context(self) -> None:
        """Test bind preserves existing context."""
        logger = ServiceLogger(
            "test_service", "TestClass", extra_context={"env": "test"}
        )
        bound_logger = logger.bind(request_id="123")

        assert bound_logger._extra_context["env"] == "test"
        assert bound_logger._extra_context["request_id"] == "123"

    def test_log_methods_exist(self) -> None:
        """Test all log methods exist."""
        logger = ServiceLogger("test", "Test")

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

    def test_configure_logging_structured(self) -> None:
        """Test configure_logging with structured format."""
        configure_logging(structured=True, console_output=True)

        root_logger = logging.getLogger()
        # Check that a handler with StructuredFormatter is attached
        has_structured = any(
            isinstance(h.formatter, StructuredFormatter)
            for h in root_logger.handlers
        )
        assert has_structured

    def test_configure_logging_plain(self) -> None:
        """Test configure_logging with plain format."""
        configure_logging(structured=False, console_output=True)

        root_logger = logging.getLogger()
        # Check that handlers exist
        assert len(root_logger.handlers) > 0


class TestGetServiceLogger:
    """Tests for get_service_logger function."""

    def test_get_service_logger(self) -> None:
        """Test getting a service logger."""
        logger = get_service_logger("my_service", "MyClass")

        assert isinstance(logger, ServiceLogger)
        assert logger._service_name == "my_service"
        assert logger._service_type == "MyClass"

    def test_get_service_logger_with_context(self) -> None:
        """Test getting a service logger with extra context."""
        logger = get_service_logger(
            "my_service", "MyClass", extra_context={"env": "production"}
        )

        assert logger._extra_context["env"] == "production"


class TestGetLogger:
    """Tests for get_logger function."""

    def test_get_logger(self) -> None:
        """Test getting a standard logger."""
        logger = get_logger("my_module")

        assert isinstance(logger, logging.Logger)
        assert logger.name == "my_module"


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

    def test_get_trace_context(self) -> None:
        """Test getting full trace context."""
        set_request_id("req-789")
        set_trace_id("trace-012")

        context = get_trace_context()

        assert context["request_id"] == "req-789"
        assert context["trace_id"] == "trace-012"
