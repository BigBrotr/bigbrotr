"""Unit tests for the ServiceState model and ServiceStateType enum."""

import json
from dataclasses import FrozenInstanceError
from enum import StrEnum

import pytest

from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateDbParams, ServiceStateType


# =============================================================================
# ServiceStateType Tests
# =============================================================================


class TestServiceStateType:
    """ServiceStateType StrEnum."""

    def test_members(self):
        assert len(ServiceStateType) == 2
        assert set(ServiceStateType) == {
            ServiceStateType.CHECKPOINT,
            ServiceStateType.CURSOR,
        }

    def test_values(self):
        assert ServiceStateType.CHECKPOINT == "checkpoint"
        assert ServiceStateType.CURSOR == "cursor"

    def test_is_str_enum(self):
        assert issubclass(ServiceStateType, StrEnum)
        assert isinstance(ServiceStateType.CHECKPOINT, StrEnum)

    def test_construct_from_value(self):
        assert ServiceStateType("checkpoint") is ServiceStateType.CHECKPOINT
        assert ServiceStateType("cursor") is ServiceStateType.CURSOR


# =============================================================================
# Construction Tests
# =============================================================================


class TestConstruction:
    """ServiceState construction and initialization."""

    def test_with_enum_values(self):
        state = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="wss://relay.damus.io",
            state_value={"last_seen": 1700000000},
        )
        assert state.service_name == "finder"
        assert state.state_type == "cursor"
        assert state.state_key == "wss://relay.damus.io"
        assert state.state_value == {"last_seen": 1700000000}

    def test_string_coercion(self):
        state = ServiceState(
            service_name="finder",  # type: ignore[arg-type]
            state_type="cursor",  # type: ignore[arg-type]
            state_key="wss://relay.damus.io",
            state_value={},
        )
        assert state.service_name == "finder"
        assert state.state_type == "cursor"

    def test_custom_service_name_allowed(self):
        state = ServiceState(
            service_name="custom_service",
            state_type=ServiceStateType.CURSOR,
            state_key="key",
            state_value={},
        )
        assert state.service_name == "custom_service"

    def test_custom_state_type_allowed(self):
        state = ServiceState(
            service_name=ServiceName.FINDER,
            state_type="custom_type",
            state_key="key",
            state_value={},
        )
        assert state.state_type == "custom_type"

    def test_frozen(self):
        state = ServiceState(
            service_name=ServiceName.MONITOR,
            state_type=ServiceStateType.CHECKPOINT,
            state_key="batch_1",
            state_value={"done": True},
        )
        with pytest.raises(FrozenInstanceError):
            state.state_key = "batch_2"  # type: ignore[misc]

    def test_empty_state_value(self):
        state = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="key",
            state_value={},
        )
        assert state.state_value == {}


# =============================================================================
# to_db_params Tests
# =============================================================================


class TestToDbParams:
    """ServiceState.to_db_params() for database persistence."""

    def test_returns_service_state_db_params(self):
        state = ServiceState(
            service_name=ServiceName.SYNCHRONIZER,
            state_type=ServiceStateType.CURSOR,
            state_key="wss://relay.damus.io",
            state_value={"last_seen": 1700000000},
        )
        result = state.to_db_params()
        assert isinstance(result, ServiceStateDbParams)

    def test_field_values(self):
        state = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CHECKPOINT,
            state_key="wss://nos.lol",
            state_value={"source": "nip65"},
        )
        params = state.to_db_params()
        assert params.service_name == "finder"
        assert params.state_type == "checkpoint"
        assert params.state_key == "wss://nos.lol"
        assert params.state_value == '{"source": "nip65"}'

    def test_state_value_valid_json(self):
        state = ServiceState(
            service_name=ServiceName.MONITOR,
            state_type=ServiceStateType.CHECKPOINT,
            state_key="key",
            state_value={"nested": {"deep": "value"}, "list": [1, 2, 3]},
        )
        params = state.to_db_params()
        parsed = json.loads(params.state_value)
        assert parsed["nested"]["deep"] == "value"
        assert parsed["list"] == [1, 2, 3]

    def test_caching(self):
        state = ServiceState(
            service_name=ServiceName.VALIDATOR,
            state_type=ServiceStateType.CURSOR,
            state_key="batch_pos",
            state_value={"index": 42},
        )
        assert state.to_db_params() is state.to_db_params()

    def test_empty_state_value_serializes(self):
        state = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="key",
            state_value={},
        )
        assert state.to_db_params().state_value == "{}"


# =============================================================================
# Sanitization Tests
# =============================================================================


class TestSanitization:
    """state_value validation plus normalization via normalize_json_data."""

    def test_none_values_preserved(self):
        state = ServiceState(
            service_name=ServiceName.MONITOR,
            state_type=ServiceStateType.CURSOR,
            state_key="key",
            state_value={"keep": "value", "remove": None},
        )
        assert state.state_value["keep"] == "value"
        assert state.state_value["remove"] is None

    def test_empty_containers_preserved(self):
        state = ServiceState(
            service_name=ServiceName.MONITOR,
            state_type=ServiceStateType.CURSOR,
            state_key="key",
            state_value={"keep": "value", "empty_dict": {}, "empty_list": []},
        )
        assert dict(state.state_value["empty_dict"]) == {}
        assert tuple(state.state_value["empty_list"]) == ()

    def test_null_bytes_in_value_rejected(self):
        with pytest.raises(ValueError, match="null bytes"):
            ServiceState(
                service_name=ServiceName.MONITOR,
                state_type=ServiceStateType.CURSOR,
                state_key="key",
                state_value={"text": "bad\x00value"},
            )

    def test_null_bytes_in_key_rejected(self):
        with pytest.raises(ValueError, match="null bytes"):
            ServiceState(
                service_name=ServiceName.MONITOR,
                state_type=ServiceStateType.CURSOR,
                state_key="key",
                state_value={"bad\x00key": "value"},
            )

    def test_non_string_keys_rejected(self):
        with pytest.raises(TypeError, match="state_value keys must be str, got int"):
            ServiceState(
                service_name=ServiceName.MONITOR,
                state_type=ServiceStateType.CURSOR,
                state_key="key",
                state_value={1: "value", "ok": "value"},
            )

    def test_non_serializable_value_rejected(self):
        class Custom:
            pass

        with pytest.raises(TypeError, match="state_value contains unsupported type Custom"):
            ServiceState(
                service_name=ServiceName.MONITOR,
                state_type=ServiceStateType.CURSOR,
                state_key="key",
                state_value={"ok": "value", "bad": Custom()},
            )


# =============================================================================
# Type Validation Tests
# =============================================================================


class TestTypeValidation:
    """Runtime type validation in __post_init__."""

    def test_state_key_non_string_rejected(self):
        with pytest.raises(TypeError, match="state_key must be a str"):
            ServiceState(
                service_name=ServiceName.MONITOR,
                state_type=ServiceStateType.CURSOR,
                state_key=123,  # type: ignore[arg-type]
                state_value={"key": "value"},
            )

    def test_state_key_empty_rejected(self):
        with pytest.raises(ValueError, match="state_key must not be empty"):
            ServiceState(
                service_name=ServiceName.MONITOR,
                state_type=ServiceStateType.CURSOR,
                state_key="",
                state_value={},
            )

    def test_state_key_null_bytes_rejected(self):
        with pytest.raises(ValueError, match="state_key contains null bytes"):
            ServiceState(
                service_name=ServiceName.MONITOR,
                state_type=ServiceStateType.CURSOR,
                state_key="key\x00here",
                state_value={},
            )

    def test_state_value_non_dict_rejected(self):
        with pytest.raises(TypeError, match="state_value must be a Mapping"):
            ServiceState(
                service_name=ServiceName.MONITOR,
                state_type=ServiceStateType.CURSOR,
                state_key="test",
                state_value=[1, 2, 3],  # type: ignore[arg-type]
            )

    def test_state_value_string_rejected(self):
        with pytest.raises(TypeError, match="state_value must be a Mapping"):
            ServiceState(
                service_name=ServiceName.MONITOR,
                state_type=ServiceStateType.CURSOR,
                state_key="test",
                state_value="not a dict",  # type: ignore[arg-type]
            )


# =============================================================================
# Immutability Tests
# =============================================================================


class TestImmutability:
    """Deep immutability of state_value."""

    def test_state_value_immutable(self):
        state = ServiceState(
            service_name=ServiceName.MONITOR,
            state_type=ServiceStateType.CURSOR,
            state_key="test",
            state_value={"key": "value"},
        )
        with pytest.raises(TypeError):
            state.state_value["key"] = "modified"  # type: ignore[index]

    def test_state_value_nested_immutable(self):
        state = ServiceState(
            service_name=ServiceName.MONITOR,
            state_type=ServiceStateType.CURSOR,
            state_key="test",
            state_value={"nested": {"inner": "value"}},
        )
        with pytest.raises(TypeError):
            state.state_value["nested"]["inner"] = "modified"  # type: ignore[index]

    def test_original_dict_not_affected(self):
        original = {"key": "value"}
        state = ServiceState(
            service_name=ServiceName.MONITOR,
            state_type=ServiceStateType.CURSOR,
            state_key="test",
            state_value=original,
        )
        original["key"] = "modified"
        assert state.state_value["key"] == "value"

    def test_new_attribute_blocked(self):
        state = ServiceState(
            service_name=ServiceName.MONITOR,
            state_type=ServiceStateType.CHECKPOINT,
            state_key="test",
            state_value={},
        )
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            state.new_attr = "value"  # type: ignore[attr-defined]


# =============================================================================
# Equality Tests
# =============================================================================


class TestEquality:
    """Equality behavior."""

    def test_equal(self):
        s1 = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="key",
            state_value={"a": 1},
        )
        s2 = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="key",
            state_value={"a": 1},
        )
        assert s1 == s2

    def test_different_service_name(self):
        s1 = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="key",
            state_value={},
        )
        s2 = ServiceState(
            service_name=ServiceName.MONITOR,
            state_type=ServiceStateType.CURSOR,
            state_key="key",
            state_value={},
        )
        assert s1 != s2

    def test_different_state_type(self):
        s1 = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="key",
            state_value={},
        )
        s2 = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CHECKPOINT,
            state_key="key",
            state_value={},
        )
        assert s1 != s2

    def test_different_state_key(self):
        s1 = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="key1",
            state_value={},
        )
        s2 = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="key2",
            state_value={},
        )
        assert s1 != s2
