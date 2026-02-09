"""Unit tests for services.common.constants module.

Tests:
- ServiceName - StrEnum of canonical service identifiers
- StateType - StrEnum of service state type identifiers
"""

from enum import StrEnum

from bigbrotr.services.common.constants import ServiceName, StateType


# =============================================================================
# ServiceName Tests
# =============================================================================


class TestServiceNameValues:
    """Tests for ServiceName enum member values."""

    def test_seeder_value(self) -> None:
        assert ServiceName.SEEDER == "seeder"

    def test_finder_value(self) -> None:
        assert ServiceName.FINDER == "finder"

    def test_validator_value(self) -> None:
        assert ServiceName.VALIDATOR == "validator"

    def test_monitor_value(self) -> None:
        assert ServiceName.MONITOR == "monitor"

    def test_synchronizer_value(self) -> None:
        assert ServiceName.SYNCHRONIZER == "synchronizer"


class TestServiceNameProperties:
    """Tests for ServiceName enum type behavior."""

    def test_is_strenum(self) -> None:
        assert issubclass(ServiceName, StrEnum)

    def test_member_count(self) -> None:
        assert len(ServiceName) == 5

    def test_str_comparison(self) -> None:
        """StrEnum members compare equal to plain strings."""
        assert ServiceName.VALIDATOR == "validator"
        assert ServiceName.VALIDATOR == "validator"

    def test_usable_as_dict_key(self) -> None:
        d = {ServiceName.SEEDER: 1, ServiceName.FINDER: 2}
        assert d["seeder"] == 1
        assert d[ServiceName.FINDER] == 2

    def test_usable_in_fstring(self) -> None:
        assert f"service={ServiceName.MONITOR}" == "service=monitor"

    def test_iteration_yields_all_members(self) -> None:
        names = list(ServiceName)
        assert len(names) == 5
        assert ServiceName.SEEDER in names
        assert ServiceName.SYNCHRONIZER in names


# =============================================================================
# StateType Tests
# =============================================================================


class TestStateTypeValues:
    """Tests for StateType enum member values."""

    def test_candidate_value(self) -> None:
        assert StateType.CANDIDATE == "candidate"

    def test_cursor_value(self) -> None:
        assert StateType.CURSOR == "cursor"

    def test_checkpoint_value(self) -> None:
        assert StateType.CHECKPOINT == "checkpoint"


class TestStateTypeProperties:
    """Tests for StateType enum type behavior."""

    def test_is_strenum(self) -> None:
        assert issubclass(StateType, StrEnum)

    def test_member_count(self) -> None:
        assert len(StateType) == 3

    def test_str_comparison(self) -> None:
        assert StateType.CANDIDATE == "candidate"
        assert StateType.CURSOR == "cursor"

    def test_usable_as_dict_key(self) -> None:
        d = {StateType.CANDIDATE: "pending", StateType.CURSOR: "active"}
        assert d["candidate"] == "pending"

    def test_usable_in_fstring(self) -> None:
        assert f"type={StateType.CHECKPOINT}" == "type=checkpoint"

    def test_iteration_yields_all_members(self) -> None:
        types = list(StateType)
        assert len(types) == 3
        assert StateType.CANDIDATE in types
        assert StateType.CHECKPOINT in types
