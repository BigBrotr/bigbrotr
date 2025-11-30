"""
Unit tests for Logger module.
"""

from core.logger import Logger


class TestLogger:
    """Tests for Logger class."""

    def test_init(self) -> None:
        """Test Logger initialization."""
        logger = Logger("test_service")
        assert logger._logger.name == "test_service"

    def test_log_methods_exist(self) -> None:
        """Test all log methods exist."""
        logger = Logger("test")

        assert hasattr(logger, "debug")
        assert hasattr(logger, "info")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "error")
        assert hasattr(logger, "critical")
        assert hasattr(logger, "exception")
