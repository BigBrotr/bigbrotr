"""
Unit tests for models.nips.nip66.logs module.

Tests:
- Nip66RttLogs semantic validation rules
- Success/reason constraint validation
- Cascade validation (open failure -> read/write failure)
- Nip66BaseLogs and derived logs classes
- to_dict() and from_dict() methods
"""

from __future__ import annotations

import pytest

from models.nips.nip66.logs import (
    Nip66DnsLogs,
    Nip66GeoLogs,
    Nip66HttpLogs,
    Nip66NetLogs,
    Nip66RttLogs,
    Nip66SslLogs,
)


class TestNip66RttLogsValidation:
    """Test Nip66RttLogs semantic validation rules."""

    def test_all_success(self) -> None:
        """All operations successful is valid."""
        logs = Nip66RttLogs(
            open_success=True,
            read_success=True,
            write_success=True,
        )
        assert logs.open_success is True
        assert logs.read_success is True
        assert logs.write_success is True
        assert logs.open_reason is None
        assert logs.read_reason is None
        assert logs.write_reason is None

    def test_open_success_read_write_optional(self) -> None:
        """Open success with optional read/write is valid."""
        logs = Nip66RttLogs(open_success=True)
        assert logs.open_success is True
        assert logs.read_success is None
        assert logs.write_success is None

    def test_open_fail_cascades(self) -> None:
        """Open failure with cascading read/write failures is valid."""
        logs = Nip66RttLogs(
            open_success=False,
            open_reason="connection refused",
            read_success=False,
            read_reason="connection refused",
            write_success=False,
            write_reason="connection refused",
        )
        assert logs.open_success is False
        assert logs.read_success is False
        assert logs.write_success is False

    def test_partial_success_read_fail(self) -> None:
        """Open success, read failure, write untested is valid."""
        logs = Nip66RttLogs(
            open_success=True,
            read_success=False,
            read_reason="no events returned",
        )
        assert logs.open_success is True
        assert logs.read_success is False
        assert logs.write_success is None

    def test_partial_success_write_fail(self) -> None:
        """Open+read success, write failure is valid."""
        logs = Nip66RttLogs(
            open_success=True,
            read_success=True,
            write_success=False,
            write_reason="auth-required",
        )
        assert logs.open_success is True
        assert logs.read_success is True
        assert logs.write_success is False
        assert logs.write_reason == "auth-required"


class TestNip66RttLogsSuccessReasonConstraints:
    """Test success/reason pair constraints for RTT logs."""

    def test_open_success_with_reason_raises(self) -> None:
        """Open success with reason is invalid."""
        with pytest.raises(ValueError, match="open_reason must be None when open_success is True"):
            Nip66RttLogs(
                open_success=True,
                open_reason="should not be here",
            )

    def test_open_failure_without_reason_raises(self) -> None:
        """Open failure without reason is invalid."""
        with pytest.raises(ValueError, match="open_reason is required when open_success is False"):
            Nip66RttLogs(
                open_success=False,
                open_reason=None,
            )

    def test_read_success_with_reason_raises(self) -> None:
        """Read success with reason is invalid."""
        with pytest.raises(ValueError, match="read_reason must be None when read_success is True"):
            Nip66RttLogs(
                open_success=True,
                read_success=True,
                read_reason="should not be here",
            )

    def test_read_failure_without_reason_raises(self) -> None:
        """Read failure without reason is invalid."""
        with pytest.raises(ValueError, match="read_reason is required when read_success is False"):
            Nip66RttLogs(
                open_success=True,
                read_success=False,
                read_reason=None,
            )

    def test_write_success_with_reason_raises(self) -> None:
        """Write success with reason is invalid."""
        with pytest.raises(
            ValueError, match="write_reason must be None when write_success is True"
        ):
            Nip66RttLogs(
                open_success=True,
                write_success=True,
                write_reason="should not be here",
            )

    def test_write_failure_without_reason_raises(self) -> None:
        """Write failure without reason is invalid."""
        with pytest.raises(
            ValueError, match="write_reason is required when write_success is False"
        ):
            Nip66RttLogs(
                open_success=True,
                write_success=False,
                write_reason=None,
            )


class TestNip66RttLogsCascadeConstraints:
    """Test cascade constraints when open fails."""

    def test_open_fail_read_success_raises(self) -> None:
        """Open failure with read success is invalid (cascade constraint)."""
        with pytest.raises(
            ValueError, match="read_success must be False when open_success is False"
        ):
            Nip66RttLogs(
                open_success=False,
                open_reason="connection refused",
                read_success=True,
            )

    def test_open_fail_write_success_raises(self) -> None:
        """Open failure with write success is invalid (cascade constraint)."""
        with pytest.raises(
            ValueError, match="write_success must be False when open_success is False"
        ):
            Nip66RttLogs(
                open_success=False,
                open_reason="connection refused",
                write_success=True,
            )

    def test_open_fail_read_none_allowed(self) -> None:
        """Open failure with read=None is valid."""
        logs = Nip66RttLogs(
            open_success=False,
            open_reason="connection refused",
            read_success=None,
        )
        assert logs.read_success is None

    def test_open_fail_write_none_allowed(self) -> None:
        """Open failure with write=None is valid."""
        logs = Nip66RttLogs(
            open_success=False,
            open_reason="connection refused",
            write_success=None,
        )
        assert logs.write_success is None


class TestNip66RttLogsSerialization:
    """Test Nip66RttLogs serialization methods."""

    def test_to_dict_excludes_none(self) -> None:
        """to_dict excludes None values."""
        logs = Nip66RttLogs(open_success=True)
        d = logs.to_dict()
        assert d == {"open_success": True}
        assert "open_reason" not in d
        assert "read_success" not in d
        assert "write_success" not in d

    def test_to_dict_includes_all_set_values(self) -> None:
        """to_dict includes all explicitly set values."""
        logs = Nip66RttLogs(
            open_success=True,
            read_success=False,
            read_reason="timeout",
        )
        d = logs.to_dict()
        assert d == {
            "open_success": True,
            "read_success": False,
            "read_reason": "timeout",
        }

    def test_to_dict_complete(self) -> None:
        """to_dict with all fields set."""
        logs = Nip66RttLogs(
            open_success=True,
            read_success=True,
            write_success=False,
            write_reason="auth-required",
        )
        d = logs.to_dict()
        assert d == {
            "open_success": True,
            "read_success": True,
            "write_success": False,
            "write_reason": "auth-required",
        }

    def test_from_dict_success(self) -> None:
        """from_dict creates valid logs."""
        data = {
            "open_success": True,
            "read_success": True,
            "write_success": True,
        }
        logs = Nip66RttLogs.from_dict(data)
        assert logs.open_success is True
        assert logs.read_success is True
        assert logs.write_success is True

    def test_from_dict_with_failure(self) -> None:
        """from_dict handles failure cases."""
        data = {
            "open_success": False,
            "open_reason": "connection refused",
            "read_success": False,
            "read_reason": "connection refused",
            "write_success": False,
            "write_reason": "connection refused",
        }
        logs = Nip66RttLogs.from_dict(data)
        assert logs.open_success is False
        assert logs.open_reason == "connection refused"


class TestNip66RttLogsImmutability:
    """Test that Nip66RttLogs is frozen/immutable."""

    def test_cannot_modify_open_success(self) -> None:
        """Cannot modify open_success after creation."""
        from pydantic import ValidationError

        logs = Nip66RttLogs(open_success=True)
        with pytest.raises((ValidationError, TypeError, AttributeError)):
            logs.open_success = False  # type: ignore[misc]

    def test_cannot_modify_read_success(self) -> None:
        """Cannot modify read_success after creation."""
        from pydantic import ValidationError

        logs = Nip66RttLogs(open_success=True, read_success=True)
        with pytest.raises((ValidationError, TypeError, AttributeError)):
            logs.read_success = False  # type: ignore[misc]


class TestNip66BaseLogsAndDerived:
    """Test Nip66BaseLogs and derived log classes."""

    def test_ssl_logs_success(self) -> None:
        """Nip66SslLogs success case."""
        logs = Nip66SslLogs(success=True, reason=None)
        assert logs.success is True
        assert logs.reason is None

    def test_ssl_logs_failure(self) -> None:
        """Nip66SslLogs failure case."""
        logs = Nip66SslLogs(success=False, reason="certificate expired")
        assert logs.success is False
        assert logs.reason == "certificate expired"

    def test_ssl_logs_success_with_reason_raises(self) -> None:
        """Nip66SslLogs success with reason raises."""
        with pytest.raises(ValueError, match="reason must be None when success is True"):
            Nip66SslLogs(success=True, reason="should not be here")

    def test_ssl_logs_failure_without_reason_raises(self) -> None:
        """Nip66SslLogs failure without reason raises."""
        with pytest.raises(ValueError, match="reason is required when success is False"):
            Nip66SslLogs(success=False, reason=None)

    def test_geo_logs_success(self) -> None:
        """Nip66GeoLogs success case."""
        logs = Nip66GeoLogs(success=True, reason=None)
        assert logs.success is True

    def test_geo_logs_failure(self) -> None:
        """Nip66GeoLogs failure case."""
        logs = Nip66GeoLogs(success=False, reason="IP not found")
        assert logs.success is False
        assert logs.reason == "IP not found"

    def test_net_logs_success(self) -> None:
        """Nip66NetLogs success case."""
        logs = Nip66NetLogs(success=True, reason=None)
        assert logs.success is True

    def test_dns_logs_success(self) -> None:
        """Nip66DnsLogs success case."""
        logs = Nip66DnsLogs(success=True, reason=None)
        assert logs.success is True

    def test_dns_logs_failure(self) -> None:
        """Nip66DnsLogs failure case."""
        logs = Nip66DnsLogs(success=False, reason="NXDOMAIN")
        assert logs.success is False
        assert logs.reason == "NXDOMAIN"

    def test_http_logs_success(self) -> None:
        """Nip66HttpLogs success case."""
        logs = Nip66HttpLogs(success=True, reason=None)
        assert logs.success is True

    def test_http_logs_failure(self) -> None:
        """Nip66HttpLogs failure case."""
        logs = Nip66HttpLogs(success=False, reason="connection timeout")
        assert logs.success is False


class TestBaseLogsSerialization:
    """Test BaseLogs to_dict and from_dict methods."""

    def test_to_dict_success(self) -> None:
        """to_dict for success case."""
        logs = Nip66SslLogs(success=True, reason=None)
        d = logs.to_dict()
        assert d == {"success": True}
        assert "reason" not in d

    def test_to_dict_failure(self) -> None:
        """to_dict for failure case."""
        logs = Nip66SslLogs(success=False, reason="error message")
        d = logs.to_dict()
        assert d == {"success": False, "reason": "error message"}

    def test_from_dict_success(self) -> None:
        """from_dict for success case."""
        data = {"success": True, "reason": None}
        logs = Nip66GeoLogs.from_dict(data)
        assert logs.success is True
        assert logs.reason is None

    def test_from_dict_failure(self) -> None:
        """from_dict for failure case."""
        data = {"success": False, "reason": "lookup failed"}
        logs = Nip66NetLogs.from_dict(data)
        assert logs.success is False
        assert logs.reason == "lookup failed"
