"""
Unit tests for core.logger module.

Tests:
- Logger initialization
- Key-value formatting with escaping
- JSON output mode
- All log levels (debug, info, warning, error, critical, exception)
"""

import json
import logging
from unittest.mock import MagicMock

import pytest

from core.logger import Logger


class TestLoggerInit:
    """Test Logger initialization."""

    def test_init_creates_logger_with_name(self) -> None:
        """Logger should use provided name."""
        logger = Logger("test_service")
        assert logger._logger.name == "test_service"

    def test_init_default_not_json(self) -> None:
        """Logger should default to key-value format."""
        logger = Logger("test")
        assert logger._json_output is False

    def test_init_json_mode(self) -> None:
        """Logger should support JSON output mode."""
        logger = Logger("test", json_output=True)
        assert logger._json_output is True


class TestFormatValue:
    """Test value formatting and escaping."""

    def test_simple_value(self) -> None:
        """Simple values should not be quoted."""
        logger = Logger("test")
        assert logger._format_value("hello") == "hello"
        assert logger._format_value(123) == "123"
        assert logger._format_value(45.67) == "45.67"

    def test_value_with_spaces(self) -> None:
        """Values with spaces should be quoted."""
        logger = Logger("test")
        assert logger._format_value("hello world") == '"hello world"'

    def test_value_with_equals(self) -> None:
        """Values with equals sign should be quoted."""
        logger = Logger("test")
        assert logger._format_value("foo=bar") == '"foo=bar"'

    def test_value_with_double_quotes(self) -> None:
        """Values with double quotes should be escaped and quoted."""
        logger = Logger("test")
        result = logger._format_value('say "hello"')
        assert result == '"say \\"hello\\""'

    def test_value_with_single_quotes(self) -> None:
        """Values with single quotes should be quoted."""
        logger = Logger("test")
        assert logger._format_value("it's") == '"it\'s"'

    def test_empty_value(self) -> None:
        """Empty values should be quoted."""
        logger = Logger("test")
        assert logger._format_value("") == '""'

    def test_value_with_backslash(self) -> None:
        """Values with backslashes only are not quoted (no spaces/equals/quotes)."""
        logger = Logger("test")
        result = logger._format_value("path\\to\\file")
        # Backslashes alone don't trigger quoting - only spaces, equals, or quotes do
        assert result == "path\\to\\file"

    def test_value_with_backslash_and_spaces(self) -> None:
        """Values with backslashes and spaces should be quoted and escaped."""
        logger = Logger("test")
        result = logger._format_value("path\\to\\my file")
        assert result == '"path\\\\to\\\\my file"'


class TestFormatMessage:
    """Test message formatting."""

    def test_message_without_kwargs(self) -> None:
        """Message without kwargs should return message only."""
        logger = Logger("test")
        assert logger._format_message("test_msg", {}) == "test_msg"

    def test_message_with_kwargs(self) -> None:
        """Message with kwargs should format as key=value pairs."""
        logger = Logger("test")
        result = logger._format_message("test_msg", {"count": 42, "name": "test"})
        assert "test_msg" in result
        assert "count=42" in result
        assert "name=test" in result

    def test_json_format_without_kwargs(self) -> None:
        """JSON mode should output valid JSON."""
        logger = Logger("test", json_output=True)
        result = logger._format_message("test_msg", {})
        parsed = json.loads(result)
        assert parsed["message"] == "test_msg"

    def test_json_format_with_kwargs(self) -> None:
        """JSON mode should include kwargs in JSON."""
        logger = Logger("test", json_output=True)
        result = logger._format_message("test_msg", {"count": 42, "name": "test"})
        parsed = json.loads(result)
        assert parsed["message"] == "test_msg"
        assert parsed["count"] == 42
        assert parsed["name"] == "test"

    def test_json_format_complex_values(self) -> None:
        """JSON mode should handle complex values."""
        logger = Logger("test", json_output=True)
        result = logger._format_message("msg", {"data": {"nested": True}})
        parsed = json.loads(result)
        assert parsed["data"] == {"nested": True}


class TestLogLevels:
    """Test all log levels."""

    @pytest.fixture
    def mock_logger(self) -> tuple[Logger, MagicMock]:
        """Create logger with mocked internal logger."""
        logger = Logger("test")
        mock = MagicMock()
        logger._logger = mock
        return logger, mock

    def test_debug(self, mock_logger: tuple[Logger, MagicMock]) -> None:
        """Debug should call logger.debug."""
        logger, mock = mock_logger
        logger.debug("test_debug", count=1)
        mock.debug.assert_called_once()
        args = mock.debug.call_args[0][0]
        assert "test_debug" in args
        assert "count=1" in args

    def test_info(self, mock_logger: tuple[Logger, MagicMock]) -> None:
        """Info should call logger.info."""
        logger, mock = mock_logger
        logger.info("test_info", value="test")
        mock.info.assert_called_once()
        args = mock.info.call_args[0][0]
        assert "test_info" in args
        assert "value=test" in args

    def test_warning(self, mock_logger: tuple[Logger, MagicMock]) -> None:
        """Warning should call logger.warning."""
        logger, mock = mock_logger
        logger.warning("test_warning", error="oops")
        mock.warning.assert_called_once()
        args = mock.warning.call_args[0][0]
        assert "test_warning" in args
        assert "error=oops" in args

    def test_error(self, mock_logger: tuple[Logger, MagicMock]) -> None:
        """Error should call logger.error."""
        logger, mock = mock_logger
        logger.error("test_error", code=500)
        mock.error.assert_called_once()
        args = mock.error.call_args[0][0]
        assert "test_error" in args
        assert "code=500" in args

    def test_critical(self, mock_logger: tuple[Logger, MagicMock]) -> None:
        """Critical should call logger.critical."""
        logger, mock = mock_logger
        logger.critical("test_critical", fatal=True)
        mock.critical.assert_called_once()
        args = mock.critical.call_args[0][0]
        assert "test_critical" in args
        assert "fatal=True" in args

    def test_exception(self, mock_logger: tuple[Logger, MagicMock]) -> None:
        """Exception should call logger.exception."""
        logger, mock = mock_logger
        logger.exception("test_exception", trace="...")
        mock.exception.assert_called_once()
        args = mock.exception.call_args[0][0]
        assert "test_exception" in args


class TestLoggerIntegration:
    """Integration tests with real logging."""

    def test_log_to_handler(self, caplog: pytest.LogCaptureFixture) -> None:
        """Logs should reach handlers."""
        with caplog.at_level(logging.INFO):
            logger = Logger("integration_test")
            logger.info("hello", world=True)

        assert len(caplog.records) == 1
        assert "hello" in caplog.records[0].message
        assert "world=True" in caplog.records[0].message

    def test_json_log_to_handler(self, caplog: pytest.LogCaptureFixture) -> None:
        """JSON logs should be valid JSON in handler."""
        with caplog.at_level(logging.INFO):
            logger = Logger("json_test", json_output=True)
            logger.info("test", value=42)

        assert len(caplog.records) == 1
        parsed = json.loads(caplog.records[0].message)
        assert parsed["message"] == "test"
        assert parsed["value"] == 42