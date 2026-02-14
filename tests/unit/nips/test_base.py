"""Unit tests for BaseData, BaseMetadata, BaseLogs, BaseNip, BaseNipSelection, BaseNipOptions."""

import pytest
from pydantic import ValidationError

from bigbrotr.models.constants import DEFAULT_TIMEOUT
from bigbrotr.models.relay import Relay
from bigbrotr.nips.base import (
    BaseData,
    BaseLogs,
    BaseMetadata,
    BaseNip,
    BaseNipOptions,
    BaseNipSelection,
)
from bigbrotr.nips.nip11 import Nip11, Nip11Options, Nip11Selection
from bigbrotr.nips.nip66 import Nip66, Nip66Options, Nip66Selection
from bigbrotr.nips.parsing import FieldSpec


# =============================================================================
# DEFAULT_TIMEOUT Tests
# =============================================================================


class TestDefaultTimeout:
    """Test DEFAULT_TIMEOUT constant."""

    def test_value(self):
        """DEFAULT_TIMEOUT is 10.0 seconds."""
        assert DEFAULT_TIMEOUT == 10.0

    def test_type(self):
        """DEFAULT_TIMEOUT is a float."""
        assert isinstance(DEFAULT_TIMEOUT, float)


# =============================================================================
# BaseData Tests
# =============================================================================


class TestBaseDataParse:
    """Test BaseData.parse() method."""

    def test_parse_with_non_dict_returns_empty(self):
        """parse() returns empty dict for non-dict input."""
        assert BaseData.parse("string") == {}
        assert BaseData.parse(123) == {}
        assert BaseData.parse(None) == {}
        assert BaseData.parse([1, 2, 3]) == {}
        assert BaseData.parse((1, 2)) == {}

    def test_parse_with_empty_dict_returns_empty(self):
        """parse() returns empty dict for empty input."""
        assert BaseData.parse({}) == {}

    def test_parse_with_default_field_spec_returns_empty(self):
        """parse() returns empty dict when _FIELD_SPEC is default (no fields defined)."""
        # BaseData has empty _FIELD_SPEC by default
        result = BaseData.parse({"count": 10, "name": "test"})
        assert result == {}


class TestBaseDataSubclass:
    """Test BaseData subclass with custom _FIELD_SPEC."""

    @pytest.fixture
    def data_subclass(self):
        """Create a BaseData subclass with custom fields."""

        class TestData(BaseData):
            _FIELD_SPEC = FieldSpec(
                int_fields=frozenset({"count", "limit"}),
                bool_fields=frozenset({"enabled"}),
                str_fields=frozenset({"name"}),
                str_list_fields=frozenset({"tags"}),
                float_fields=frozenset({"score"}),
                int_list_fields=frozenset({"ids"}),
            )

            count: int | None = None
            limit: int | None = None
            enabled: bool | None = None
            name: str | None = None
            tags: list[str] | None = None
            score: float | None = None
            ids: list[int] | None = None

        return TestData

    def test_parse_valid_data(self, data_subclass):
        """parse() correctly parses valid data."""
        data = {
            "count": 10,
            "limit": 100,
            "enabled": True,
            "name": "Test",
            "tags": ["a", "b"],
            "score": 9.5,
            "ids": [1, 2, 3],
        }
        result = data_subclass.parse(data)
        assert result == {
            "count": 10,
            "limit": 100,
            "enabled": True,
            "name": "Test",
            "tags": ["a", "b"],
            "score": 9.5,
            "ids": [1, 2, 3],
        }

    def test_parse_filters_invalid_types(self, data_subclass):
        """parse() filters out invalid types."""
        data = {
            "count": "not an int",
            "limit": True,  # bool rejected for int
            "enabled": 1,  # int rejected for bool
            "name": 123,  # int rejected for str
            "tags": "not a list",
            "score": "9.5",  # str rejected for float
            "ids": [True, 1, "two"],  # True and "two" filtered
        }
        result = data_subclass.parse(data)
        assert result == {"ids": [1]}

    def test_parse_unknown_fields_ignored(self, data_subclass):
        """parse() ignores unknown fields."""
        data = {"count": 10, "unknown_field": "value"}
        result = data_subclass.parse(data)
        assert result == {"count": 10}

    def test_from_dict_creates_model(self, data_subclass):
        """from_dict() creates model from valid dict."""
        data = {"count": 10, "name": "Test"}
        model = data_subclass.from_dict(data)
        assert model.count == 10
        assert model.name == "Test"
        assert model.limit is None

    def test_from_dict_validates_strictly(self, data_subclass):
        """from_dict() uses Pydantic strict validation."""
        model = data_subclass.from_dict({"count": 10})
        assert model.count == 10

    def test_to_dict_excludes_none(self, data_subclass):
        """to_dict() excludes None values."""
        model = data_subclass(count=10, name="Test")
        d = model.to_dict()
        assert d == {"count": 10, "name": "Test"}
        assert "limit" not in d
        assert "enabled" not in d

    def test_to_dict_empty_model(self, data_subclass):
        """to_dict() returns empty dict for model with all None."""
        model = data_subclass()
        d = model.to_dict()
        assert d == {}

    def test_parse_then_from_dict(self, data_subclass):
        """parse() then from_dict() creates valid model."""
        raw = {"count": "invalid", "limit": 100, "enabled": True, "name": 123}
        parsed = data_subclass.parse(raw)
        model = data_subclass.from_dict(parsed)
        assert model.count is None  # "invalid" was filtered
        assert model.limit == 100
        assert model.enabled is True
        assert model.name is None  # 123 was filtered


class TestBaseDataFrozen:
    """Test BaseData is frozen (immutable)."""

    @pytest.fixture
    def data_subclass(self):
        """Create a simple BaseData subclass."""

        class TestData(BaseData):
            value: int | None = None

        return TestData

    def test_model_is_frozen(self, data_subclass):
        """BaseData models are immutable."""
        model = data_subclass(value=10)
        with pytest.raises(ValidationError):
            model.value = 20


# =============================================================================
# BaseMetadata Tests
# =============================================================================


class TestBaseMetadata:
    """Test BaseMetadata class."""

    @pytest.fixture
    def metadata_subclass(self):
        """Create a BaseMetadata subclass with data and logs."""

        class TestData(BaseData):
            name: str | None = None
            count: int | None = None

            def to_dict(self):
                return {"name": self.name, "count": self.count}

        class TestLogs(BaseLogs):
            pass

        class TestMetadata(BaseMetadata):
            data: TestData
            logs: TestLogs

        return TestMetadata, TestData, TestLogs

    def test_from_dict_creates_model(self, metadata_subclass):
        """from_dict() creates metadata model from valid dict."""
        TestMetadata, _TestData, _TestLogs = metadata_subclass
        raw = {
            "data": {"name": "Test", "count": 10},
            "logs": {"success": True},
        }
        model = TestMetadata.from_dict(raw)
        assert model.data.name == "Test"
        assert model.data.count == 10
        assert model.logs.success is True

    def test_to_dict_calls_nested_to_dict(self, metadata_subclass):
        """to_dict() calls to_dict() on nested objects."""
        TestMetadata, TestData, TestLogs = metadata_subclass
        model = TestMetadata(
            data=TestData(name="Test", count=10),
            logs=TestLogs(success=True),
        )
        d = model.to_dict()
        assert d == {
            "data": {"name": "Test", "count": 10},
            "logs": {"success": True},
        }

    def test_to_dict_excludes_none_values(self, metadata_subclass):
        """to_dict() excludes None values at top level."""

        class TestData(BaseData):
            name: str | None = None

            def to_dict(self):
                return {"name": self.name}

        class TestLogs(BaseLogs):
            pass

        class TestMetadataWithOptional(BaseMetadata):
            data: TestData | None = None
            logs: TestLogs | None = None

        model = TestMetadataWithOptional(
            data=TestData(name="Test"),
            logs=None,
        )
        d = model.to_dict()
        assert d == {"data": {"name": "Test"}}
        assert "logs" not in d

    def test_to_dict_handles_non_to_dict_values(self, metadata_subclass):
        """to_dict() handles values without to_dict() method."""

        class SimpleMetadata(BaseMetadata):
            value: str
            count: int

        model = SimpleMetadata(value="test", count=10)
        d = model.to_dict()
        assert d == {"value": "test", "count": 10}

    def test_model_is_frozen(self, metadata_subclass):
        """BaseMetadata models are immutable."""
        TestMetadata, TestData, TestLogs = metadata_subclass
        model = TestMetadata(
            data=TestData(name="Test"),
            logs=TestLogs(success=True),
        )
        with pytest.raises(ValidationError):
            model.data = TestData(name="Changed")


# =============================================================================
# BaseLogs Tests
# =============================================================================


class TestBaseLogsSuccess:
    """Test BaseLogs with success=True scenarios."""

    def test_success_without_reason(self):
        """success=True without reason is valid."""
        logs = BaseLogs(success=True)
        assert logs.success is True
        assert logs.reason is None

    def test_success_with_none_reason(self):
        """success=True with explicit reason=None is valid."""
        logs = BaseLogs(success=True, reason=None)
        assert logs.success is True
        assert logs.reason is None

    def test_success_with_reason_raises(self):
        """success=True with non-None reason raises ValidationError."""
        with pytest.raises(ValidationError, match="reason must be None when success is True"):
            BaseLogs(success=True, reason="should not be here")


class TestBaseLogsFailure:
    """Test BaseLogs with success=False scenarios."""

    def test_failure_with_reason(self):
        """success=False with reason is valid."""
        logs = BaseLogs(success=False, reason="Connection timeout")
        assert logs.success is False
        assert logs.reason == "Connection timeout"

    def test_failure_without_reason_raises(self):
        """success=False without reason raises ValidationError."""
        with pytest.raises(ValidationError, match="reason is required when success is False"):
            BaseLogs(success=False)

    def test_failure_with_none_reason_raises(self):
        """success=False with explicit reason=None raises ValidationError."""
        with pytest.raises(ValidationError, match="reason is required when success is False"):
            BaseLogs(success=False, reason=None)

    def test_failure_with_empty_reason(self):
        """success=False with empty string reason is valid (string type passes)."""
        logs = BaseLogs(success=False, reason="")
        assert logs.success is False
        assert logs.reason == ""


class TestBaseLogsTypeValidation:
    """Test BaseLogs type validation."""

    def test_non_bool_success_raises(self):
        """Non-bool success value raises ValidationError."""
        with pytest.raises(ValidationError):
            BaseLogs(success="yes")

    def test_int_success_raises(self):
        """Integer success value raises ValidationError (StrictBool)."""
        with pytest.raises(ValidationError):
            BaseLogs(success=1)

    def test_non_str_reason_raises(self):
        """Non-str reason value raises ValidationError."""
        with pytest.raises(ValidationError):
            BaseLogs(success=False, reason=404)


class TestBaseLogsFromDict:
    """Test BaseLogs.from_dict() method."""

    def test_from_dict_success(self):
        """from_dict() creates logs from valid dict."""
        logs = BaseLogs.from_dict({"success": True})
        assert logs.success is True
        assert logs.reason is None

    def test_from_dict_failure(self):
        """from_dict() creates failure logs from valid dict."""
        logs = BaseLogs.from_dict({"success": False, "reason": "error message"})
        assert logs.success is False
        assert logs.reason == "error message"

    def test_from_dict_empty_raises(self):
        """from_dict() with empty dict raises ValidationError."""
        with pytest.raises(ValidationError):
            BaseLogs.from_dict({})

    def test_from_dict_invalid_success_raises(self):
        """from_dict() with invalid success type raises ValidationError."""
        with pytest.raises(ValidationError):
            BaseLogs.from_dict({"success": "yes"})

    def test_from_dict_invalid_reason_raises(self):
        """from_dict() with invalid reason type raises ValidationError."""
        with pytest.raises(ValidationError):
            BaseLogs.from_dict({"success": False, "reason": 404})


class TestBaseLogsToDict:
    """Test BaseLogs.to_dict() method."""

    def test_to_dict_success(self):
        """to_dict() returns dict without reason when success."""
        logs = BaseLogs(success=True)
        d = logs.to_dict()
        assert d == {"success": True}
        assert "reason" not in d

    def test_to_dict_failure(self):
        """to_dict() returns dict with reason when failure."""
        logs = BaseLogs(success=False, reason="error")
        d = logs.to_dict()
        assert d == {"success": False, "reason": "error"}


class TestBaseLogsRoundtrip:
    """Test BaseLogs roundtrip (to_dict -> from_dict)."""

    def test_success_roundtrip(self):
        """to_dict -> from_dict roundtrip preserves success logs."""
        original = BaseLogs(success=True)
        reconstructed = BaseLogs.from_dict(original.to_dict())
        assert reconstructed == original

    def test_failure_roundtrip(self):
        """to_dict -> from_dict roundtrip preserves failure logs."""
        original = BaseLogs(success=False, reason="Connection refused")
        reconstructed = BaseLogs.from_dict(original.to_dict())
        assert reconstructed == original


class TestBaseLogsFrozen:
    """Test BaseLogs is frozen (immutable)."""

    def test_model_is_frozen(self):
        """BaseLogs models are immutable."""
        logs = BaseLogs(success=True)
        with pytest.raises(ValidationError):
            logs.success = False


# =============================================================================
# BaseLogs Subclass Tests
# =============================================================================


class TestBaseLogsSubclass:
    """Test BaseLogs subclass inheritance."""

    @pytest.fixture
    def logs_subclass(self):
        """Create a BaseLogs subclass with additional fields."""

        class ExtendedLogs(BaseLogs):
            elapsed_ms: int | None = None

        return ExtendedLogs

    def test_subclass_inherits_validation(self, logs_subclass):
        """Subclass inherits success/reason semantic validation."""
        logs = logs_subclass(success=True, elapsed_ms=100)
        assert logs.success is True
        assert logs.elapsed_ms == 100

        with pytest.raises(ValidationError, match="reason must be None when success is True"):
            logs_subclass(success=True, reason="error", elapsed_ms=100)

    def test_subclass_to_dict(self, logs_subclass):
        """Subclass to_dict() includes additional fields."""
        logs = logs_subclass(success=False, reason="timeout", elapsed_ms=5000)
        d = logs.to_dict()
        assert d == {"success": False, "reason": "timeout", "elapsed_ms": 5000}

    def test_subclass_to_dict_excludes_none(self, logs_subclass):
        """Subclass to_dict() excludes None values."""
        logs = logs_subclass(success=True)
        d = logs.to_dict()
        assert d == {"success": True}
        assert "elapsed_ms" not in d


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests combining BaseData, BaseMetadata, and BaseLogs."""

    @pytest.fixture
    def complete_model(self):
        """Create a complete metadata model setup."""

        class MyData(BaseData):
            _FIELD_SPEC = FieldSpec(
                int_fields=frozenset({"count"}),
                str_fields=frozenset({"name"}),
            )

            count: int | None = None
            name: str | None = None

        class MyLogs(BaseLogs):
            elapsed_ms: int | None = None

        class MyMetadata(BaseMetadata):
            data: MyData
            logs: MyLogs

        return MyData, MyLogs, MyMetadata

    def test_full_workflow(self, complete_model):
        """Test complete workflow: raw data -> parse -> create -> serialize."""
        MyData, MyLogs, MyMetadata = complete_model

        raw_data = {
            "count": 10,
            "name": "Test",
            "invalid_field": "ignored",
            "count_as_string": "not valid",
        }

        parsed = MyData.parse(raw_data)
        assert parsed == {"count": 10, "name": "Test"}

        data = MyData.from_dict(parsed)
        logs = MyLogs(success=True, elapsed_ms=50)
        metadata = MyMetadata(data=data, logs=logs)

        result = metadata.to_dict()
        assert result == {
            "data": {"count": 10, "name": "Test"},
            "logs": {"success": True, "elapsed_ms": 50},
        }

    def test_failure_workflow(self, complete_model):
        """Test failure workflow: operation fails -> create failure logs."""
        MyData, MyLogs, MyMetadata = complete_model

        data = MyData()
        logs = MyLogs(success=False, reason="Connection timeout", elapsed_ms=10000)
        metadata = MyMetadata(data=data, logs=logs)

        # Serialize
        result = metadata.to_dict()
        assert result == {
            "data": {},
            "logs": {"success": False, "reason": "Connection timeout", "elapsed_ms": 10000},
        }

    def test_roundtrip_workflow(self, complete_model):
        """Test roundtrip: create -> serialize -> deserialize -> compare."""
        MyData, MyLogs, MyMetadata = complete_model

        original = MyMetadata(
            data=MyData(count=42, name="Roundtrip Test"),
            logs=MyLogs(success=True, elapsed_ms=100),
        )

        serialized = original.to_dict()
        reconstructed = MyMetadata.from_dict(serialized)

        assert reconstructed.data.count == original.data.count
        assert reconstructed.data.name == original.data.name
        assert reconstructed.logs.success == original.logs.success
        assert reconstructed.logs.elapsed_ms == original.logs.elapsed_ms


# =============================================================================
# BaseNipSelection Tests
# =============================================================================


class TestBaseNipSelection:
    """Test BaseNipSelection base class."""

    def test_construction(self):
        """BaseNipSelection can be constructed with no fields."""
        selection = BaseNipSelection()
        assert isinstance(selection, BaseNipSelection)

    def test_is_base_model(self):
        """BaseNipSelection is a Pydantic BaseModel."""
        from pydantic import BaseModel

        assert issubclass(BaseNipSelection, BaseModel)


# =============================================================================
# BaseNipOptions Tests
# =============================================================================


class TestBaseNipOptions:
    """Test BaseNipOptions base class."""

    def test_default_allow_insecure(self):
        """Default allow_insecure is False."""
        options = BaseNipOptions()
        assert options.allow_insecure is False

    def test_custom_allow_insecure(self):
        """allow_insecure can be set to True."""
        options = BaseNipOptions(allow_insecure=True)
        assert options.allow_insecure is True

    def test_is_base_model(self):
        """BaseNipOptions is a Pydantic BaseModel."""
        from pydantic import BaseModel

        assert issubclass(BaseNipOptions, BaseModel)


# =============================================================================
# BaseNip Tests
# =============================================================================


class TestBaseNip:
    """Test BaseNip abstract base class."""

    def test_cannot_instantiate_directly(self):
        """BaseNip cannot be instantiated (ABC enforcement)."""
        relay = Relay("wss://relay.example.com")
        with pytest.raises(TypeError):
            BaseNip(relay=relay)

    def test_is_abstract(self):
        """BaseNip has abstract methods."""
        from abc import ABC

        assert issubclass(BaseNip, ABC)

    def test_has_abstract_to_relay_metadata_tuple(self):
        """BaseNip declares to_relay_metadata_tuple as abstract."""
        assert "to_relay_metadata_tuple" in BaseNip.__abstractmethods__

    def test_has_abstract_create(self):
        """BaseNip declares create as abstract."""
        assert "create" in BaseNip.__abstractmethods__


# =============================================================================
# Nip11 Inheritance Tests
# =============================================================================


class TestNip11Inheritance:
    """Test Nip11 inherits from BaseNip."""

    def test_nip11_is_base_nip(self):
        """Nip11 instance is a BaseNip."""
        relay = Relay("wss://relay.example.com")
        nip11 = Nip11(relay=relay)
        assert isinstance(nip11, BaseNip)

    def test_nip11_has_relay(self):
        """Nip11 inherits relay from BaseNip."""
        relay = Relay("wss://relay.example.com")
        nip11 = Nip11(relay=relay)
        assert nip11.relay == relay

    def test_nip11_has_generated_at(self):
        """Nip11 inherits generated_at from BaseNip."""
        relay = Relay("wss://relay.example.com")
        nip11 = Nip11(relay=relay)
        assert isinstance(nip11.generated_at, int)
        assert nip11.generated_at > 0

    def test_nip11_is_frozen(self):
        """Nip11 is frozen (inherited from BaseNip)."""
        relay = Relay("wss://relay.example.com")
        nip11 = Nip11(relay=relay)
        with pytest.raises(ValidationError):
            nip11.info = None


# =============================================================================
# Nip66 Inheritance Tests
# =============================================================================


class TestNip66Inheritance:
    """Test Nip66 inherits from BaseNip."""

    def test_nip66_is_base_nip(self):
        """Nip66 instance is a BaseNip."""
        relay = Relay("wss://relay.example.com")
        nip66 = Nip66(relay=relay)
        assert isinstance(nip66, BaseNip)

    def test_nip66_has_relay(self):
        """Nip66 inherits relay from BaseNip."""
        relay = Relay("wss://relay.example.com")
        nip66 = Nip66(relay=relay)
        assert nip66.relay == relay

    def test_nip66_has_generated_at(self):
        """Nip66 inherits generated_at from BaseNip."""
        relay = Relay("wss://relay.example.com")
        nip66 = Nip66(relay=relay)
        assert isinstance(nip66.generated_at, int)
        assert nip66.generated_at > 0

    def test_nip66_is_frozen(self):
        """Nip66 is frozen (inherited from BaseNip)."""
        relay = Relay("wss://relay.example.com")
        nip66 = Nip66(relay=relay)
        with pytest.raises(ValidationError):
            nip66.rtt = None


# =============================================================================
# Selection Inheritance Tests
# =============================================================================


class TestSelectionInheritance:
    """Test Selection classes inherit from BaseNipSelection."""

    def test_nip11_selection_is_base(self):
        """Nip11Selection is a BaseNipSelection."""
        assert issubclass(Nip11Selection, BaseNipSelection)
        selection = Nip11Selection()
        assert isinstance(selection, BaseNipSelection)

    def test_nip66_selection_is_base(self):
        """Nip66Selection is a BaseNipSelection."""
        assert issubclass(Nip66Selection, BaseNipSelection)
        selection = Nip66Selection()
        assert isinstance(selection, BaseNipSelection)


# =============================================================================
# Options Inheritance Tests
# =============================================================================


class TestOptionsInheritance:
    """Test Options classes inherit from BaseNipOptions."""

    def test_nip11_options_is_base(self):
        """Nip11Options is a BaseNipOptions."""
        assert issubclass(Nip11Options, BaseNipOptions)
        options = Nip11Options()
        assert isinstance(options, BaseNipOptions)

    def test_nip11_options_inherits_allow_insecure(self):
        """Nip11Options inherits allow_insecure from BaseNipOptions."""
        options = Nip11Options()
        assert options.allow_insecure is False
        options = Nip11Options(allow_insecure=True)
        assert options.allow_insecure is True

    def test_nip66_options_is_base(self):
        """Nip66Options is a BaseNipOptions."""
        assert issubclass(Nip66Options, BaseNipOptions)
        options = Nip66Options()
        assert isinstance(options, BaseNipOptions)

    def test_nip66_options_inherits_allow_insecure(self):
        """Nip66Options inherits allow_insecure from BaseNipOptions."""
        options = Nip66Options()
        assert options.allow_insecure is False
        options = Nip66Options(allow_insecure=True)
        assert options.allow_insecure is True
