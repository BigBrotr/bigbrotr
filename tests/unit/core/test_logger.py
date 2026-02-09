"""
Unit tests for logger module.

Tests:
- Logger initialization with name, json_output, and max_value_length
- format_kv_pairs() utility function
- StructuredFormatter formatting
- All log levels (debug, info, warning, error, critical, exception)
- Value escaping and quoting
- Truncation of long values
- JSON output mode
- Integration with Python logging
"""

import json
import logging
from unittest.mock import MagicMock

import pytest

from bigbrotr.core.logger import Logger, StructuredFormatter, format_kv_pairs


# ============================================================================
# format_kv_pairs Tests
# ============================================================================


class TestFormatKvPairs:
    """Tests for format_kv_pairs() utility function."""

    def test_empty_dict(self) -> None:
        """Test formatting empty dictionary returns empty string."""
        assert format_kv_pairs({}) == ""

    def test_simple_string(self) -> None:
        """Test formatting simple string value."""
        result = format_kv_pairs({"key": "hello"})
        assert result == " key=hello"

    def test_simple_integer(self) -> None:
        """Test formatting integer value."""
        result = format_kv_pairs({"key": 123})
        assert result == " key=123"

    def test_simple_float(self) -> None:
        """Test formatting float value."""
        result = format_kv_pairs({"key": 45.67})
        assert result == " key=45.67"

    def test_boolean_value(self) -> None:
        """Test formatting boolean values."""
        result = format_kv_pairs({"flag": True})
        assert result == " flag=True"

        result = format_kv_pairs({"flag": False})
        assert result == " flag=False"

    def test_none_value(self) -> None:
        """Test formatting None value."""
        result = format_kv_pairs({"key": None})
        assert result == " key=None"

    def test_value_with_spaces(self) -> None:
        """Test that values with spaces are quoted."""
        result = format_kv_pairs({"key": "hello world"})
        assert result == ' key="hello world"'

    def test_value_with_equals_sign(self) -> None:
        """Test that values with equals sign are quoted."""
        result = format_kv_pairs({"key": "foo=bar"})
        assert result == ' key="foo=bar"'

    def test_value_with_double_quotes(self) -> None:
        """Test that double quotes in values are escaped."""
        result = format_kv_pairs({"key": 'say "hello"'})
        assert result == ' key="say \\"hello\\""'

    def test_value_with_single_quotes(self) -> None:
        """Test that values with single quotes are quoted."""
        result = format_kv_pairs({"key": "it's"})
        assert result == ' key="it\'s"'

    def test_empty_string_value(self) -> None:
        """Test formatting empty string value."""
        result = format_kv_pairs({"key": ""})
        assert result == ' key=""'

    def test_value_with_backslash(self) -> None:
        """Test that simple backslash values are not quoted."""
        result = format_kv_pairs({"key": "path\\to\\file"})
        assert result == " key=path\\to\\file"

    def test_value_with_backslash_and_spaces(self) -> None:
        """Test that backslash values with spaces are escaped properly."""
        result = format_kv_pairs({"key": "path\\to\\my file"})
        assert result == ' key="path\\\\to\\\\my file"'

    def test_multiple_keys(self) -> None:
        """Test formatting multiple key-value pairs."""
        result = format_kv_pairs({"a": 1, "b": 2, "c": 3})
        assert "a=1" in result
        assert "b=2" in result
        assert "c=3" in result

    def test_mixed_types(self) -> None:
        """Test formatting mixed value types."""
        result = format_kv_pairs({"str": "hello", "int": 42, "float": 3.14, "bool": True})
        assert "str=hello" in result
        assert "int=42" in result
        assert "float=3.14" in result
        assert "bool=True" in result


class TestFormatKvPairsTruncation:
    """Tests for format_kv_pairs() truncation behavior."""

    def test_truncation_with_default_limit(self) -> None:
        """Test truncation at default limit (1000 chars)."""
        long_value = "x" * 1500
        result = format_kv_pairs({"key": long_value}, max_value_length=1000)

        assert "truncated" in result
        assert len(result) < 1500 + 50  # Account for truncation message

    def test_truncation_message_format(self) -> None:
        """Test truncation message format."""
        long_value = "x" * 1500
        result = format_kv_pairs({"key": long_value}, max_value_length=1000)

        assert "truncated 500 chars" in result

    def test_no_truncation_when_disabled(self) -> None:
        """Test no truncation when max_value_length is None."""
        long_value = "x" * 1500
        result = format_kv_pairs({"key": long_value}, max_value_length=None)

        assert "truncated" not in result
        assert "x" * 1500 in result

    def test_no_truncation_when_under_limit(self) -> None:
        """Test no truncation for values under limit."""
        short_value = "x" * 100
        result = format_kv_pairs({"key": short_value}, max_value_length=1000)

        assert "truncated" not in result
        assert "x" * 100 in result


class TestFormatKvPairsPrefix:
    """Tests for format_kv_pairs() prefix behavior."""

    def test_default_prefix(self) -> None:
        """Test default prefix is single space."""
        result = format_kv_pairs({"key": "value"})
        assert result.startswith(" ")

    def test_empty_prefix(self) -> None:
        """Test empty prefix."""
        result = format_kv_pairs({"key": "val"}, prefix="")
        assert result == "key=val"

    def test_custom_prefix(self) -> None:
        """Test custom prefix."""
        result = format_kv_pairs({"key": "val"}, prefix=" | ")
        assert result == " | key=val"


# ============================================================================
# StructuredFormatter Tests
# ============================================================================


class TestStructuredFormatter:
    """Tests for StructuredFormatter."""

    def test_plain_message_without_structured_kv(self) -> None:
        """Test formatting a plain log record without structured_kv extra."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test.module",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="simple message",
            args=None,
            exc_info=None,
        )
        result = formatter.format(record)
        assert result == "info test.module simple message"

    def test_message_with_structured_kv(self) -> None:
        """Test formatting a log record with structured_kv extra."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="finder",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="cycle_completed",
            args=None,
            exc_info=None,
        )
        record.structured_kv = {"cycle": 1, "duration": 2.5}  # type: ignore[attr-defined]
        result = formatter.format(record)
        assert result.startswith("info finder cycle_completed")
        assert "cycle=1" in result
        assert "duration=2.5" in result

    def test_empty_structured_kv(self) -> None:
        """Test formatting with empty structured_kv dict."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="warning msg",
            args=None,
            exc_info=None,
        )
        record.structured_kv = {}  # type: ignore[attr-defined]
        result = formatter.format(record)
        assert result == "warning test warning msg"

    def test_debug_level_prefix(self) -> None:
        """Test that the level name is lowercase."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="pool",
            level=logging.DEBUG,
            pathname="",
            lineno=0,
            msg="connecting",
            args=None,
            exc_info=None,
        )
        result = formatter.format(record)
        assert result.startswith("debug pool")

    def test_error_level_prefix(self) -> None:
        """Test error level prefix."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="brotr",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="failed",
            args=None,
            exc_info=None,
        )
        result = formatter.format(record)
        assert result.startswith("error brotr")

    def test_critical_level_prefix(self) -> None:
        """Test critical level prefix."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="service",
            level=logging.CRITICAL,
            pathname="",
            lineno=0,
            msg="shutdown",
            args=None,
            exc_info=None,
        )
        result = formatter.format(record)
        assert result.startswith("critical service")

    def test_structured_kv_with_spaces_in_values(self) -> None:
        """Test that values with spaces are properly quoted in formatter output."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="event",
            args=None,
            exc_info=None,
        )
        record.structured_kv = {"path": "hello world"}  # type: ignore[attr-defined]
        result = formatter.format(record)
        assert 'path="hello world"' in result

    def test_stdlib_logger_without_structured_kv(self) -> None:
        """Test that stdlib loggers without structured_kv still format correctly."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="models.metadata",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="validation failed",
            args=None,
            exc_info=None,
        )
        # No structured_kv attribute at all
        result = formatter.format(record)
        assert result == "warning models.metadata validation failed"

    def test_message_with_percent_args(self) -> None:
        """Test that getMessage() properly expands %-formatting args."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="count: %d",
            args=(42,),
            exc_info=None,
        )
        result = formatter.format(record)
        assert "count: 42" in result


# ============================================================================
# Logger Initialization Tests
# ============================================================================


class TestLoggerInit:
    """Tests for Logger initialization."""

    def test_name(self) -> None:
        """Test logger is created with correct name."""
        logger = Logger("test_service")
        assert logger._logger.name == "test_service"

    def test_default_not_json(self) -> None:
        """Test default json_output is False."""
        logger = Logger("test")
        assert logger._json_output is False

    def test_json_mode(self) -> None:
        """Test explicit json_output=True."""
        logger = Logger("test", json_output=True)
        assert logger._json_output is True

    def test_default_max_value_length(self) -> None:
        """Test default max_value_length is 1000."""
        logger = Logger("test")
        assert logger._max_value_length == 1000

    def test_custom_max_value_length(self) -> None:
        """Test custom max_value_length."""
        logger = Logger("test", max_value_length=500)
        assert logger._max_value_length == 500

    def test_none_max_value_length(self) -> None:
        """Test max_value_length=None for no truncation."""
        logger = Logger("test", max_value_length=None)
        assert logger._max_value_length == 1000  # Falls back to default


# ============================================================================
# JSON Formatting Tests
# ============================================================================


class TestFormatJson:
    """Tests for JSON output mode formatting."""

    def test_json_without_kwargs(self) -> None:
        """Test JSON formatting without kwargs."""
        logger = Logger("test", json_output=True)
        result = logger._format_json("test_msg", "info", {})

        parsed = json.loads(result)
        assert parsed["message"] == "test_msg"
        assert parsed["level"] == "info"
        assert parsed["service"] == "test"
        assert "timestamp" in parsed

    def test_json_with_kwargs(self) -> None:
        """Test JSON formatting with kwargs."""
        logger = Logger("test", json_output=True)
        result = logger._format_json("test_msg", "warning", {"count": 42, "name": "test"})

        parsed = json.loads(result)
        assert parsed["message"] == "test_msg"
        assert parsed["level"] == "warning"
        assert parsed["count"] == 42
        assert parsed["name"] == "test"

    def test_json_complex_values(self) -> None:
        """Test JSON formatting with complex values."""
        logger = Logger("test", json_output=True)
        result = logger._format_json("msg", "debug", {"data": {"nested": True}, "list": [1, 2, 3]})

        parsed = json.loads(result)
        assert parsed["data"] == {"nested": True}
        assert parsed["list"] == [1, 2, 3]

    def test_json_non_serializable_values(self) -> None:
        """Test JSON formatting handles non-serializable values."""
        logger = Logger("test", json_output=True)

        class CustomObject:
            def __str__(self) -> str:
                return "custom_repr"

        result = logger._format_json("msg", "error", {"obj": CustomObject()})

        parsed = json.loads(result)
        assert "custom_repr" in parsed["obj"]


# ============================================================================
# _make_extra Tests
# ============================================================================


class TestMakeExtra:
    """Tests for Logger._make_extra() method."""

    def test_empty_kwargs(self) -> None:
        """Test _make_extra with empty kwargs returns empty dict."""
        logger = Logger("test")
        result = logger._make_extra({})
        assert result == {}

    def test_simple_kwargs(self) -> None:
        """Test _make_extra wraps kwargs in structured_kv."""
        logger = Logger("test")
        result = logger._make_extra({"count": 42, "name": "test"})
        assert "structured_kv" in result
        assert result["structured_kv"]["count"] == 42
        assert result["structured_kv"]["name"] == "test"

    def test_truncation_applied(self) -> None:
        """Test _make_extra applies truncation based on max_value_length."""
        logger = Logger("test", max_value_length=10)
        result = logger._make_extra({"key": "a" * 20})
        val = result["structured_kv"]["key"]
        assert "truncated" in val
        assert "10 chars" in val

    def test_no_truncation_for_short_values(self) -> None:
        """Test _make_extra does not truncate short values."""
        logger = Logger("test", max_value_length=100)
        result = logger._make_extra({"key": "short"})
        assert result["structured_kv"]["key"] == "short"

    def test_non_string_values_preserved(self) -> None:
        """Test _make_extra preserves non-string types when under limit."""
        logger = Logger("test")
        result = logger._make_extra({"count": 42, "flag": True, "ratio": 3.14})
        kv = result["structured_kv"]
        assert kv["count"] == 42
        assert kv["flag"] is True
        assert kv["ratio"] == 3.14


# ============================================================================
# Log Level Tests
# ============================================================================


class TestLogLevels:
    """Tests for all log level methods."""

    @pytest.fixture
    def mock_logger(self) -> tuple[Logger, MagicMock]:
        """Create logger with mocked internal logger."""
        logger = Logger("test")
        mock = MagicMock()
        logger._logger = mock
        return logger, mock

    def test_debug(self, mock_logger: tuple[Logger, MagicMock]) -> None:
        """Test debug() passes message and structured_kv extra."""
        logger, mock = mock_logger
        logger.debug("test_debug", count=1)

        mock.debug.assert_called_once()
        assert mock.debug.call_args[0][0] == "test_debug"
        extra = mock.debug.call_args[1]["extra"]
        assert extra["structured_kv"]["count"] == 1

    def test_info(self, mock_logger: tuple[Logger, MagicMock]) -> None:
        """Test info() passes message and structured_kv extra."""
        logger, mock = mock_logger
        logger.info("test_info", value="test")

        mock.info.assert_called_once()
        assert mock.info.call_args[0][0] == "test_info"
        extra = mock.info.call_args[1]["extra"]
        assert extra["structured_kv"]["value"] == "test"

    def test_warning(self, mock_logger: tuple[Logger, MagicMock]) -> None:
        """Test warning() passes message and structured_kv extra."""
        logger, mock = mock_logger
        logger.warning("test_warning", error="oops")

        mock.warning.assert_called_once()
        assert mock.warning.call_args[0][0] == "test_warning"
        extra = mock.warning.call_args[1]["extra"]
        assert extra["structured_kv"]["error"] == "oops"

    def test_error(self, mock_logger: tuple[Logger, MagicMock]) -> None:
        """Test error() passes message and structured_kv extra."""
        logger, mock = mock_logger
        logger.error("test_error", code=500)

        mock.error.assert_called_once()
        assert mock.error.call_args[0][0] == "test_error"
        extra = mock.error.call_args[1]["extra"]
        assert extra["structured_kv"]["code"] == 500

    def test_critical(self, mock_logger: tuple[Logger, MagicMock]) -> None:
        """Test critical() passes message and structured_kv extra."""
        logger, mock = mock_logger
        logger.critical("test_critical", fatal=True)

        mock.critical.assert_called_once()
        assert mock.critical.call_args[0][0] == "test_critical"
        extra = mock.critical.call_args[1]["extra"]
        assert extra["structured_kv"]["fatal"] is True

    def test_exception(self, mock_logger: tuple[Logger, MagicMock]) -> None:
        """Test exception() passes message and structured_kv extra."""
        logger, mock = mock_logger
        logger.exception("test_exception", trace="...")

        mock.exception.assert_called_once()
        assert mock.exception.call_args[0][0] == "test_exception"
        extra = mock.exception.call_args[1]["extra"]
        assert extra["structured_kv"]["trace"] == "..."


class TestLogLevelsWithoutKwargs:
    """Tests for log methods without kwargs."""

    @pytest.fixture
    def mock_logger(self) -> tuple[Logger, MagicMock]:
        """Create logger with mocked internal logger."""
        logger = Logger("test")
        mock = MagicMock()
        logger._logger = mock
        return logger, mock

    def test_debug_no_kwargs(self, mock_logger: tuple[Logger, MagicMock]) -> None:
        """Test debug() without kwargs passes no extra."""
        logger, mock = mock_logger
        logger.debug("simple message")

        mock.debug.assert_called_once_with("simple message", extra={})

    def test_info_no_kwargs(self, mock_logger: tuple[Logger, MagicMock]) -> None:
        """Test info() without kwargs passes no extra."""
        logger, mock = mock_logger
        logger.info("simple message")

        mock.info.assert_called_once_with("simple message", extra={})


class TestLogLevelsJsonMode:
    """Tests for log methods in JSON output mode."""

    @pytest.fixture
    def mock_logger(self) -> tuple[Logger, MagicMock]:
        """Create JSON logger with mocked internal logger."""
        logger = Logger("test", json_output=True)
        mock = MagicMock()
        logger._logger = mock
        return logger, mock

    def test_info_json(self, mock_logger: tuple[Logger, MagicMock]) -> None:
        """Test info() in JSON mode formats as JSON string."""
        logger, mock = mock_logger
        logger.info("test_msg", count=42)

        mock.info.assert_called_once()
        parsed = json.loads(mock.info.call_args[0][0])
        assert parsed["message"] == "test_msg"
        assert parsed["count"] == 42

    def test_error_json(self, mock_logger: tuple[Logger, MagicMock]) -> None:
        """Test error() in JSON mode formats as JSON string."""
        logger, mock = mock_logger
        logger.error("fail", code=500)

        mock.error.assert_called_once()
        parsed = json.loads(mock.error.call_args[0][0])
        assert parsed["message"] == "fail"
        assert parsed["code"] == 500

    def test_debug_json_no_kwargs(self, mock_logger: tuple[Logger, MagicMock]) -> None:
        """Test debug() in JSON mode without kwargs."""
        logger, mock = mock_logger
        logger.debug("simple")

        mock.debug.assert_called_once()
        parsed = json.loads(mock.debug.call_args[0][0])
        assert parsed["message"] == "simple"


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    """Integration tests with real Python logging."""

    def test_log_to_handler(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that logs are captured by handler with structured_kv extra."""
        with caplog.at_level(logging.INFO):
            logger = Logger("integration_test")
            logger.info("hello", world=True)

        assert len(caplog.records) == 1
        assert caplog.records[0].message == "hello"
        assert getattr(caplog.records[0], "structured_kv", {}).get("world") is True

    def test_json_log_to_handler(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test JSON output is captured by handler."""
        with caplog.at_level(logging.INFO):
            logger = Logger("json_test", json_output=True)
            logger.info("test", value=42)

        parsed = json.loads(caplog.records[0].message)
        assert parsed["message"] == "test"
        assert parsed["value"] == 42

    def test_log_levels_captured(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test different log levels are captured correctly."""
        logger = Logger("level_test")

        with caplog.at_level(logging.DEBUG):
            logger.debug("debug_message")
            logger.info("info_message")
            logger.warning("warning_message")
            logger.error("error_message")
            logger.critical("critical_message")

        messages = [r.message for r in caplog.records]
        assert any("debug_message" in m for m in messages)
        assert any("info_message" in m for m in messages)
        assert any("warning_message" in m for m in messages)
        assert any("error_message" in m for m in messages)
        assert any("critical_message" in m for m in messages)

    def test_log_record_level(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test log record has correct level."""
        logger = Logger("level_test")

        with caplog.at_level(logging.DEBUG):
            logger.debug("debug")
            logger.info("info")
            logger.warning("warning")
            logger.error("error")
            logger.critical("critical")

        levels = [r.levelno for r in caplog.records]
        assert logging.DEBUG in levels
        assert logging.INFO in levels
        assert logging.WARNING in levels
        assert logging.ERROR in levels
        assert logging.CRITICAL in levels

    def test_structured_formatter_integration(self) -> None:
        """Test StructuredFormatter produces correct output through real logging."""
        formatter = StructuredFormatter()
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)

        test_logger = logging.getLogger("formatter_integration_test")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.DEBUG)

        # Create a record manually and format it
        record = test_logger.makeRecord(
            name="formatter_integration_test",
            level=logging.INFO,
            fn="",
            lno=0,
            msg="cycle_done",
            args=(),
            exc_info=None,
            extra={"structured_kv": {"cycle": 5, "elapsed": 1.2}},
        )
        result = formatter.format(record)
        assert result.startswith("info formatter_integration_test cycle_done")
        assert "cycle=5" in result
        assert "elapsed=1.2" in result

        # Cleanup
        test_logger.removeHandler(handler)

    def test_stdlib_logger_through_structured_formatter(self) -> None:
        """Test plain stdlib logger records format cleanly through StructuredFormatter."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="models.metadata",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="unknown type: %s",
            args=("foo",),
            exc_info=None,
        )
        result = formatter.format(record)
        assert result == "warning models.metadata unknown type: foo"


# ============================================================================
# Edge Cases Tests
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_special_characters_in_message(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test special characters in message."""
        with caplog.at_level(logging.INFO):
            logger = Logger("test")
            logger.info("msg with\nnewline")

        assert "msg with\nnewline" in caplog.records[0].message

    def test_unicode_in_values(self) -> None:
        """Test unicode characters in values."""
        result = format_kv_pairs({"emoji": "test"})
        assert "test" in result

    def test_very_long_key_name(self) -> None:
        """Test very long key names."""
        long_key = "a" * 100
        result = format_kv_pairs({long_key: "value"})
        assert long_key in result

    def test_numeric_key(self) -> None:
        """Test numeric-like key names."""
        result = format_kv_pairs({"123": "value", "key456": "value2"})
        assert "123=value" in result
        assert "key456=value2" in result

    def test_multiple_spaces_in_value(self) -> None:
        """Test multiple spaces in value."""
        result = format_kv_pairs({"key": "hello    world"})
        assert 'key="hello    world"' in result

    def test_tab_in_value(self) -> None:
        """Test tab character in value (not quoted unless space present)."""
        result = format_kv_pairs({"key": "hello\tworld"})
        # Tab doesn't trigger quoting
        assert "key=hello\tworld" in result

    def test_newline_in_value(self) -> None:
        """Test newline in value (not quoted unless space present)."""
        result = format_kv_pairs({"key": "hello\nworld"})
        assert "key=hello\nworld" in result
