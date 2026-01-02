"""
Unit tests for core.logger module.

Tests:
- Logger initialization with name and level
- Structured key=value message formatting
- All log levels (debug, info, warning, error, critical, exception)
- Value formatting (strings, numbers, booleans, None)
- get_child() for hierarchical loggers
"""

import json
import logging
from unittest.mock import MagicMock

import pytest

from core import Logger


class TestInit:
    """Logger initialization."""

    def test_name(self):
        logger = Logger("test_service")
        assert logger._logger.name == "test_service"

    def test_default_not_json(self):
        logger = Logger("test")
        assert logger._json_output is False

    def test_json_mode(self):
        logger = Logger("test", json_output=True)
        assert logger._json_output is True


class TestFormatValue:
    """Value formatting and escaping."""

    def test_simple(self):
        logger = Logger("test")
        assert logger._format_value("hello") == "hello"
        assert logger._format_value(123) == "123"
        assert logger._format_value(45.67) == "45.67"

    def test_with_spaces(self):
        logger = Logger("test")
        assert logger._format_value("hello world") == '"hello world"'

    def test_with_equals(self):
        logger = Logger("test")
        assert logger._format_value("foo=bar") == '"foo=bar"'

    def test_with_double_quotes(self):
        logger = Logger("test")
        assert logger._format_value('say "hello"') == '"say \\"hello\\""'

    def test_with_single_quotes(self):
        logger = Logger("test")
        assert logger._format_value("it's") == '"it\'s"'

    def test_empty(self):
        logger = Logger("test")
        assert logger._format_value("") == '""'

    def test_with_backslash(self):
        logger = Logger("test")
        assert logger._format_value("path\\to\\file") == "path\\to\\file"

    def test_with_backslash_and_spaces(self):
        logger = Logger("test")
        assert logger._format_value("path\\to\\my file") == '"path\\\\to\\\\my file"'


class TestFormatMessage:
    """Message formatting."""

    def test_without_kwargs(self):
        logger = Logger("test")
        assert logger._format_message("test_msg", {}) == "test_msg"

    def test_with_kwargs(self):
        logger = Logger("test")
        result = logger._format_message("test_msg", {"count": 42, "name": "test"})
        assert "test_msg" in result
        assert "count=42" in result
        assert "name=test" in result

    def test_json_without_kwargs(self):
        logger = Logger("test", json_output=True)
        result = logger._format_message("test_msg", {})
        parsed = json.loads(result)
        assert parsed["message"] == "test_msg"

    def test_json_with_kwargs(self):
        logger = Logger("test", json_output=True)
        result = logger._format_message("test_msg", {"count": 42, "name": "test"})
        parsed = json.loads(result)
        assert parsed["message"] == "test_msg"
        assert parsed["count"] == 42
        assert parsed["name"] == "test"

    def test_json_complex_values(self):
        logger = Logger("test", json_output=True)
        result = logger._format_message("msg", {"data": {"nested": True}})
        parsed = json.loads(result)
        assert parsed["data"] == {"nested": True}


class TestLogLevels:
    """All log levels."""

    @pytest.fixture
    def mock_logger(self):
        logger = Logger("test")
        mock = MagicMock()
        logger._logger = mock
        return logger, mock

    def test_debug(self, mock_logger):
        logger, mock = mock_logger
        logger.debug("test_debug", count=1)
        mock.debug.assert_called_once()
        assert "test_debug" in mock.debug.call_args[0][0]

    def test_info(self, mock_logger):
        logger, mock = mock_logger
        logger.info("test_info", value="test")
        mock.info.assert_called_once()
        assert "value=test" in mock.info.call_args[0][0]

    def test_warning(self, mock_logger):
        logger, mock = mock_logger
        logger.warning("test_warning", error="oops")
        mock.warning.assert_called_once()

    def test_error(self, mock_logger):
        logger, mock = mock_logger
        logger.error("test_error", code=500)
        mock.error.assert_called_once()

    def test_critical(self, mock_logger):
        logger, mock = mock_logger
        logger.critical("test_critical", fatal=True)
        mock.critical.assert_called_once()

    def test_exception(self, mock_logger):
        logger, mock = mock_logger
        logger.exception("test_exception", trace="...")
        mock.exception.assert_called_once()


class TestIntegration:
    """Integration tests with real logging."""

    def test_log_to_handler(self, caplog):
        with caplog.at_level(logging.INFO):
            logger = Logger("integration_test")
            logger.info("hello", world=True)

        assert len(caplog.records) == 1
        assert "hello" in caplog.records[0].message
        assert "world=True" in caplog.records[0].message

    def test_json_log_to_handler(self, caplog):
        with caplog.at_level(logging.INFO):
            logger = Logger("json_test", json_output=True)
            logger.info("test", value=42)

        parsed = json.loads(caplog.records[0].message)
        assert parsed["message"] == "test"
        assert parsed["value"] == 42
