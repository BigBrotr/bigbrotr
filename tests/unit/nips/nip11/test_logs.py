"""Unit tests for Nip11InfoLogs model."""

import pytest
from pydantic import ValidationError

from bigbrotr.nips.base import BaseLogs
from bigbrotr.nips.nip11 import Nip11InfoLogs


# =============================================================================
# Inheritance Tests
# =============================================================================


class TestNip11InfoLogsInheritance:
    """Test Nip11InfoLogs inherits from BaseLogs."""

    def test_inherits_from_base_logs(self):
        """Nip11InfoLogs is a subclass of BaseLogs."""
        assert issubclass(Nip11InfoLogs, BaseLogs)

    def test_instance_is_base_logs(self, info_logs_success: Nip11InfoLogs):
        """Nip11InfoLogs instance is also a BaseLogs instance."""
        assert isinstance(info_logs_success, BaseLogs)

    def test_inherits_success_field(self):
        """Nip11InfoLogs inherits success field from BaseLogs."""
        logs = Nip11InfoLogs(success=True)
        assert hasattr(logs, "success")
        assert logs.success is True

    def test_inherits_reason_field(self):
        """Nip11InfoLogs inherits reason field from BaseLogs."""
        logs = Nip11InfoLogs(success=False, reason="error")
        assert hasattr(logs, "reason")
        assert logs.reason == "error"

    def test_inherits_from_dict_method(self):
        """Nip11InfoLogs inherits from_dict class method."""
        logs = Nip11InfoLogs.from_dict({"success": True})
        assert logs.success is True

    def test_inherits_to_dict_method(self):
        """Nip11InfoLogs inherits to_dict method."""
        logs = Nip11InfoLogs(success=True)
        d = logs.to_dict()
        assert d == {"success": True}


# =============================================================================
# Semantic Validation Tests
# =============================================================================


class TestNip11InfoLogsSemanticValidation:
    """Test success/reason semantic validation."""

    def test_success_true_without_reason_is_valid(self):
        """success=True without reason is valid."""
        logs = Nip11InfoLogs(success=True)
        assert logs.success is True
        assert logs.reason is None

    def test_success_true_with_none_reason_is_valid(self):
        """success=True with explicit reason=None is valid."""
        logs = Nip11InfoLogs(success=True, reason=None)
        assert logs.success is True
        assert logs.reason is None

    def test_success_true_with_reason_raises(self):
        """success=True with non-None reason raises ValidationError."""
        with pytest.raises(ValidationError, match="reason must be None when success is True"):
            Nip11InfoLogs(success=True, reason="should fail")

    def test_success_false_with_reason_is_valid(self):
        """success=False with reason is valid."""
        logs = Nip11InfoLogs(success=False, reason="HTTP 404")
        assert logs.success is False
        assert logs.reason == "HTTP 404"

    def test_success_false_without_reason_raises(self):
        """success=False without reason raises ValidationError."""
        with pytest.raises(ValidationError, match="reason is required when success is False"):
            Nip11InfoLogs(success=False)

    def test_success_false_with_none_reason_raises(self):
        """success=False with explicit reason=None raises ValidationError."""
        with pytest.raises(ValidationError, match="reason is required when success is False"):
            Nip11InfoLogs(success=False, reason=None)

    def test_success_false_with_empty_string_reason_raises(self):
        """success=False with empty string reason raises (empty is not meaningful)."""
        with pytest.raises(ValidationError, match="reason is required when success is False"):
            Nip11InfoLogs(success=False, reason="")


# =============================================================================
# Constructor Type Validation Tests
# =============================================================================


class TestNip11InfoLogsConstructorValidation:
    """Test constructor type validation."""

    def test_constructor_requires_success(self):
        """Constructor requires success field (no default)."""
        with pytest.raises(ValidationError):
            Nip11InfoLogs()

    def test_constructor_rejects_non_bool_success(self):
        """Constructor raises ValidationError if success is not bool."""
        with pytest.raises(ValidationError):
            Nip11InfoLogs(success="yes")

    def test_constructor_rejects_int_success(self):
        """Constructor raises ValidationError if success is int (StrictBool)."""
        with pytest.raises(ValidationError):
            Nip11InfoLogs(success=1)

    def test_constructor_rejects_zero_success(self):
        """Constructor raises ValidationError if success is 0 (StrictBool)."""
        with pytest.raises(ValidationError):
            Nip11InfoLogs(success=0)

    def test_constructor_rejects_non_str_reason(self):
        """Constructor raises ValidationError if reason is not str."""
        with pytest.raises(ValidationError):
            Nip11InfoLogs(success=False, reason=404)

    def test_constructor_rejects_list_reason(self):
        """Constructor raises ValidationError if reason is a list."""
        with pytest.raises(ValidationError):
            Nip11InfoLogs(success=False, reason=["error", "message"])


# =============================================================================
# from_dict Tests
# =============================================================================


class TestNip11InfoLogsFromDict:
    """Test Nip11InfoLogs.from_dict() method."""

    def test_from_dict_success(self):
        """from_dict with success=True creates valid logs."""
        logs = Nip11InfoLogs.from_dict({"success": True})
        assert logs.success is True
        assert logs.reason is None

    def test_from_dict_failure(self):
        """from_dict with success=False and reason creates valid logs."""
        logs = Nip11InfoLogs.from_dict({"success": False, "reason": "HTTP 404"})
        assert logs.success is False
        assert logs.reason == "HTTP 404"

    def test_from_dict_empty_raises(self):
        """from_dict with empty dict raises ValidationError (success required)."""
        with pytest.raises(ValidationError):
            Nip11InfoLogs.from_dict({})

    def test_from_dict_rejects_non_bool_success(self):
        """from_dict raises ValidationError for non-bool success."""
        with pytest.raises(ValidationError):
            Nip11InfoLogs.from_dict({"success": "yes"})

    def test_from_dict_rejects_non_str_reason(self):
        """from_dict raises ValidationError for non-str reason."""
        with pytest.raises(ValidationError):
            Nip11InfoLogs.from_dict({"success": False, "reason": 404})

    def test_from_dict_rejects_reason_when_success_true(self):
        """from_dict raises ValidationError when reason set with success=True."""
        with pytest.raises(ValidationError, match="reason must be None when success is True"):
            Nip11InfoLogs.from_dict({"success": True, "reason": "should fail"})

    def test_from_dict_ignores_extra_fields(self):
        """from_dict ignores extra fields not in the model."""
        logs = Nip11InfoLogs.from_dict({"success": True, "extra_field": "ignored"})
        assert logs.success is True
        assert not hasattr(logs, "extra_field")


# =============================================================================
# to_dict Tests
# =============================================================================


class TestNip11InfoLogsToDict:
    """Test Nip11InfoLogs.to_dict() method."""

    def test_to_dict_success_excludes_reason(self):
        """to_dict returns dict without reason when success=True."""
        logs = Nip11InfoLogs(success=True)
        d = logs.to_dict()
        assert d == {"success": True}
        assert "reason" not in d

    def test_to_dict_failure_includes_reason(self):
        """to_dict returns dict with reason when success=False."""
        logs = Nip11InfoLogs(success=False, reason="timeout")
        d = logs.to_dict()
        assert d == {"success": False, "reason": "timeout"}

    def test_to_dict_empty_reason_raises(self):
        """Empty string reason is rejected at construction."""
        with pytest.raises(ValidationError, match="reason is required when success is False"):
            Nip11InfoLogs(success=False, reason="")


# =============================================================================
# Roundtrip Tests
# =============================================================================


class TestNip11InfoLogsRoundtrip:
    """Test to_dict -> from_dict roundtrip serialization."""

    def test_success_roundtrip(self):
        """to_dict -> from_dict roundtrip preserves success logs."""
        original = Nip11InfoLogs(success=True)
        reconstructed = Nip11InfoLogs.from_dict(original.to_dict())
        assert reconstructed == original

    def test_failure_roundtrip(self):
        """to_dict -> from_dict roundtrip preserves failure logs."""
        original = Nip11InfoLogs(success=False, reason="Connection refused")
        reconstructed = Nip11InfoLogs.from_dict(original.to_dict())
        assert reconstructed == original

    def test_empty_reason_roundtrip_rejected(self):
        """Empty string reason is rejected at construction."""
        with pytest.raises(ValidationError, match="reason is required when success is False"):
            Nip11InfoLogs(success=False, reason="")


# =============================================================================
# Frozen Model Tests
# =============================================================================


class TestNip11InfoLogsFrozen:
    """Test Nip11InfoLogs is frozen (immutable)."""

    def test_model_is_frozen(self):
        """Nip11InfoLogs models are immutable."""
        logs = Nip11InfoLogs(success=True)
        with pytest.raises(ValidationError):
            logs.success = False

    def test_cannot_modify_reason(self):
        """Cannot modify reason field after creation."""
        logs = Nip11InfoLogs(success=False, reason="original")
        with pytest.raises(ValidationError):
            logs.reason = "modified"

    def test_cannot_add_new_attribute(self):
        """Cannot add new attributes to frozen model."""
        logs = Nip11InfoLogs(success=True)
        with pytest.raises(ValidationError):
            logs.new_field = "value"


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestNip11InfoLogsEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_long_reason(self):
        """Very long reason string is accepted."""
        long_reason = "x" * 10000
        logs = Nip11InfoLogs(success=False, reason=long_reason)
        assert logs.reason == long_reason
        assert len(logs.to_dict()["reason"]) == 10000

    def test_unicode_reason(self):
        """Unicode characters in reason are preserved."""
        reason = "Error: conexion rechazada"
        logs = Nip11InfoLogs(success=False, reason=reason)
        assert logs.reason == reason

    def test_special_characters_in_reason(self):
        """Special characters in reason are preserved."""
        reason = 'Error: <html>&amp;\n\t"quotes"'
        logs = Nip11InfoLogs(success=False, reason=reason)
        assert logs.reason == reason

    def test_newlines_in_reason(self):
        """Newlines in reason are preserved."""
        reason = "Line 1\nLine 2\nLine 3"
        logs = Nip11InfoLogs(success=False, reason=reason)
        assert logs.reason == reason
        assert "\n" in logs.to_dict()["reason"]

    def test_equality_comparison(self):
        """Two logs with same values are equal."""
        logs1 = Nip11InfoLogs(success=False, reason="error")
        logs2 = Nip11InfoLogs(success=False, reason="error")
        assert logs1 == logs2

    def test_inequality_different_reason(self):
        """Two logs with different reasons are not equal."""
        logs1 = Nip11InfoLogs(success=False, reason="error1")
        logs2 = Nip11InfoLogs(success=False, reason="error2")
        assert logs1 != logs2

    def test_hash_equality(self):
        """Two equal logs have the same hash."""
        logs1 = Nip11InfoLogs(success=True)
        logs2 = Nip11InfoLogs(success=True)
        assert hash(logs1) == hash(logs2)

    def test_can_use_in_set(self):
        """Logs can be used in sets (hashable)."""
        logs1 = Nip11InfoLogs(success=True)
        logs2 = Nip11InfoLogs(success=False, reason="error")
        logs_set = {logs1, logs2}
        assert len(logs_set) == 2
