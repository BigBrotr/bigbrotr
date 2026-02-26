"""Unit tests for the ServiceState model, ServiceStateType enum, and ServiceStateDbParams."""

from dataclasses import FrozenInstanceError
from enum import StrEnum

import pytest

from bigbrotr.models.constants import ServiceName
from bigbrotr.models.service_state import ServiceState, ServiceStateDbParams, ServiceStateType


# =============================================================================
# ServiceStateType Tests
# =============================================================================


class TestServiceStateType:
    """Test ServiceStateType StrEnum."""

    def test_members(self):
        assert len(ServiceStateType) == 4
        assert set(ServiceStateType) == {
            ServiceStateType.CANDIDATE,
            ServiceStateType.CURSOR,
            ServiceStateType.MONITORING,
            ServiceStateType.PUBLICATION,
        }

    def test_values(self):
        assert ServiceStateType.CANDIDATE == "candidate"
        assert ServiceStateType.CURSOR == "cursor"
        assert ServiceStateType.MONITORING == "monitoring"
        assert ServiceStateType.PUBLICATION == "publication"

    def test_is_str_enum(self):
        assert issubclass(ServiceStateType, StrEnum)
        assert isinstance(ServiceStateType.CANDIDATE, StrEnum)


# =============================================================================
# ServiceStateDbParams Tests
# =============================================================================


class TestServiceStateDbParams:
    """Test ServiceStateDbParams NamedTuple."""

    def test_field_count(self):
        params = ServiceStateDbParams(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="wss://relay.damus.io",
            state_value={"last_seen": 1700000000},
            updated_at=1700000001,
        )
        assert len(params) == 5

    def test_field_order(self):
        params = ServiceStateDbParams(
            service_name=ServiceName.MONITOR,
            state_type=ServiceStateType.MONITORING,
            state_key="batch_42",
            state_value={"progress": 0.75},
            updated_at=1700000500,
        )
        assert params[0] == ServiceName.MONITOR
        assert params[1] == ServiceStateType.MONITORING
        assert params[2] == "batch_42"
        assert params[3] == {"progress": 0.75}
        assert params[4] == 1700000500

    def test_is_named_tuple(self):
        params = ServiceStateDbParams(
            service_name=ServiceName.SEEDER,
            state_type=ServiceStateType.CANDIDATE,
            state_key="wss://example.com",
            state_value={},
            updated_at=0,
        )
        assert isinstance(params, tuple)
        assert hasattr(params, "_fields")


# =============================================================================
# ServiceState Construction Tests
# =============================================================================


class TestServiceStateConstruction:
    """ServiceState construction and initialization."""

    def test_with_enum_values(self):
        state = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CURSOR,
            state_key="wss://relay.damus.io",
            state_value={"last_seen": 1700000000},
            updated_at=1700000001,
        )
        assert state.service_name is ServiceName.FINDER
        assert state.state_type is ServiceStateType.CURSOR
        assert state.state_key == "wss://relay.damus.io"
        assert state.state_value == {"last_seen": 1700000000}
        assert state.updated_at == 1700000001

    def test_string_coercion(self):
        state = ServiceState(
            service_name="finder",  # type: ignore[arg-type]
            state_type="cursor",  # type: ignore[arg-type]
            state_key="wss://relay.damus.io",
            state_value={},
            updated_at=0,
        )
        assert state.service_name is ServiceName.FINDER
        assert state.state_type is ServiceStateType.CURSOR
        assert isinstance(state.service_name, ServiceName)
        assert isinstance(state.state_type, ServiceStateType)

    def test_invalid_service_name(self):
        with pytest.raises(ValueError):
            ServiceState(
                service_name="invalid_service",  # type: ignore[arg-type]
                state_type=ServiceStateType.CURSOR,
                state_key="key",
                state_value={},
                updated_at=0,
            )

    def test_invalid_state_type(self):
        with pytest.raises(ValueError):
            ServiceState(
                service_name=ServiceName.FINDER,
                state_type="invalid_type",  # type: ignore[arg-type]
                state_key="key",
                state_value={},
                updated_at=0,
            )

    def test_frozen(self):
        state = ServiceState(
            service_name=ServiceName.MONITOR,
            state_type=ServiceStateType.MONITORING,
            state_key="batch_1",
            state_value={"done": True},
            updated_at=1700000000,
        )
        with pytest.raises(FrozenInstanceError):
            state.state_key = "batch_2"  # type: ignore[misc]


# =============================================================================
# to_db_params Tests
# =============================================================================


class TestServiceStateToDbParams:
    """ServiceState.to_db_params() for database persistence."""

    def test_returns_service_state_db_params(self):
        state = ServiceState(
            service_name=ServiceName.SYNCHRONIZER,
            state_type=ServiceStateType.CURSOR,
            state_key="wss://relay.damus.io",
            state_value={"last_seen": 1700000000},
            updated_at=1700000001,
        )
        result = state.to_db_params()
        assert isinstance(result, ServiceStateDbParams)

    def test_field_values(self):
        state = ServiceState(
            service_name=ServiceName.FINDER,
            state_type=ServiceStateType.CANDIDATE,
            state_key="wss://nos.lol",
            state_value={"source": "nip65"},
            updated_at=1700000999,
        )
        params = state.to_db_params()
        assert params.service_name is ServiceName.FINDER
        assert params.state_type is ServiceStateType.CANDIDATE
        assert params.state_key == "wss://nos.lol"
        assert params.state_value == '{"source": "nip65"}'
        assert params.updated_at == 1700000999

    def test_caching(self):
        state = ServiceState(
            service_name=ServiceName.VALIDATOR,
            state_type=ServiceStateType.CURSOR,
            state_key="batch_pos",
            state_value={"index": 42},
            updated_at=1700000000,
        )
        assert state.to_db_params() is state.to_db_params()


# =============================================================================
# from_db_params Tests
# =============================================================================


class TestServiceStateFromDbParams:
    """ServiceState.from_db_params() reconstruction."""

    def test_roundtrip(self):
        original = ServiceState(
            service_name=ServiceName.SYNCHRONIZER,
            state_type=ServiceStateType.MONITORING,
            state_key="wss://relay.damus.io",
            state_value={"cursor": 1700000000, "page": 5},
            updated_at=1700000001,
        )
        params = original.to_db_params()
        reconstructed = ServiceState.from_db_params(params)
        assert reconstructed.service_name is original.service_name
        assert reconstructed.state_type is original.state_type
        assert reconstructed.state_key == original.state_key
        assert reconstructed.state_value == original.state_value
        assert reconstructed.updated_at == original.updated_at

    def test_from_raw_strings(self):
        params = ServiceStateDbParams(
            service_name="monitor",  # type: ignore[arg-type]
            state_type="monitoring",  # type: ignore[arg-type]
            state_key="health_batch",
            state_value='{"completed": 100}',
            updated_at=1700000500,
        )
        state = ServiceState.from_db_params(params)
        assert state.service_name is ServiceName.MONITOR
        assert state.state_type is ServiceStateType.MONITORING
        assert isinstance(state.service_name, ServiceName)
        assert isinstance(state.state_type, ServiceStateType)


# =============================================================================
# Type Validation Tests
# =============================================================================


class TestTypeValidation:
    """Runtime type validation in __post_init__."""

    def test_state_key_non_string_rejected(self):
        """state_key must be a str."""
        with pytest.raises(TypeError, match="state_key must be a str"):
            ServiceState(
                service_name=ServiceName.MONITOR,
                state_type=ServiceStateType.CURSOR,
                state_key=123,  # type: ignore[arg-type]
                state_value={"key": "value"},
                updated_at=1700000000,
            )

    def test_state_value_non_dict_rejected(self):
        """state_value must be a dict."""
        with pytest.raises(TypeError, match="state_value must be a Mapping"):
            ServiceState(
                service_name=ServiceName.MONITOR,
                state_type=ServiceStateType.CURSOR,
                state_key="test",
                state_value=[1, 2, 3],  # type: ignore[arg-type]
                updated_at=1700000000,
            )

    def test_state_value_string_rejected(self):
        """state_value must be a dict, not a string."""
        with pytest.raises(TypeError, match="state_value must be a Mapping"):
            ServiceState(
                service_name=ServiceName.MONITOR,
                state_type=ServiceStateType.CURSOR,
                state_key="test",
                state_value="not a dict",  # type: ignore[arg-type]
                updated_at=1700000000,
            )

    def test_updated_at_non_int_rejected(self):
        """updated_at must be an int."""
        with pytest.raises(TypeError, match="updated_at must be an int"):
            ServiceState(
                service_name=ServiceName.MONITOR,
                state_type=ServiceStateType.CURSOR,
                state_key="test",
                state_value={"key": "value"},
                updated_at="abc",  # type: ignore[arg-type]
            )

    def test_updated_at_bool_rejected(self):
        """bool is not accepted as int for updated_at."""
        with pytest.raises(TypeError, match="updated_at must be an int"):
            ServiceState(
                service_name=ServiceName.MONITOR,
                state_type=ServiceStateType.CURSOR,
                state_key="test",
                state_value={"key": "value"},
                updated_at=True,  # type: ignore[arg-type]
            )

    def test_updated_at_negative_rejected(self):
        """updated_at must be non-negative."""
        with pytest.raises(ValueError, match="updated_at must be non-negative"):
            ServiceState(
                service_name=ServiceName.MONITOR,
                state_type=ServiceStateType.CURSOR,
                state_key="test",
                state_value={"key": "value"},
                updated_at=-1,
            )


# =============================================================================
# Immutability Tests
# =============================================================================


class TestImmutability:
    """Deep immutability of state_value."""

    def test_state_value_immutable(self):
        """state_value dict cannot be mutated after construction."""
        state = ServiceState(
            service_name=ServiceName.MONITOR,
            state_type=ServiceStateType.CURSOR,
            state_key="test",
            state_value={"key": "value"},
            updated_at=1700000000,
        )
        with pytest.raises(TypeError):
            state.state_value["key"] = "modified"  # type: ignore[index]

    def test_state_value_nested_immutable(self):
        """Nested dicts in state_value cannot be mutated."""
        state = ServiceState(
            service_name=ServiceName.MONITOR,
            state_type=ServiceStateType.CURSOR,
            state_key="test",
            state_value={"nested": {"inner": "value"}},
            updated_at=1700000000,
        )
        with pytest.raises(TypeError):
            state.state_value["nested"]["inner"] = "modified"  # type: ignore[index]

    def test_original_dict_not_affected(self):
        """Mutating the original dict does not affect the frozen state_value."""
        original = {"key": "value"}
        state = ServiceState(
            service_name=ServiceName.MONITOR,
            state_type=ServiceStateType.CURSOR,
            state_key="test",
            state_value=original,
            updated_at=1700000000,
        )
        original["key"] = "modified"
        assert state.state_value["key"] == "value"
