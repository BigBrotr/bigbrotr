"""Unit tests for NIP-11 data models (limitation, retention, fees, fetch data)."""

from typing import Any

import pytest
from pydantic import ValidationError

from bigbrotr.nips.nip11 import (
    Nip11InfoData,
    Nip11InfoDataFeeEntry,
    Nip11InfoDataFees,
    Nip11InfoDataLimitation,
    Nip11InfoDataRetentionEntry,
)


# =============================================================================
# Nip11InfoDataLimitation Tests
# =============================================================================


class TestNip11InfoDataLimitationConstructor:
    """Test Nip11InfoDataLimitation constructor validation."""

    def test_constructor_all_defaults(self):
        """Constructor with no arguments creates model with all None values."""
        lim = Nip11InfoDataLimitation()
        assert lim.max_message_length is None
        assert lim.auth_required is None

    def test_constructor_valid_int_fields(self):
        """Constructor accepts valid int values."""
        lim = Nip11InfoDataLimitation(
            max_message_length=65535,
            max_subscriptions=20,
            max_limit=5000,
        )
        assert lim.max_message_length == 65535
        assert lim.max_subscriptions == 20
        assert lim.max_limit == 5000

    def test_constructor_valid_bool_fields(self):
        """Constructor accepts valid bool values."""
        lim = Nip11InfoDataLimitation(
            auth_required=True,
            payment_required=False,
            restricted_writes=True,
        )
        assert lim.auth_required is True
        assert lim.payment_required is False
        assert lim.restricted_writes is True

    def test_constructor_rejects_non_int(self):
        """Constructor raises ValidationError for non-int field."""
        with pytest.raises(ValidationError):
            Nip11InfoDataLimitation(max_message_length="large")

    def test_constructor_rejects_bool_as_int(self):
        """Constructor raises ValidationError for bool in int field (StrictInt)."""
        with pytest.raises(ValidationError):
            Nip11InfoDataLimitation(max_message_length=True)

    def test_constructor_rejects_float_as_int(self):
        """Constructor raises ValidationError for float in int field."""
        with pytest.raises(ValidationError):
            Nip11InfoDataLimitation(max_message_length=65535.0)

    def test_constructor_rejects_non_bool(self):
        """Constructor raises ValidationError for non-bool field."""
        with pytest.raises(ValidationError):
            Nip11InfoDataLimitation(auth_required="yes")

    def test_constructor_rejects_int_as_bool(self):
        """Constructor raises ValidationError for int in bool field (StrictBool)."""
        with pytest.raises(ValidationError):
            Nip11InfoDataLimitation(auth_required=1)


class TestNip11InfoDataLimitationFromDict:
    """Test Nip11InfoDataLimitation.from_dict() method."""

    def test_from_dict_valid(self):
        """from_dict with valid data creates Nip11InfoDataLimitation."""
        lim = Nip11InfoDataLimitation.from_dict(
            {
                "max_message_length": 65535,
                "auth_required": True,
            }
        )
        assert lim.max_message_length == 65535
        assert lim.auth_required is True
        assert lim.max_subscriptions is None

    def test_from_dict_empty(self):
        """from_dict with empty dict creates model with defaults."""
        lim = Nip11InfoDataLimitation.from_dict({})
        assert lim.max_message_length is None

    def test_from_dict_rejects_non_int(self):
        """from_dict raises ValidationError for non-int field."""
        with pytest.raises(ValidationError):
            Nip11InfoDataLimitation.from_dict({"max_limit": "big"})

    def test_from_dict_rejects_non_bool(self):
        """from_dict raises ValidationError for non-bool field."""
        with pytest.raises(ValidationError):
            Nip11InfoDataLimitation.from_dict({"payment_required": 1})


class TestNip11InfoDataLimitationParse:
    """Test Nip11InfoDataLimitation.parse() method."""

    def test_parse_valid_data(self):
        """Valid data is parsed correctly."""
        data = {
            "max_message_length": 65535,
            "auth_required": True,
            "payment_required": False,
        }
        result = Nip11InfoDataLimitation.parse(data)
        assert result == {
            "max_message_length": 65535,
            "auth_required": True,
            "payment_required": False,
        }

    def test_parse_invalid_types_ignored(self):
        """Invalid types are ignored."""
        data = {
            "max_message_length": "not an int",
            "auth_required": "not a bool",
            "unknown_field": 123,
        }
        result = Nip11InfoDataLimitation.parse(data)
        assert result == {}

    def test_parse_bool_not_treated_as_int(self):
        """Boolean values are not treated as integers."""
        data = {"max_message_length": True}
        result = Nip11InfoDataLimitation.parse(data)
        assert result == {}

    def test_parse_int_not_treated_as_bool(self):
        """Integer values are not treated as booleans."""
        data = {"auth_required": 1}
        result = Nip11InfoDataLimitation.parse(data)
        assert result == {}

    def test_parse_non_dict_returns_empty(self):
        """Non-dict input returns empty dict."""
        assert Nip11InfoDataLimitation.parse("string") == {}
        assert Nip11InfoDataLimitation.parse(123) == {}
        assert Nip11InfoDataLimitation.parse(None) == {}
        assert Nip11InfoDataLimitation.parse([1, 2]) == {}

    def test_parse_negative_int_accepted(self):
        """Negative integers are accepted (validation is type-only)."""
        data = {"max_message_length": -100}
        result = Nip11InfoDataLimitation.parse(data)
        assert result == {"max_message_length": -100}

    def test_parse_zero_accepted(self):
        """Zero is accepted for int fields."""
        data = {"min_pow_difficulty": 0}
        result = Nip11InfoDataLimitation.parse(data)
        assert result == {"min_pow_difficulty": 0}


class TestNip11InfoDataLimitationToDict:
    """Test Nip11InfoDataLimitation.to_dict() method."""

    def test_to_dict_excludes_none(self):
        """to_dict returns dict excluding None fields."""
        lim = Nip11InfoDataLimitation(max_message_length=1000)
        d = lim.to_dict()
        assert d["max_message_length"] == 1000
        assert "max_subscriptions" not in d

    def test_to_dict_empty_model(self):
        """to_dict returns empty dict for model with all None."""
        lim = Nip11InfoDataLimitation()
        d = lim.to_dict()
        assert d == {}

    def test_to_dict_all_fields(self):
        """to_dict includes all non-None fields."""
        lim = Nip11InfoDataLimitation(
            max_message_length=65535,
            auth_required=True,
            payment_required=False,
        )
        d = lim.to_dict()
        assert d == {
            "max_message_length": 65535,
            "auth_required": True,
            "payment_required": False,
        }


class TestNip11InfoDataLimitationRoundtrip:
    """Test to_dict -> from_dict roundtrip."""

    def test_roundtrip(self):
        """to_dict -> from_dict roundtrip preserves data."""
        original = Nip11InfoDataLimitation(
            max_message_length=65535,
            max_subscriptions=20,
            auth_required=False,
        )
        reconstructed = Nip11InfoDataLimitation.from_dict(original.to_dict())
        assert reconstructed == original


# =============================================================================
# Nip11InfoDataRetentionEntry Tests
# =============================================================================


class TestNip11InfoDataRetentionEntryConstructor:
    """Test Nip11InfoDataRetentionEntry constructor validation."""

    def test_constructor_all_defaults(self):
        """Constructor with no arguments creates model with all None values."""
        entry = Nip11InfoDataRetentionEntry()
        assert entry.kinds is None
        assert entry.time is None
        assert entry.count is None

    def test_constructor_valid_simple_kinds(self):
        """Constructor accepts list of ints for kinds."""
        entry = Nip11InfoDataRetentionEntry(kinds=[1, 2, 3])
        assert entry.kinds == [1, 2, 3]

    def test_constructor_valid_kind_ranges(self):
        """Constructor accepts tuples for kind ranges."""
        entry = Nip11InfoDataRetentionEntry(kinds=[1, (10000, 19999), 3])
        assert entry.kinds == [1, (10000, 19999), 3]

    def test_constructor_rejects_non_int_time(self):
        """Constructor raises ValidationError for non-int time."""
        with pytest.raises(ValidationError):
            Nip11InfoDataRetentionEntry(kinds=[1], time="3600")

    def test_constructor_rejects_bool_time(self):
        """Constructor raises ValidationError for bool time (StrictInt)."""
        with pytest.raises(ValidationError):
            Nip11InfoDataRetentionEntry(time=True)

    def test_constructor_rejects_bool_in_kinds(self):
        """Constructor raises ValidationError for bool in kinds list."""
        with pytest.raises(ValidationError):
            Nip11InfoDataRetentionEntry(kinds=[True])

    def test_constructor_rejects_invalid_kinds_element(self):
        """Constructor raises ValidationError for invalid kinds element."""
        with pytest.raises(ValidationError):
            Nip11InfoDataRetentionEntry(kinds=[1, "two"])

    def test_constructor_rejects_non_list_kinds(self):
        """Constructor raises ValidationError for non-list kinds."""
        with pytest.raises(ValidationError):
            Nip11InfoDataRetentionEntry(kinds="invalid")

    def test_constructor_rejects_three_element_tuple(self):
        """Constructor raises ValidationError for tuple with wrong length."""
        with pytest.raises(ValidationError):
            Nip11InfoDataRetentionEntry(kinds=[(1, 2, 3)])


class TestNip11InfoDataRetentionEntryParse:
    """Test Nip11InfoDataRetentionEntry.parse() method."""

    def test_parse_valid_data(self):
        """Valid data is parsed correctly."""
        data = {"kinds": [1, 2, 3], "time": 3600, "count": 1000}
        result = Nip11InfoDataRetentionEntry.parse(data)
        assert result == {"kinds": [1, 2, 3], "time": 3600, "count": 1000}

    def test_parse_kind_ranges(self):
        """Kind ranges are parsed correctly (list to tuple conversion)."""
        data = {"kinds": [1, [10, 20], 3]}
        result = Nip11InfoDataRetentionEntry.parse(data)
        assert result == {"kinds": [1, (10, 20), 3]}

    def test_parse_invalid_kinds_filtered(self):
        """Invalid kinds are filtered out."""
        data = {"kinds": [1, "invalid", True, [10, 20], [1, 2, 3]]}
        result = Nip11InfoDataRetentionEntry.parse(data)
        assert result == {"kinds": [1, (10, 20)]}

    def test_parse_empty_kinds_not_included(self):
        """Empty kinds list after filtering is not included."""
        data = {"kinds": ["invalid", True, "string"]}
        result = Nip11InfoDataRetentionEntry.parse(data)
        assert "kinds" not in result

    def test_parse_non_dict_returns_empty(self):
        """Non-dict input returns empty dict."""
        assert Nip11InfoDataRetentionEntry.parse([1, 2, 3]) == {}
        assert Nip11InfoDataRetentionEntry.parse(None) == {}

    def test_parse_bool_in_range_filtered(self):
        """Range with bool element is filtered out."""
        data = {"kinds": [[True, 100]]}
        result = Nip11InfoDataRetentionEntry.parse(data)
        assert result == {}


class TestNip11InfoDataRetentionEntryToDict:
    """Test Nip11InfoDataRetentionEntry.to_dict() method."""

    def test_to_dict_omits_none(self):
        """to_dict omits None values."""
        entry = Nip11InfoDataRetentionEntry(kinds=[1, 2], time=3600, count=None)
        d = entry.to_dict()
        assert d == {"kinds": [1, 2], "time": 3600}
        assert "count" not in d

    def test_to_dict_converts_tuples_to_lists(self):
        """to_dict converts tuples to lists for JSON serialization."""
        entry = Nip11InfoDataRetentionEntry(kinds=[1, (10000, 19999)])
        d = entry.to_dict()
        assert d == {"kinds": [1, [10000, 19999]]}


class TestNip11InfoDataRetentionEntryRoundtrip:
    """Test to_dict -> from_dict roundtrip."""

    def test_roundtrip(self):
        """to_dict -> from_dict roundtrip preserves data."""
        original = Nip11InfoDataRetentionEntry(kinds=[0, 3], time=3600, count=100)
        reconstructed = Nip11InfoDataRetentionEntry.from_dict(original.to_dict())
        assert reconstructed == original


# =============================================================================
# Nip11InfoDataFeeEntry Tests
# =============================================================================


class TestNip11InfoDataFeeEntryConstructor:
    """Test Nip11InfoDataFeeEntry constructor validation."""

    def test_constructor_all_defaults(self):
        """Constructor with no arguments creates model with all None values."""
        entry = Nip11InfoDataFeeEntry()
        assert entry.amount is None
        assert entry.unit is None
        assert entry.period is None
        assert entry.kinds is None

    def test_constructor_valid_values(self):
        """Constructor accepts valid values."""
        entry = Nip11InfoDataFeeEntry(
            amount=1000,
            unit="sats",
            period=2628003,
            kinds=[4],
        )
        assert entry.amount == 1000
        assert entry.unit == "sats"
        assert entry.period == 2628003
        assert entry.kinds == [4]

    def test_constructor_rejects_non_int_amount(self):
        """Constructor raises ValidationError for non-int amount."""
        with pytest.raises(ValidationError):
            Nip11InfoDataFeeEntry(amount="1000", unit="sats")

    def test_constructor_rejects_bool_amount(self):
        """Constructor raises ValidationError for bool amount (StrictInt)."""
        with pytest.raises(ValidationError):
            Nip11InfoDataFeeEntry(amount=True, unit="sats")

    def test_constructor_rejects_bool_in_kinds(self):
        """Constructor raises ValidationError for bool in kinds list."""
        with pytest.raises(ValidationError):
            Nip11InfoDataFeeEntry(amount=100, unit="sats", kinds=[False])

    def test_constructor_rejects_non_str_unit(self):
        """Constructor raises ValidationError for non-str unit."""
        with pytest.raises(ValidationError):
            Nip11InfoDataFeeEntry(amount=1000, unit=42)

    def test_constructor_rejects_invalid_kinds_element(self):
        """Constructor raises ValidationError for non-int in kinds."""
        with pytest.raises(ValidationError):
            Nip11InfoDataFeeEntry(amount=100, unit="sats", kinds=["four"])


class TestNip11InfoDataFeeEntryParse:
    """Test Nip11InfoDataFeeEntry.parse() method."""

    def test_parse_valid_data(self):
        """Valid data is parsed correctly."""
        data = {"amount": 1000, "unit": "msats", "period": 30, "kinds": [1, 2]}
        result = Nip11InfoDataFeeEntry.parse(data)
        assert result == {"amount": 1000, "unit": "msats", "period": 30, "kinds": [1, 2]}

    def test_parse_invalid_types_ignored(self):
        """Invalid types are ignored."""
        data = {"amount": "1000", "unit": 123, "kinds": "not a list"}
        result = Nip11InfoDataFeeEntry.parse(data)
        assert result == {}

    def test_parse_filters_invalid_kinds(self):
        """Invalid kinds elements are filtered out."""
        data = {"amount": 100, "unit": "sats", "kinds": [1, True, "two", 3]}
        result = Nip11InfoDataFeeEntry.parse(data)
        assert result == {"amount": 100, "unit": "sats", "kinds": [1, 3]}


class TestNip11InfoDataFeeEntryToDict:
    """Test Nip11InfoDataFeeEntry.to_dict() method."""

    def test_to_dict_omits_none(self):
        """to_dict omits None values."""
        entry = Nip11InfoDataFeeEntry(amount=100, unit="sats")
        d = entry.to_dict()
        assert d == {"amount": 100, "unit": "sats"}
        assert "period" not in d
        assert "kinds" not in d


class TestNip11InfoDataFeeEntryRoundtrip:
    """Test to_dict -> from_dict roundtrip."""

    def test_roundtrip(self):
        """to_dict -> from_dict roundtrip preserves data."""
        original = Nip11InfoDataFeeEntry(amount=100, unit="msats", kinds=[4])
        reconstructed = Nip11InfoDataFeeEntry.from_dict(original.to_dict())
        assert reconstructed == original


# =============================================================================
# Nip11InfoDataFees Tests
# =============================================================================


class TestNip11InfoDataFeesConstructor:
    """Test Nip11InfoDataFees constructor validation."""

    def test_constructor_all_defaults(self):
        """Constructor with no arguments creates model with all None values."""
        fees = Nip11InfoDataFees()
        assert fees.admission is None
        assert fees.subscription is None
        assert fees.publication is None

    def test_constructor_valid_values(self):
        """Constructor accepts valid values."""
        fees = Nip11InfoDataFees(admission=[Nip11InfoDataFeeEntry(amount=1000, unit="sats")])
        assert fees.admission is not None
        assert len(fees.admission) == 1

    def test_constructor_rejects_non_list(self):
        """Constructor raises ValidationError for non-list field."""
        with pytest.raises(ValidationError):
            Nip11InfoDataFees(admission="invalid")

    def test_constructor_accepts_dict_entries(self):
        """Constructor automatically converts dicts to Nip11InfoDataFeeEntry."""
        fees = Nip11InfoDataFees(admission=[{"amount": 1000}])
        assert fees.admission[0].amount == 1000


class TestNip11InfoDataFeesParse:
    """Test Nip11InfoDataFees.parse() method."""

    def test_parse_valid_data(self):
        """Valid data is parsed correctly."""
        data = {
            "admission": [{"amount": 1000, "unit": "msats"}],
            "subscription": [{"amount": 500, "unit": "msats", "period": 30}],
        }
        result = Nip11InfoDataFees.parse(data)
        assert result == {
            "admission": [{"amount": 1000, "unit": "msats"}],
            "subscription": [{"amount": 500, "unit": "msats", "period": 30}],
        }

    def test_parse_empty_entries_filtered(self):
        """Empty entries are filtered out."""
        data = {"admission": [{"invalid": "data"}, {"amount": 1000, "unit": "msats"}]}
        result = Nip11InfoDataFees.parse(data)
        assert result == {"admission": [{"amount": 1000, "unit": "msats"}]}

    def test_parse_non_list_ignored(self):
        """Non-list values are ignored."""
        data = {"admission": "not a list"}
        result = Nip11InfoDataFees.parse(data)
        assert result == {}

    def test_parse_all_invalid_entries_omits_key(self):
        """Key is omitted if all entries are invalid."""
        data = {"admission": [{"invalid": "data"}]}
        result = Nip11InfoDataFees.parse(data)
        assert "admission" not in result


class TestNip11InfoDataFeesRoundtrip:
    """Test to_dict -> from_dict roundtrip."""

    def test_roundtrip(self):
        """to_dict -> from_dict roundtrip preserves data."""
        original = Nip11InfoDataFees(
            admission=[Nip11InfoDataFeeEntry(amount=1000, unit="sats")],
            subscription=[Nip11InfoDataFeeEntry(amount=5000, unit="sats", period=2628003)],
        )
        reconstructed = Nip11InfoDataFees.from_dict(original.to_dict())
        assert reconstructed == original


# =============================================================================
# Nip11InfoData Tests
# =============================================================================


class TestNip11InfoDataConstructor:
    """Test Nip11InfoData constructor validation."""

    def test_constructor_all_defaults(self):
        """Constructor with no arguments creates model with defaults."""
        data = Nip11InfoData()
        assert data.name is None
        assert isinstance(data.limitation, Nip11InfoDataLimitation)
        assert isinstance(data.fees, Nip11InfoDataFees)

    def test_constructor_valid_values(self):
        """Constructor accepts valid values."""
        data = Nip11InfoData(
            name="Test Relay",
            description="A test relay",
            supported_nips=[1, 11, 42],
        )
        assert data.name == "Test Relay"
        assert data.description == "A test relay"
        assert data.supported_nips == [1, 11, 42]

    def test_constructor_rejects_non_str_name(self):
        """Constructor raises ValidationError for non-str name."""
        with pytest.raises(ValidationError):
            Nip11InfoData(name=123)

    def test_constructor_rejects_bool_in_supported_nips(self):
        """Constructor raises ValidationError for bool in supported_nips."""
        with pytest.raises(ValidationError):
            Nip11InfoData(supported_nips=[True, 11])

    def test_constructor_rejects_non_str_in_tags(self):
        """Constructor raises ValidationError for non-str in tags list."""
        with pytest.raises(ValidationError):
            Nip11InfoData(tags=["valid", 42])

    def test_constructor_accepts_dict_limitation(self):
        """Constructor automatically converts dict to Nip11InfoDataLimitation."""
        data = Nip11InfoData(limitation={"max_message_length": 1000})
        assert data.limitation.max_message_length == 1000

    def test_constructor_accepts_dict_fees(self):
        """Constructor automatically converts dict to Nip11InfoDataFees."""
        data = Nip11InfoData(fees={"admission": [{"amount": 100}]})
        assert data.fees.admission[0].amount == 100

    def test_constructor_accepts_dict_retention_entries(self):
        """Constructor converts dicts to Nip11InfoDataRetentionEntry."""
        data = Nip11InfoData(retention=[{"kinds": [1]}])
        assert data.retention[0].kinds == [1]


class TestNip11InfoDataSelfProperty:
    """Test Nip11InfoData.self property and alias handling."""

    def test_self_property_returns_self_pubkey(self):
        """self property returns self_pubkey value."""
        data = Nip11InfoData(self_pubkey="abc123")
        assert data.self == "abc123"

    def test_self_alias_in_from_dict(self):
        """'self' key in dict maps to self_pubkey field."""
        data = Nip11InfoData.from_dict({"self": "xyz789"})
        assert data.self_pubkey == "xyz789"
        assert data.self == "xyz789"

    def test_self_alias_in_to_dict(self):
        """to_dict outputs 'self' key (via alias)."""
        data = Nip11InfoData(self_pubkey="abc123")
        d = data.to_dict()
        assert "self" in d
        assert d["self"] == "abc123"
        assert "self_pubkey" not in d


class TestNip11InfoDataParse:
    """Test Nip11InfoData.parse() method."""

    def test_parse_valid_data(self):
        """Valid data is parsed correctly."""
        data = {
            "name": "Test Relay",
            "description": "A test relay",
            "supported_nips": [1, 11, 42],
            "limitation": {"max_message_length": 65535},
            "relay_countries": ["US", "DE"],
        }
        result = Nip11InfoData.parse(data)
        assert result["name"] == "Test Relay"
        assert result["description"] == "A test relay"
        assert result["supported_nips"] == [1, 11, 42]
        assert result["limitation"] == {"max_message_length": 65535}
        assert result["relay_countries"] == ["US", "DE"]

    def test_parse_invalid_types_ignored(self):
        """Invalid types are ignored."""
        data = {
            "name": 123,
            "supported_nips": "not a list",
            "relay_countries": [1, 2, 3],
        }
        result = Nip11InfoData.parse(data)
        assert result == {}

    def test_parse_nested_objects(self):
        """Nested objects are parsed correctly."""
        data = {
            "retention": [{"kinds": [1, 2], "time": 3600}],
            "fees": {"admission": [{"amount": 1000, "unit": "msats"}]},
        }
        result = Nip11InfoData.parse(data)
        assert result["retention"] == [{"kinds": [1, 2], "time": 3600}]
        assert result["fees"] == {"admission": [{"amount": 1000, "unit": "msats"}]}

    def test_parse_filters_bools_from_supported_nips(self):
        """Bools are filtered from supported_nips."""
        data = {"supported_nips": [1, True, 11, False, 42]}
        result = Nip11InfoData.parse(data)
        assert result["supported_nips"] == [1, 11, 42]

    def test_parse_filters_non_strings_from_tags(self):
        """Non-strings are filtered from tags."""
        data = {"tags": ["valid", 42, "also valid", None]}
        result = Nip11InfoData.parse(data)
        assert result["tags"] == ["valid", "also valid"]

    def test_parse_self_field(self):
        """'self' field is parsed as string."""
        data = {"self": "abc123def456"}
        result = Nip11InfoData.parse(data)
        assert result["self"] == "abc123def456"

    def test_parse_non_dict_returns_empty(self):
        """Non-dict input returns empty dict."""
        assert Nip11InfoData.parse(None) == {}
        assert Nip11InfoData.parse("string") == {}
        assert Nip11InfoData.parse([1, 2, 3]) == {}

    def test_parse_creates_valid_model(self):
        """Parsed data creates a valid Nip11InfoData model."""
        raw = {
            "name": "Test",
            "invalid_field": "ignored",
            "supported_nips": [1, True, "invalid", 11],
            "limitation": {"max_message_length": "invalid", "auth_required": False},
        }
        parsed = Nip11InfoData.parse(raw)
        model = Nip11InfoData.from_dict(parsed)
        assert model.name == "Test"
        assert model.supported_nips == [1, 11]
        assert model.limitation.auth_required is False
        assert model.limitation.max_message_length is None


class TestNip11InfoDataFromDict:
    """Test Nip11InfoData.from_dict() method."""

    def test_from_dict_valid(self, complete_nip11_data: dict[str, Any]):
        """from_dict with valid data creates Nip11InfoData."""
        data = Nip11InfoData.from_dict(complete_nip11_data)
        assert data.name == "Test Relay"
        assert data.self == "b" * 64
        assert data.limitation.max_message_length == 65535
        assert data.fees.admission is not None
        assert data.retention is not None
        assert len(data.retention) == 3

    def test_from_dict_empty(self):
        """from_dict with empty dict creates defaults."""
        data = Nip11InfoData.from_dict({})
        assert data.name is None
        assert isinstance(data.limitation, Nip11InfoDataLimitation)
        assert isinstance(data.fees, Nip11InfoDataFees)

    def test_from_dict_rejects_non_str_name(self):
        """from_dict raises ValidationError for non-str name."""
        with pytest.raises(ValidationError):
            Nip11InfoData.from_dict({"name": 123})


class TestNip11InfoDataToDict:
    """Test Nip11InfoData.to_dict() method."""

    def test_to_dict(self, complete_nip11_data: dict[str, Any]):
        """to_dict returns serializable dict."""
        data = Nip11InfoData.from_dict(complete_nip11_data)
        d = data.to_dict()
        assert d["name"] == "Test Relay"
        assert d["self"] == "b" * 64
        assert isinstance(d["limitation"], dict)
        assert isinstance(d["fees"], dict)

    def test_to_dict_excludes_none(self):
        """to_dict excludes None values."""
        data = Nip11InfoData(name="Test")
        d = data.to_dict()
        assert "name" in d
        assert "description" not in d


class TestNip11InfoDataRoundtrip:
    """Test to_dict -> from_dict roundtrip."""

    def test_roundtrip(self, complete_nip11_data: dict[str, Any]):
        """to_dict -> from_dict roundtrip preserves data."""
        original = Nip11InfoData.from_dict(complete_nip11_data)
        reconstructed = Nip11InfoData.from_dict(original.to_dict())
        assert reconstructed == original


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestNip11InfoDataEdgeCases:
    """Test edge cases for Nip11InfoData."""

    def test_empty_lists(self):
        """Empty lists are valid."""
        data = Nip11InfoData(
            supported_nips=[],
            relay_countries=[],
            language_tags=[],
            tags=[],
            retention=[],
        )
        assert data.supported_nips == []
        assert data.relay_countries == []

    def test_unicode_values(self, unicode_nip11_data: dict[str, Any]):
        """Unicode values are preserved."""
        data = Nip11InfoData.from_dict(unicode_nip11_data)
        assert data.name == "Relay del Sol"
        assert data.description == "Un relay para todos los nostrichos"
        assert "espanol" in data.tags
        assert "es" in data.language_tags

    def test_very_long_values(self):
        """Very long string values are accepted."""
        long_name = "x" * 10000
        long_description = "y" * 100000
        data = Nip11InfoData(name=long_name, description=long_description)
        assert len(data.name) == 10000
        assert len(data.description) == 100000

    def test_special_characters(self):
        """Special characters are preserved."""
        data = Nip11InfoData(
            name='Test <Relay> & "Quotes"',
            description="Line1\nLine2\tTab",
        )
        assert "<Relay>" in data.name
        assert "\n" in data.description
        assert "\t" in data.description

    def test_large_supported_nips_list(self):
        """Large lists of supported NIPs are handled."""
        nips = list(range(1, 1001))
        data = Nip11InfoData(supported_nips=nips)
        assert len(data.supported_nips) == 1000

    def test_many_retention_entries(self):
        """Many retention entries are handled."""
        entries = [Nip11InfoDataRetentionEntry(kinds=[i]) for i in range(100)]
        data = Nip11InfoData(retention=entries)
        assert len(data.retention) == 100


class TestNip11InfoDataFrozen:
    """Test Nip11InfoData is frozen (immutable)."""

    def test_model_is_frozen(self):
        """Nip11InfoData models are immutable."""
        data = Nip11InfoData(name="Test")
        with pytest.raises(ValidationError):
            data.name = "Changed"

    def test_limitation_is_frozen(self):
        """Nested limitation is also frozen."""
        data = Nip11InfoData(limitation=Nip11InfoDataLimitation(max_message_length=1000))
        with pytest.raises(ValidationError):
            data.limitation.max_message_length = 2000
