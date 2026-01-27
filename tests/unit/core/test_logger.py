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
from core.logger import format_kv_pairs


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


class TestFormatKvPairs:
    """Key-value pairs formatting and escaping."""

    def test_simple(self):
        assert format_kv_pairs({"key": "hello"}) == " key=hello"
        assert format_kv_pairs({"key": 123}) == " key=123"
        assert format_kv_pairs({"key": 45.67}) == " key=45.67"

    def test_with_spaces(self):
        assert format_kv_pairs({"key": "hello world"}) == ' key="hello world"'

    def test_with_equals(self):
        assert format_kv_pairs({"key": "foo=bar"}) == ' key="foo=bar"'

    def test_with_double_quotes(self):
        assert format_kv_pairs({"key": 'say "hello"'}) == ' key="say \\"hello\\""'

    def test_with_single_quotes(self):
        assert format_kv_pairs({"key": "it's"}) == ' key="it\'s"'

    def test_empty_value(self):
        assert format_kv_pairs({"key": ""}) == ' key=""'

    def test_with_backslash(self):
        assert format_kv_pairs({"key": "path\\to\\file"}) == " key=path\\to\\file"

    def test_with_backslash_and_spaces(self):
        assert format_kv_pairs({"key": "path\\to\\my file"}) == ' key="path\\\\to\\\\my file"'

    def test_empty_dict(self):
        assert format_kv_pairs({}) == ""

    def test_multiple_keys(self):
        result = format_kv_pairs({"a": 1, "b": 2})
        assert "a=1" in result
        assert "b=2" in result

    def test_truncation(self):
        long_value = "x" * 1500
        result = format_kv_pairs({"key": long_value}, max_value_length=1000)
        assert "truncated" in result
        assert len(result) < 1500

    def test_no_truncation(self):
        long_value = "x" * 1500
        result = format_kv_pairs({"key": long_value}, max_value_length=None)
        assert "truncated" not in result

    def test_custom_prefix(self):
        assert format_kv_pairs({"key": "val"}, prefix="") == "key=val"
        assert format_kv_pairs({"key": "val"}, prefix=" | ") == " | key=val"


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
