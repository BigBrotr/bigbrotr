"""Unit tests for services.common.constants module.

Tests:
- ServiceName - StrEnum of canonical service identifiers
- DataType - StrEnum of service data type identifiers
"""

from enum import StrEnum

from services.common.constants import DataType, ServiceName


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
# DataType Tests
# =============================================================================


class TestDataTypeValues:
    """Tests for DataType enum member values."""

    def test_candidate_value(self) -> None:
        assert DataType.CANDIDATE == "candidate"

    def test_cursor_value(self) -> None:
        assert DataType.CURSOR == "cursor"

    def test_checkpoint_value(self) -> None:
        assert DataType.CHECKPOINT == "checkpoint"


class TestDataTypeProperties:
    """Tests for DataType enum type behavior."""

    def test_is_strenum(self) -> None:
        assert issubclass(DataType, StrEnum)

    def test_member_count(self) -> None:
        assert len(DataType) == 3

    def test_str_comparison(self) -> None:
        assert DataType.CANDIDATE == "candidate"
        assert DataType.CURSOR == "cursor"

    def test_usable_as_dict_key(self) -> None:
        d = {DataType.CANDIDATE: "pending", DataType.CURSOR: "active"}
        assert d["candidate"] == "pending"

    def test_usable_in_fstring(self) -> None:
        assert f"type={DataType.CHECKPOINT}" == "type=checkpoint"

    def test_iteration_yields_all_members(self) -> None:
        types = list(DataType)
        assert len(types) == 3
        assert DataType.CANDIDATE in types
        assert DataType.CHECKPOINT in types
