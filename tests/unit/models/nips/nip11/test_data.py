"""Unit tests for NIP-11 data models (limitation, retention, fees, fetch data)."""

from typing import Any

import pytest
from pydantic import ValidationError

from models.nips.nip11 import (
    Nip11FetchData,
    Nip11FetchDataFeeEntry,
    Nip11FetchDataFees,
    Nip11FetchDataLimitation,
    Nip11FetchDataRetentionEntry,
)


# =============================================================================
# Nip11FetchDataLimitation Tests
# =============================================================================


class TestNip11FetchDataLimitationConstructor:
    """Test Nip11FetchDataLimitation constructor validation."""

    def test_constructor_all_defaults(self):
        """Constructor with no arguments creates model with all None values."""
        lim = Nip11FetchDataLimitation()
        assert lim.max_message_length is None
        assert lim.auth_required is None

    def test_constructor_valid_int_fields(self):
        """Constructor accepts valid int values."""
        lim = Nip11FetchDataLimitation(
            max_message_length=65535,
            max_subscriptions=20,
            max_limit=5000,
        )
        assert lim.max_message_length == 65535
        assert lim.max_subscriptions == 20
        assert lim.max_limit == 5000

    def test_constructor_valid_bool_fields(self):
        """Constructor accepts valid bool values."""
        lim = Nip11FetchDataLimitation(
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
            Nip11FetchDataLimitation(max_message_length="large")

    def test_constructor_rejects_bool_as_int(self):
        """Constructor raises ValidationError for bool in int field (StrictInt)."""
        with pytest.raises(ValidationError):
            Nip11FetchDataLimitation(max_message_length=True)

    def test_constructor_rejects_float_as_int(self):
        """Constructor raises ValidationError for float in int field."""
        with pytest.raises(ValidationError):
            Nip11FetchDataLimitation(max_message_length=65535.0)

    def test_constructor_rejects_non_bool(self):
        """Constructor raises ValidationError for non-bool field."""
        with pytest.raises(ValidationError):
            Nip11FetchDataLimitation(auth_required="yes")

    def test_constructor_rejects_int_as_bool(self):
        """Constructor raises ValidationError for int in bool field (StrictBool)."""
        with pytest.raises(ValidationError):
            Nip11FetchDataLimitation(auth_required=1)


class TestNip11FetchDataLimitationFromDict:
    """Test Nip11FetchDataLimitation.from_dict() method."""

    def test_from_dict_valid(self):
        """from_dict with valid data creates Nip11FetchDataLimitation."""
        lim = Nip11FetchDataLimitation.from_dict(
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
        lim = Nip11FetchDataLimitation.from_dict({})
        assert lim.max_message_length is None

    def test_from_dict_rejects_non_int(self):
        """from_dict raises ValidationError for non-int field."""
        with pytest.raises(ValidationError):
            Nip11FetchDataLimitation.from_dict({"max_limit": "big"})

    def test_from_dict_rejects_non_bool(self):
        """from_dict raises ValidationError for non-bool field."""
        with pytest.raises(ValidationError):
            Nip11FetchDataLimitation.from_dict({"payment_required": 1})


class TestNip11FetchDataLimitationParse:
    """Test Nip11FetchDataLimitation.parse() method."""

    def test_parse_valid_data(self):
        """Valid data is parsed correctly."""
        data = {
            "max_message_length": 65535,
            "auth_required": True,
            "payment_required": False,
        }
        result = Nip11FetchDataLimitation.parse(data)
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
        result = Nip11FetchDataLimitation.parse(data)
        assert result == {}

    def test_parse_bool_not_treated_as_int(self):
        """Boolean values are not treated as integers."""
        data = {"max_message_length": True}
        result = Nip11FetchDataLimitation.parse(data)
        assert result == {}

    def test_parse_int_not_treated_as_bool(self):
        """Integer values are not treated as booleans."""
        data = {"auth_required": 1}
        result = Nip11FetchDataLimitation.parse(data)
        assert result == {}

    def test_parse_non_dict_returns_empty(self):
        """Non-dict input returns empty dict."""
        assert Nip11FetchDataLimitation.parse("string") == {}
        assert Nip11FetchDataLimitation.parse(123) == {}
        assert Nip11FetchDataLimitation.parse(None) == {}
        assert Nip11FetchDataLimitation.parse([1, 2]) == {}

    def test_parse_negative_int_accepted(self):
        """Negative integers are accepted (validation is type-only)."""
        data = {"max_message_length": -100}
        result = Nip11FetchDataLimitation.parse(data)
        assert result == {"max_message_length": -100}

    def test_parse_zero_accepted(self):
        """Zero is accepted for int fields."""
        data = {"min_pow_difficulty": 0}
        result = Nip11FetchDataLimitation.parse(data)
        assert result == {"min_pow_difficulty": 0}


class TestNip11FetchDataLimitationToDict:
    """Test Nip11FetchDataLimitation.to_dict() method."""

    def test_to_dict_excludes_none(self):
        """to_dict returns dict excluding None fields."""
        lim = Nip11FetchDataLimitation(max_message_length=1000)
        d = lim.to_dict()
        assert d["max_message_length"] == 1000
        assert "max_subscriptions" not in d

    def test_to_dict_empty_model(self):
        """to_dict returns empty dict for model with all None."""
        lim = Nip11FetchDataLimitation()
        d = lim.to_dict()
        assert d == {}

    def test_to_dict_all_fields(self):
        """to_dict includes all non-None fields."""
        lim = Nip11FetchDataLimitation(
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


class TestNip11FetchDataLimitationRoundtrip:
    """Test to_dict -> from_dict roundtrip."""

    def test_roundtrip(self):
        """to_dict -> from_dict roundtrip preserves data."""
        original = Nip11FetchDataLimitation(
            max_message_length=65535,
            max_subscriptions=20,
            auth_required=False,
        )
        reconstructed = Nip11FetchDataLimitation.from_dict(original.to_dict())
        assert reconstructed == original


# =============================================================================
# Nip11FetchDataRetentionEntry Tests
# =============================================================================


class TestNip11FetchDataRetentionEntryConstructor:
    """Test Nip11FetchDataRetentionEntry constructor validation."""

    def test_constructor_all_defaults(self):
        """Constructor with no arguments creates model with all None values."""
        entry = Nip11FetchDataRetentionEntry()
        assert entry.kinds is None
        assert entry.time is None
        assert entry.count is None

    def test_constructor_valid_simple_kinds(self):
        """Constructor accepts list of ints for kinds."""
        entry = Nip11FetchDataRetentionEntry(kinds=[1, 2, 3])
        assert entry.kinds == [1, 2, 3]

    def test_constructor_valid_kind_ranges(self):
        """Constructor accepts tuples for kind ranges."""
        entry = Nip11FetchDataRetentionEntry(kinds=[1, (10000, 19999), 3])
        assert entry.kinds == [1, (10000, 19999), 3]

    def test_constructor_rejects_non_int_time(self):
        """Constructor raises ValidationError for non-int time."""
        with pytest.raises(ValidationError):
            Nip11FetchDataRetentionEntry(kinds=[1], time="3600")

    def test_constructor_rejects_bool_time(self):
        """Constructor raises ValidationError for bool time (StrictInt)."""
        with pytest.raises(ValidationError):
            Nip11FetchDataRetentionEntry(time=True)

    def test_constructor_rejects_bool_in_kinds(self):
        """Constructor raises ValidationError for bool in kinds list."""
        with pytest.raises(ValidationError):
            Nip11FetchDataRetentionEntry(kinds=[True])

    def test_constructor_rejects_invalid_kinds_element(self):
        """Constructor raises ValidationError for invalid kinds element."""
        with pytest.raises(ValidationError):
            Nip11FetchDataRetentionEntry(kinds=[1, "two"])

    def test_constructor_rejects_non_list_kinds(self):
        """Constructor raises ValidationError for non-list kinds."""
        with pytest.raises(ValidationError):
            Nip11FetchDataRetentionEntry(kinds="invalid")

    def test_constructor_rejects_three_element_tuple(self):
        """Constructor raises ValidationError for tuple with wrong length."""
        with pytest.raises(ValidationError):
            Nip11FetchDataRetentionEntry(kinds=[(1, 2, 3)])


class TestNip11FetchDataRetentionEntryParse:
    """Test Nip11FetchDataRetentionEntry.parse() method."""

    def test_parse_valid_data(self):
        """Valid data is parsed correctly."""
        data = {"kinds": [1, 2, 3], "time": 3600, "count": 1000}
        result = Nip11FetchDataRetentionEntry.parse(data)
        assert result == {"kinds": [1, 2, 3], "time": 3600, "count": 1000}

    def test_parse_kind_ranges(self):
        """Kind ranges are parsed correctly (list to tuple conversion)."""
        data = {"kinds": [1, [10, 20], 3]}
        result = Nip11FetchDataRetentionEntry.parse(data)
        assert result == {"kinds": [1, (10, 20), 3]}

    def test_parse_invalid_kinds_filtered(self):
        """Invalid kinds are filtered out."""
        data = {"kinds": [1, "invalid", True, [10, 20], [1, 2, 3]]}
        result = Nip11FetchDataRetentionEntry.parse(data)
        assert result == {"kinds": [1, (10, 20)]}

    def test_parse_empty_kinds_not_included(self):
        """Empty kinds list after filtering is not included."""
        data = {"kinds": ["invalid", True, "string"]}
        result = Nip11FetchDataRetentionEntry.parse(data)
        assert "kinds" not in result

    def test_parse_non_dict_returns_empty(self):
        """Non-dict input returns empty dict."""
        assert Nip11FetchDataRetentionEntry.parse([1, 2, 3]) == {}
        assert Nip11FetchDataRetentionEntry.parse(None) == {}

    def test_parse_bool_in_range_filtered(self):
        """Range with bool element is filtered out."""
        data = {"kinds": [[True, 100]]}
        result = Nip11FetchDataRetentionEntry.parse(data)
        assert result == {}


class TestNip11FetchDataRetentionEntryToDict:
    """Test Nip11FetchDataRetentionEntry.to_dict() method."""

    def test_to_dict_omits_none(self):
        """to_dict omits None values."""
        entry = Nip11FetchDataRetentionEntry(kinds=[1, 2], time=3600, count=None)
        d = entry.to_dict()
        assert d == {"kinds": [1, 2], "time": 3600}
        assert "count" not in d

    def test_to_dict_converts_tuples_to_lists(self):
        """to_dict converts tuples to lists for JSON serialization."""
        entry = Nip11FetchDataRetentionEntry(kinds=[1, (10000, 19999)])
        d = entry.to_dict()
        assert d == {"kinds": [1, [10000, 19999]]}


class TestNip11FetchDataRetentionEntryRoundtrip:
    """Test to_dict -> from_dict roundtrip."""

    def test_roundtrip(self):
        """to_dict -> from_dict roundtrip preserves data."""
        original = Nip11FetchDataRetentionEntry(kinds=[0, 3], time=3600, count=100)
        reconstructed = Nip11FetchDataRetentionEntry.from_dict(original.to_dict())
        assert reconstructed == original


# =============================================================================
# Nip11FetchDataFeeEntry Tests
# =============================================================================


class TestNip11FetchDataFeeEntryConstructor:
    """Test Nip11FetchDataFeeEntry constructor validation."""

    def test_constructor_all_defaults(self):
        """Constructor with no arguments creates model with all None values."""
        entry = Nip11FetchDataFeeEntry()
        assert entry.amount is None
        assert entry.unit is None
        assert entry.period is None
        assert entry.kinds is None

    def test_constructor_valid_values(self):
        """Constructor accepts valid values."""
        entry = Nip11FetchDataFeeEntry(
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
            Nip11FetchDataFeeEntry(amount="1000", unit="sats")

    def test_constructor_rejects_bool_amount(self):
        """Constructor raises ValidationError for bool amount (StrictInt)."""
        with pytest.raises(ValidationError):
            Nip11FetchDataFeeEntry(amount=True, unit="sats")

    def test_constructor_rejects_bool_in_kinds(self):
        """Constructor raises ValidationError for bool in kinds list."""
        with pytest.raises(ValidationError):
            Nip11FetchDataFeeEntry(amount=100, unit="sats", kinds=[False])

    def test_constructor_rejects_non_str_unit(self):
        """Constructor raises ValidationError for non-str unit."""
        with pytest.raises(ValidationError):
            Nip11FetchDataFeeEntry(amount=1000, unit=42)

    def test_constructor_rejects_invalid_kinds_element(self):
        """Constructor raises ValidationError for non-int in kinds."""
        with pytest.raises(ValidationError):
            Nip11FetchDataFeeEntry(amount=100, unit="sats", kinds=["four"])


class TestNip11FetchDataFeeEntryParse:
    """Test Nip11FetchDataFeeEntry.parse() method."""

    def test_parse_valid_data(self):
        """Valid data is parsed correctly."""
        data = {"amount": 1000, "unit": "msats", "period": 30, "kinds": [1, 2]}
        result = Nip11FetchDataFeeEntry.parse(data)
        assert result == {"amount": 1000, "unit": "msats", "period": 30, "kinds": [1, 2]}

    def test_parse_invalid_types_ignored(self):
        """Invalid types are ignored."""
        data = {"amount": "1000", "unit": 123, "kinds": "not a list"}
        result = Nip11FetchDataFeeEntry.parse(data)
        assert result == {}

    def test_parse_filters_invalid_kinds(self):
        """Invalid kinds elements are filtered out."""
        data = {"amount": 100, "unit": "sats", "kinds": [1, True, "two", 3]}
        result = Nip11FetchDataFeeEntry.parse(data)
        assert result == {"amount": 100, "unit": "sats", "kinds": [1, 3]}


class TestNip11FetchDataFeeEntryToDict:
    """Test Nip11FetchDataFeeEntry.to_dict() method."""

    def test_to_dict_omits_none(self):
        """to_dict omits None values."""
        entry = Nip11FetchDataFeeEntry(amount=100, unit="sats")
        d = entry.to_dict()
        assert d == {"amount": 100, "unit": "sats"}
        assert "period" not in d
        assert "kinds" not in d


class TestNip11FetchDataFeeEntryRoundtrip:
    """Test to_dict -> from_dict roundtrip."""

    def test_roundtrip(self):
        """to_dict -> from_dict roundtrip preserves data."""
        original = Nip11FetchDataFeeEntry(amount=100, unit="msats", kinds=[4])
        reconstructed = Nip11FetchDataFeeEntry.from_dict(original.to_dict())
        assert reconstructed == original


# =============================================================================
# Nip11FetchDataFees Tests
# =============================================================================


class TestNip11FetchDataFeesConstructor:
    """Test Nip11FetchDataFees constructor validation."""

    def test_constructor_all_defaults(self):
        """Constructor with no arguments creates model with all None values."""
        fees = Nip11FetchDataFees()
        assert fees.admission is None
        assert fees.subscription is None
        assert fees.publication is None

    def test_constructor_valid_values(self):
        """Constructor accepts valid values."""
        fees = Nip11FetchDataFees(admission=[Nip11FetchDataFeeEntry(amount=1000, unit="sats")])
        assert fees.admission is not None
        assert len(fees.admission) == 1

    def test_constructor_rejects_non_list(self):
        """Constructor raises ValidationError for non-list field."""
        with pytest.raises(ValidationError):
            Nip11FetchDataFees(admission="invalid")

    def test_constructor_accepts_dict_entries(self):
        """Constructor automatically converts dicts to Nip11FetchDataFeeEntry."""
        fees = Nip11FetchDataFees(admission=[{"amount": 1000}])
        assert fees.admission[0].amount == 1000


class TestNip11FetchDataFeesParse:
    """Test Nip11FetchDataFees.parse() method."""

    def test_parse_valid_data(self):
        """Valid data is parsed correctly."""
        data = {
            "admission": [{"amount": 1000, "unit": "msats"}],
            "subscription": [{"amount": 500, "unit": "msats", "period": 30}],
        }
        result = Nip11FetchDataFees.parse(data)
        assert result == {
            "admission": [{"amount": 1000, "unit": "msats"}],
            "subscription": [{"amount": 500, "unit": "msats", "period": 30}],
        }

    def test_parse_empty_entries_filtered(self):
        """Empty entries are filtered out."""
        data = {"admission": [{"invalid": "data"}, {"amount": 1000, "unit": "msats"}]}
        result = Nip11FetchDataFees.parse(data)
        assert result == {"admission": [{"amount": 1000, "unit": "msats"}]}

    def test_parse_non_list_ignored(self):
        """Non-list values are ignored."""
        data = {"admission": "not a list"}
        result = Nip11FetchDataFees.parse(data)
        assert result == {}

    def test_parse_all_invalid_entries_omits_key(self):
        """Key is omitted if all entries are invalid."""
        data = {"admission": [{"invalid": "data"}]}
        result = Nip11FetchDataFees.parse(data)
        assert "admission" not in result


class TestNip11FetchDataFeesRoundtrip:
    """Test to_dict -> from_dict roundtrip."""

    def test_roundtrip(self):
        """to_dict -> from_dict roundtrip preserves data."""
        original = Nip11FetchDataFees(
            admission=[Nip11FetchDataFeeEntry(amount=1000, unit="sats")],
            subscription=[Nip11FetchDataFeeEntry(amount=5000, unit="sats", period=2628003)],
        )
        reconstructed = Nip11FetchDataFees.from_dict(original.to_dict())
        assert reconstructed == original


# =============================================================================
# Nip11FetchData Tests
# =============================================================================


class TestNip11FetchDataConstructor:
    """Test Nip11FetchData constructor validation."""

    def test_constructor_all_defaults(self):
        """Constructor with no arguments creates model with defaults."""
        data = Nip11FetchData()
        assert data.name is None
        assert isinstance(data.limitation, Nip11FetchDataLimitation)
        assert isinstance(data.fees, Nip11FetchDataFees)

    def test_constructor_valid_values(self):
        """Constructor accepts valid values."""
        data = Nip11FetchData(
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
            Nip11FetchData(name=123)

    def test_constructor_rejects_bool_in_supported_nips(self):
        """Constructor raises ValidationError for bool in supported_nips."""
        with pytest.raises(ValidationError):
            Nip11FetchData(supported_nips=[True, 11])

    def test_constructor_rejects_non_str_in_tags(self):
        """Constructor raises ValidationError for non-str in tags list."""
        with pytest.raises(ValidationError):
            Nip11FetchData(tags=["valid", 42])

    def test_constructor_accepts_dict_limitation(self):
        """Constructor automatically converts dict to Nip11FetchDataLimitation."""
        data = Nip11FetchData(limitation={"max_message_length": 1000})
        assert data.limitation.max_message_length == 1000

    def test_constructor_accepts_dict_fees(self):
        """Constructor automatically converts dict to Nip11FetchDataFees."""
        data = Nip11FetchData(fees={"admission": [{"amount": 100}]})
        assert data.fees.admission[0].amount == 100

    def test_constructor_accepts_dict_retention_entries(self):
        """Constructor converts dicts to Nip11FetchDataRetentionEntry."""
        data = Nip11FetchData(retention=[{"kinds": [1]}])
        assert data.retention[0].kinds == [1]


class TestNip11FetchDataSelfProperty:
    """Test Nip11FetchData.self property and alias handling."""

    def test_self_property_returns_self_pubkey(self):
        """self property returns self_pubkey value."""
        data = Nip11FetchData(self_pubkey="abc123")
        assert data.self == "abc123"

    def test_self_alias_in_from_dict(self):
        """'self' key in dict maps to self_pubkey field."""
        data = Nip11FetchData.from_dict({"self": "xyz789"})
        assert data.self_pubkey == "xyz789"
        assert data.self == "xyz789"

    def test_self_alias_in_to_dict(self):
        """to_dict outputs 'self' key (via alias)."""
        data = Nip11FetchData(self_pubkey="abc123")
        d = data.to_dict()
        assert "self" in d
        assert d["self"] == "abc123"
        assert "self_pubkey" not in d


class TestNip11FetchDataParse:
    """Test Nip11FetchData.parse() method."""

    def test_parse_valid_data(self):
        """Valid data is parsed correctly."""
        data = {
            "name": "Test Relay",
            "description": "A test relay",
            "supported_nips": [1, 11, 42],
            "limitation": {"max_message_length": 65535},
            "relay_countries": ["US", "DE"],
        }
        result = Nip11FetchData.parse(data)
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
        result = Nip11FetchData.parse(data)
        assert result == {}

    def test_parse_nested_objects(self):
        """Nested objects are parsed correctly."""
        data = {
            "retention": [{"kinds": [1, 2], "time": 3600}],
            "fees": {"admission": [{"amount": 1000, "unit": "msats"}]},
        }
        result = Nip11FetchData.parse(data)
        assert result["retention"] == [{"kinds": [1, 2], "time": 3600}]
        assert result["fees"] == {"admission": [{"amount": 1000, "unit": "msats"}]}

    def test_parse_filters_bools_from_supported_nips(self):
        """Bools are filtered from supported_nips."""
        data = {"supported_nips": [1, True, 11, False, 42]}
        result = Nip11FetchData.parse(data)
        assert result["supported_nips"] == [1, 11, 42]

    def test_parse_filters_non_strings_from_tags(self):
        """Non-strings are filtered from tags."""
        data = {"tags": ["valid", 42, "also valid", None]}
        result = Nip11FetchData.parse(data)
        assert result["tags"] == ["valid", "also valid"]

    def test_parse_self_field(self):
        """'self' field is parsed as string."""
        data = {"self": "abc123def456"}
        result = Nip11FetchData.parse(data)
        assert result["self"] == "abc123def456"

    def test_parse_non_dict_returns_empty(self):
        """Non-dict input returns empty dict."""
        assert Nip11FetchData.parse(None) == {}
        assert Nip11FetchData.parse("string") == {}
        assert Nip11FetchData.parse([1, 2, 3]) == {}

    def test_parse_creates_valid_model(self):
        """Parsed data creates a valid Nip11FetchData model."""
        raw = {
            "name": "Test",
            "invalid_field": "ignored",
            "supported_nips": [1, True, "invalid", 11],
            "limitation": {"max_message_length": "invalid", "auth_required": False},
        }
        parsed = Nip11FetchData.parse(raw)
        model = Nip11FetchData.from_dict(parsed)
        assert model.name == "Test"
        assert model.supported_nips == [1, 11]
        assert model.limitation.auth_required is False
        assert model.limitation.max_message_length is None


class TestNip11FetchDataFromDict:
    """Test Nip11FetchData.from_dict() method."""

    def test_from_dict_valid(self, complete_nip11_data: dict[str, Any]):
        """from_dict with valid data creates Nip11FetchData."""
        data = Nip11FetchData.from_dict(complete_nip11_data)
        assert data.name == "Test Relay"
        assert data.self == "b" * 64
        assert data.limitation.max_message_length == 65535
        assert data.fees.admission is not None
        assert data.retention is not None
        assert len(data.retention) == 3

    def test_from_dict_empty(self):
        """from_dict with empty dict creates defaults."""
        data = Nip11FetchData.from_dict({})
        assert data.name is None
        assert isinstance(data.limitation, Nip11FetchDataLimitation)
        assert isinstance(data.fees, Nip11FetchDataFees)

    def test_from_dict_rejects_non_str_name(self):
        """from_dict raises ValidationError for non-str name."""
        with pytest.raises(ValidationError):
            Nip11FetchData.from_dict({"name": 123})


class TestNip11FetchDataToDict:
    """Test Nip11FetchData.to_dict() method."""

    def test_to_dict(self, complete_nip11_data: dict[str, Any]):
        """to_dict returns serializable dict."""
        data = Nip11FetchData.from_dict(complete_nip11_data)
        d = data.to_dict()
        assert d["name"] == "Test Relay"
        assert d["self"] == "b" * 64
        assert isinstance(d["limitation"], dict)
        assert isinstance(d["fees"], dict)

    def test_to_dict_excludes_none(self):
        """to_dict excludes None values."""
        data = Nip11FetchData(name="Test")
        d = data.to_dict()
        assert "name" in d
        assert "description" not in d


class TestNip11FetchDataRoundtrip:
    """Test to_dict -> from_dict roundtrip."""

    def test_roundtrip(self, complete_nip11_data: dict[str, Any]):
        """to_dict -> from_dict roundtrip preserves data."""
        original = Nip11FetchData.from_dict(complete_nip11_data)
        reconstructed = Nip11FetchData.from_dict(original.to_dict())
        assert reconstructed == original


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestNip11FetchDataEdgeCases:
    """Test edge cases for Nip11FetchData."""

    def test_empty_lists(self):
        """Empty lists are valid."""
        data = Nip11FetchData(
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
        data = Nip11FetchData.from_dict(unicode_nip11_data)
        assert data.name == "Relay del Sol"
        assert data.description == "Un relay para todos los nostrichos"
        assert "espanol" in data.tags
        assert "es" in data.language_tags

    def test_very_long_values(self):
        """Very long string values are accepted."""
        long_name = "x" * 10000
        long_description = "y" * 100000
        data = Nip11FetchData(name=long_name, description=long_description)
        assert len(data.name) == 10000
        assert len(data.description) == 100000

    def test_special_characters(self):
        """Special characters are preserved."""
        data = Nip11FetchData(
            name='Test <Relay> & "Quotes"',
            description="Line1\nLine2\tTab",
        )
        assert "<Relay>" in data.name
        assert "\n" in data.description
        assert "\t" in data.description

    def test_large_supported_nips_list(self):
        """Large lists of supported NIPs are handled."""
        nips = list(range(1, 1001))
        data = Nip11FetchData(supported_nips=nips)
        assert len(data.supported_nips) == 1000

    def test_many_retention_entries(self):
        """Many retention entries are handled."""
        entries = [Nip11FetchDataRetentionEntry(kinds=[i]) for i in range(100)]
        data = Nip11FetchData(retention=entries)
        assert len(data.retention) == 100


class TestNip11FetchDataFrozen:
    """Test Nip11FetchData is frozen (immutable)."""

    def test_model_is_frozen(self):
        """Nip11FetchData models are immutable."""
        data = Nip11FetchData(name="Test")
        with pytest.raises(ValidationError):
            data.name = "Changed"

    def test_limitation_is_frozen(self):
        """Nested limitation is also frozen."""
        data = Nip11FetchData(limitation=Nip11FetchDataLimitation(max_message_length=1000))
        with pytest.raises(ValidationError):
            data.limitation.max_message_length = 2000
