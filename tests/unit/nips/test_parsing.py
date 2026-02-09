"""Unit tests for FieldSpec dataclass and parse_fields function."""

import pytest

from bigbrotr.nips.parsing import FieldSpec, parse_fields


# =============================================================================
# FieldSpec Dataclass Tests
# =============================================================================


class TestFieldSpecConstruction:
    """Test FieldSpec dataclass construction and defaults."""

    def test_default_construction(self):
        """Default construction creates empty frozensets."""
        spec = FieldSpec()
        assert spec.int_fields == frozenset()
        assert spec.bool_fields == frozenset()
        assert spec.str_fields == frozenset()
        assert spec.str_list_fields == frozenset()
        assert spec.float_fields == frozenset()
        assert spec.int_list_fields == frozenset()

    def test_construction_with_int_fields(self):
        """Construction with int_fields."""
        spec = FieldSpec(int_fields=frozenset({"count", "limit"}))
        assert spec.int_fields == frozenset({"count", "limit"})
        assert spec.bool_fields == frozenset()

    def test_construction_with_bool_fields(self):
        """Construction with bool_fields."""
        spec = FieldSpec(bool_fields=frozenset({"enabled", "active"}))
        assert spec.bool_fields == frozenset({"enabled", "active"})
        assert spec.int_fields == frozenset()

    def test_construction_with_str_fields(self):
        """Construction with str_fields."""
        spec = FieldSpec(str_fields=frozenset({"name", "description"}))
        assert spec.str_fields == frozenset({"name", "description"})

    def test_construction_with_str_list_fields(self):
        """Construction with str_list_fields."""
        spec = FieldSpec(str_list_fields=frozenset({"tags", "labels"}))
        assert spec.str_list_fields == frozenset({"tags", "labels"})

    def test_construction_with_float_fields(self):
        """Construction with float_fields."""
        spec = FieldSpec(float_fields=frozenset({"lat", "lon"}))
        assert spec.float_fields == frozenset({"lat", "lon"})

    def test_construction_with_int_list_fields(self):
        """Construction with int_list_fields."""
        spec = FieldSpec(int_list_fields=frozenset({"ids", "kinds"}))
        assert spec.int_list_fields == frozenset({"ids", "kinds"})

    def test_construction_with_all_fields(self):
        """Construction with all field types populated."""
        spec = FieldSpec(
            int_fields=frozenset({"count"}),
            bool_fields=frozenset({"enabled"}),
            str_fields=frozenset({"name"}),
            str_list_fields=frozenset({"tags"}),
            float_fields=frozenset({"lat"}),
            int_list_fields=frozenset({"ids"}),
        )
        assert spec.int_fields == frozenset({"count"})
        assert spec.bool_fields == frozenset({"enabled"})
        assert spec.str_fields == frozenset({"name"})
        assert spec.str_list_fields == frozenset({"tags"})
        assert spec.float_fields == frozenset({"lat"})
        assert spec.int_list_fields == frozenset({"ids"})


class TestFieldSpecImmutability:
    """Test FieldSpec is immutable (frozen=True)."""

    def test_is_hashable(self):
        """FieldSpec is hashable due to frozen=True."""
        spec = FieldSpec(int_fields=frozenset({"count"}))
        assert hash(spec) is not None
        d = {spec: "value"}
        assert d[spec] == "value"

    def test_modification_raises_error(self):
        """Cannot modify FieldSpec attributes after creation."""
        spec = FieldSpec(int_fields=frozenset({"count"}))
        with pytest.raises(AttributeError):
            spec.int_fields = frozenset({"other"})


class TestFieldSpecEquality:
    """Test FieldSpec equality comparison."""

    def test_equal_specs(self):
        """Equal FieldSpecs are equal."""
        spec1 = FieldSpec(int_fields=frozenset({"count"}))
        spec2 = FieldSpec(int_fields=frozenset({"count"}))
        assert spec1 == spec2

    def test_different_specs(self):
        """Different FieldSpecs are not equal."""
        spec1 = FieldSpec(int_fields=frozenset({"count"}))
        spec2 = FieldSpec(int_fields=frozenset({"limit"}))
        assert spec1 != spec2


# =============================================================================
# parse_fields: Empty and Edge Cases
# =============================================================================


class TestParseFieldsEmpty:
    """Test parse_fields with empty input and edge cases."""

    def test_empty_data_returns_empty(self):
        """Empty data dict returns empty dict."""
        spec = FieldSpec(int_fields=frozenset({"count"}))
        result = parse_fields({}, spec)
        assert result == {}

    def test_empty_spec_returns_empty(self):
        """Empty FieldSpec returns empty dict (no fields defined)."""
        spec = FieldSpec()
        result = parse_fields({"count": 10, "name": "test"}, spec)
        assert result == {}

    def test_unknown_fields_ignored(self):
        """Fields not in any spec category are ignored."""
        spec = FieldSpec(int_fields=frozenset({"count"}))
        result = parse_fields({"count": 10, "unknown": "value"}, spec)
        assert result == {"count": 10}
        assert "unknown" not in result


# =============================================================================
# parse_fields: int_fields Tests
# =============================================================================


class TestParseFieldsInt:
    """Test parse_fields with int_fields."""

    @pytest.fixture
    def int_spec(self):
        """FieldSpec with int fields."""
        return FieldSpec(int_fields=frozenset({"count", "limit", "max_size"}))

    def test_valid_int_preserved(self, int_spec):
        """Valid int values are preserved."""
        result = parse_fields({"count": 10, "limit": 100}, int_spec)
        assert result == {"count": 10, "limit": 100}

    def test_zero_preserved(self, int_spec):
        """Zero is a valid int and is preserved."""
        result = parse_fields({"count": 0}, int_spec)
        assert result == {"count": 0}

    def test_negative_int_preserved(self, int_spec):
        """Negative int values are preserved."""
        result = parse_fields({"count": -5}, int_spec)
        assert result == {"count": -5}

    def test_large_int_preserved(self, int_spec):
        """Large int values are preserved."""
        result = parse_fields({"count": 2**62}, int_spec)
        assert result == {"count": 2**62}

    def test_bool_true_rejected(self, int_spec):
        """Boolean True is rejected for int fields (bool is subclass of int)."""
        result = parse_fields({"count": True}, int_spec)
        assert result == {}

    def test_bool_false_rejected(self, int_spec):
        """Boolean False is rejected for int fields (bool is subclass of int)."""
        result = parse_fields({"count": False}, int_spec)
        assert result == {}

    def test_string_rejected(self, int_spec):
        """String value is rejected for int fields."""
        result = parse_fields({"count": "10"}, int_spec)
        assert result == {}

    def test_float_rejected(self, int_spec):
        """Float value is rejected for int fields."""
        result = parse_fields({"count": 10.5}, int_spec)
        assert result == {}

    def test_none_rejected(self, int_spec):
        """None value is rejected for int fields."""
        result = parse_fields({"count": None}, int_spec)
        assert result == {}

    def test_list_rejected(self, int_spec):
        """List value is rejected for int fields."""
        result = parse_fields({"count": [10]}, int_spec)
        assert result == {}

    def test_mixed_valid_invalid(self, int_spec):
        """Valid ints preserved, invalid values dropped."""
        result = parse_fields({"count": 10, "limit": "invalid", "max_size": True}, int_spec)
        assert result == {"count": 10}


# =============================================================================
# parse_fields: bool_fields Tests
# =============================================================================


class TestParseFieldsBool:
    """Test parse_fields with bool_fields."""

    @pytest.fixture
    def bool_spec(self):
        """FieldSpec with bool fields."""
        return FieldSpec(bool_fields=frozenset({"enabled", "active", "verified"}))

    def test_true_preserved(self, bool_spec):
        """Boolean True is preserved."""
        result = parse_fields({"enabled": True}, bool_spec)
        assert result == {"enabled": True}

    def test_false_preserved(self, bool_spec):
        """Boolean False is preserved."""
        result = parse_fields({"enabled": False}, bool_spec)
        assert result == {"enabled": False}

    def test_int_one_rejected(self, bool_spec):
        """Integer 1 is rejected for bool fields."""
        result = parse_fields({"enabled": 1}, bool_spec)
        assert result == {}

    def test_int_zero_rejected(self, bool_spec):
        """Integer 0 is rejected for bool fields."""
        result = parse_fields({"enabled": 0}, bool_spec)
        assert result == {}

    def test_string_true_rejected(self, bool_spec):
        """String 'true' is rejected for bool fields."""
        result = parse_fields({"enabled": "true"}, bool_spec)
        assert result == {}

    def test_string_false_rejected(self, bool_spec):
        """String 'false' is rejected for bool fields."""
        result = parse_fields({"enabled": "false"}, bool_spec)
        assert result == {}

    def test_none_rejected(self, bool_spec):
        """None is rejected for bool fields."""
        result = parse_fields({"enabled": None}, bool_spec)
        assert result == {}

    def test_mixed_valid_invalid(self, bool_spec):
        """Valid bools preserved, invalid values dropped."""
        result = parse_fields({"enabled": True, "active": "yes", "verified": False}, bool_spec)
        assert result == {"enabled": True, "verified": False}


# =============================================================================
# parse_fields: str_fields Tests
# =============================================================================


class TestParseFieldsStr:
    """Test parse_fields with str_fields."""

    @pytest.fixture
    def str_spec(self):
        """FieldSpec with str fields."""
        return FieldSpec(str_fields=frozenset({"name", "description", "email"}))

    def test_valid_str_preserved(self, str_spec):
        """Valid string values are preserved."""
        result = parse_fields({"name": "Test", "description": "A test"}, str_spec)
        assert result == {"name": "Test", "description": "A test"}

    def test_empty_str_preserved(self, str_spec):
        """Empty string is a valid str and is preserved."""
        result = parse_fields({"name": ""}, str_spec)
        assert result == {"name": ""}

    def test_unicode_str_preserved(self, str_spec):
        """Unicode string is preserved."""
        result = parse_fields({"name": "Test Relay"}, str_spec)
        assert result == {"name": "Test Relay"}

    def test_int_rejected(self, str_spec):
        """Integer is rejected for str fields."""
        result = parse_fields({"name": 123}, str_spec)
        assert result == {}

    def test_bool_rejected(self, str_spec):
        """Boolean is rejected for str fields."""
        result = parse_fields({"name": True}, str_spec)
        assert result == {}

    def test_none_rejected(self, str_spec):
        """None is rejected for str fields."""
        result = parse_fields({"name": None}, str_spec)
        assert result == {}

    def test_list_rejected(self, str_spec):
        """List is rejected for str fields."""
        result = parse_fields({"name": ["Test"]}, str_spec)
        assert result == {}

    def test_mixed_valid_invalid(self, str_spec):
        """Valid strings preserved, invalid values dropped."""
        result = parse_fields({"name": "Test", "description": 123, "email": None}, str_spec)
        assert result == {"name": "Test"}


# =============================================================================
# parse_fields: str_list_fields Tests
# =============================================================================


class TestParseFieldsStrList:
    """Test parse_fields with str_list_fields."""

    @pytest.fixture
    def str_list_spec(self):
        """FieldSpec with str_list fields."""
        return FieldSpec(str_list_fields=frozenset({"tags", "languages", "countries"}))

    def test_valid_str_list_preserved(self, str_list_spec):
        """Valid string list is preserved."""
        result = parse_fields({"tags": ["nostr", "bitcoin"]}, str_list_spec)
        assert result == {"tags": ["nostr", "bitcoin"]}

    def test_single_element_list_preserved(self, str_list_spec):
        """Single element string list is preserved."""
        result = parse_fields({"tags": ["nostr"]}, str_list_spec)
        assert result == {"tags": ["nostr"]}

    def test_empty_list_rejected(self, str_list_spec):
        """Empty list is rejected (no valid elements)."""
        result = parse_fields({"tags": []}, str_list_spec)
        assert result == {}

    def test_invalid_elements_filtered(self, str_list_spec):
        """Invalid elements are filtered, valid ones preserved."""
        result = parse_fields({"tags": ["nostr", 123, True, "bitcoin"]}, str_list_spec)
        assert result == {"tags": ["nostr", "bitcoin"]}

    def test_all_invalid_elements_results_in_no_field(self, str_list_spec):
        """List with only invalid elements is not included."""
        result = parse_fields({"tags": [123, True, None]}, str_list_spec)
        assert result == {}

    def test_none_element_filtered(self, str_list_spec):
        """None elements are filtered out."""
        result = parse_fields({"tags": ["nostr", None, "bitcoin"]}, str_list_spec)
        assert result == {"tags": ["nostr", "bitcoin"]}

    def test_non_list_rejected(self, str_list_spec):
        """Non-list value is rejected."""
        result = parse_fields({"tags": "nostr"}, str_list_spec)
        assert result == {}

    def test_int_rejected(self, str_list_spec):
        """Integer is rejected for str_list fields."""
        result = parse_fields({"tags": 123}, str_list_spec)
        assert result == {}

    def test_empty_str_in_list_preserved(self, str_list_spec):
        """Empty strings in list are preserved (valid str type)."""
        result = parse_fields({"tags": ["nostr", "", "bitcoin"]}, str_list_spec)
        assert result == {"tags": ["nostr", "", "bitcoin"]}


# =============================================================================
# parse_fields: float_fields Tests
# =============================================================================


class TestParseFieldsFloat:
    """Test parse_fields with float_fields."""

    @pytest.fixture
    def float_spec(self):
        """FieldSpec with float fields."""
        return FieldSpec(float_fields=frozenset({"lat", "lon", "accuracy"}))

    def test_valid_float_preserved(self, float_spec):
        """Valid float values are preserved."""
        result = parse_fields({"lat": 37.386, "lon": -122.084}, float_spec)
        assert result == {"lat": 37.386, "lon": -122.084}

    def test_int_converted_to_float(self, float_spec):
        """Integer values are converted to float."""
        result = parse_fields({"lat": 37}, float_spec)
        assert result == {"lat": 37.0}
        assert isinstance(result["lat"], float)

    def test_zero_preserved(self, float_spec):
        """Zero is valid and converted to float."""
        result = parse_fields({"lat": 0}, float_spec)
        assert result == {"lat": 0.0}
        assert isinstance(result["lat"], float)

    def test_negative_float_preserved(self, float_spec):
        """Negative float values are preserved."""
        result = parse_fields({"lon": -122.084}, float_spec)
        assert result == {"lon": -122.084}

    def test_bool_true_rejected(self, float_spec):
        """Boolean True is rejected for float fields."""
        result = parse_fields({"lat": True}, float_spec)
        assert result == {}

    def test_bool_false_rejected(self, float_spec):
        """Boolean False is rejected for float fields."""
        result = parse_fields({"lat": False}, float_spec)
        assert result == {}

    def test_string_rejected(self, float_spec):
        """String value is rejected for float fields."""
        result = parse_fields({"lat": "37.386"}, float_spec)
        assert result == {}

    def test_none_rejected(self, float_spec):
        """None is rejected for float fields."""
        result = parse_fields({"lat": None}, float_spec)
        assert result == {}

    def test_mixed_valid_invalid(self, float_spec):
        """Valid floats preserved, invalid values dropped."""
        result = parse_fields({"lat": 37.386, "lon": "invalid", "accuracy": True}, float_spec)
        assert result == {"lat": 37.386}


# =============================================================================
# parse_fields: int_list_fields Tests
# =============================================================================


class TestParseFieldsIntList:
    """Test parse_fields with int_list_fields."""

    @pytest.fixture
    def int_list_spec(self):
        """FieldSpec with int_list fields."""
        return FieldSpec(int_list_fields=frozenset({"ids", "kinds", "nips"}))

    def test_valid_int_list_preserved(self, int_list_spec):
        """Valid integer list is preserved."""
        result = parse_fields({"ids": [1, 2, 3]}, int_list_spec)
        assert result == {"ids": [1, 2, 3]}

    def test_single_element_list_preserved(self, int_list_spec):
        """Single element integer list is preserved."""
        result = parse_fields({"ids": [42]}, int_list_spec)
        assert result == {"ids": [42]}

    def test_empty_list_rejected(self, int_list_spec):
        """Empty list is rejected (no valid elements)."""
        result = parse_fields({"ids": []}, int_list_spec)
        assert result == {}

    def test_invalid_elements_filtered(self, int_list_spec):
        """Invalid elements are filtered, valid ones preserved."""
        result = parse_fields({"ids": [1, "two", 3.5, 4]}, int_list_spec)
        assert result == {"ids": [1, 4]}

    def test_bool_elements_filtered(self, int_list_spec):
        """Boolean elements are filtered (bool is subclass of int)."""
        result = parse_fields({"ids": [1, True, False, 4]}, int_list_spec)
        assert result == {"ids": [1, 4]}

    def test_all_invalid_elements_results_in_no_field(self, int_list_spec):
        """List with only invalid elements is not included."""
        result = parse_fields({"ids": [True, False, "one"]}, int_list_spec)
        assert result == {}

    def test_none_element_filtered(self, int_list_spec):
        """None elements are filtered out."""
        result = parse_fields({"ids": [1, None, 3]}, int_list_spec)
        assert result == {"ids": [1, 3]}

    def test_non_list_rejected(self, int_list_spec):
        """Non-list value is rejected."""
        result = parse_fields({"ids": 123}, int_list_spec)
        assert result == {}

    def test_string_rejected(self, int_list_spec):
        """String is rejected for int_list fields."""
        result = parse_fields({"ids": "1,2,3"}, int_list_spec)
        assert result == {}

    def test_negative_ints_preserved(self, int_list_spec):
        """Negative integers in list are preserved."""
        result = parse_fields({"ids": [-1, 0, 1]}, int_list_spec)
        assert result == {"ids": [-1, 0, 1]}


# =============================================================================
# parse_fields: Mixed Field Types
# =============================================================================


class TestParseFieldsMixed:
    """Test parse_fields with multiple field types."""

    @pytest.fixture
    def mixed_spec(self):
        """FieldSpec with all field types."""
        return FieldSpec(
            int_fields=frozenset({"count", "limit"}),
            bool_fields=frozenset({"enabled", "verified"}),
            str_fields=frozenset({"name", "description"}),
            str_list_fields=frozenset({"tags", "languages"}),
            float_fields=frozenset({"lat", "lon"}),
            int_list_fields=frozenset({"ids", "kinds"}),
        )

    def test_all_valid_fields(self, mixed_spec):
        """All valid fields are preserved."""
        data = {
            "count": 10,
            "enabled": True,
            "name": "Test",
            "tags": ["a", "b"],
            "lat": 37.0,
            "ids": [1, 2],
        }
        result = parse_fields(data, mixed_spec)
        assert result == {
            "count": 10,
            "enabled": True,
            "name": "Test",
            "tags": ["a", "b"],
            "lat": 37.0,
            "ids": [1, 2],
        }

    def test_some_invalid_fields(self, mixed_spec):
        """Invalid fields are dropped, valid ones preserved."""
        data = {
            "count": 10,
            "limit": "invalid",  # Should be int
            "enabled": True,
            "verified": 1,  # Should be bool
            "name": "Test",
            "description": 123,  # Should be str
            "tags": ["a", "b"],
            "languages": "en",  # Should be list
            "lat": 37.0,
            "lon": "invalid",  # Should be float
            "ids": [1, 2],
            "kinds": [True, False],  # Bools filtered
        }
        result = parse_fields(data, mixed_spec)
        assert result == {
            "count": 10,
            "enabled": True,
            "name": "Test",
            "tags": ["a", "b"],
            "lat": 37.0,
            "ids": [1, 2],
        }

    def test_unknown_fields_ignored(self, mixed_spec):
        """Fields not defined in spec are ignored."""
        data = {
            "count": 10,
            "unknown_field": "value",
            "another_unknown": 123,
        }
        result = parse_fields(data, mixed_spec)
        assert result == {"count": 10}


# =============================================================================
# parse_fields: Real-World NIP-11/NIP-66 Scenarios
# =============================================================================


class TestParseFieldsRealWorld:
    """Test parse_fields with realistic NIP-11/NIP-66 scenarios."""

    def test_nip11_limitation_fields(self):
        """Parse NIP-11 limitation fields."""
        spec = FieldSpec(
            int_fields=frozenset({"max_message_length", "max_subscriptions", "max_limit"}),
            bool_fields=frozenset({"auth_required", "payment_required"}),
        )
        data = {
            "max_message_length": 65535,
            "max_subscriptions": 20,
            "max_limit": 5000,
            "auth_required": False,
            "payment_required": True,
            "invalid_int": "large",
            "invalid_bool": "yes",
        }
        result = parse_fields(data, spec)
        assert result == {
            "max_message_length": 65535,
            "max_subscriptions": 20,
            "max_limit": 5000,
            "auth_required": False,
            "payment_required": True,
        }

    def test_nip11_data_fields(self):
        """Parse NIP-11 top-level data fields."""
        spec = FieldSpec(
            str_fields=frozenset({"name", "description", "software", "version"}),
            str_list_fields=frozenset({"relay_countries", "language_tags", "tags"}),
            int_list_fields=frozenset({"supported_nips"}),
        )
        data = {
            "name": "Test Relay",
            "description": "A test relay",
            "software": "strfry",
            "version": "1.0.0",
            "relay_countries": ["US", "DE"],
            "language_tags": ["en", "de"],
            "tags": ["bitcoin", 123],
            "supported_nips": [1, 11, True, 42],
        }
        result = parse_fields(data, spec)
        assert result == {
            "name": "Test Relay",
            "description": "A test relay",
            "software": "strfry",
            "version": "1.0.0",
            "relay_countries": ["US", "DE"],
            "language_tags": ["en", "de"],
            "tags": ["bitcoin"],
            "supported_nips": [1, 11, 42],
        }

    def test_nip66_geo_fields(self):
        """Parse NIP-66 geo data fields."""
        spec = FieldSpec(
            str_fields=frozenset({"geo_country", "geo_country_name", "geo_city", "geo_tz"}),
            float_fields=frozenset({"geo_lat", "geo_lon"}),
            int_fields=frozenset({"geo_accuracy", "geo_geoname_id"}),
            bool_fields=frozenset({"geo_is_eu"}),
        )
        data = {
            "geo_country": "US",
            "geo_country_name": "United States",
            "geo_city": "Mountain View",
            "geo_tz": "America/Los_Angeles",
            "geo_lat": 37.386,
            "geo_lon": -122.084,
            "geo_accuracy": 10,
            "geo_geoname_id": 5375480,
            "geo_is_eu": False,
        }
        result = parse_fields(data, spec)
        assert result == data

    def test_nip66_dns_fields(self):
        """Parse NIP-66 DNS data fields."""
        spec = FieldSpec(
            str_fields=frozenset({"dns_cname", "dns_reverse"}),
            str_list_fields=frozenset({"dns_ips", "dns_ips_v6", "dns_ns"}),
            int_fields=frozenset({"dns_ttl"}),
        )
        data = {
            "dns_ips": ["8.8.8.8", "8.8.4.4", 123],
            "dns_ips_v6": ["2001:4860:4860::8888"],
            "dns_cname": "dns.google",
            "dns_reverse": "dns.google",
            "dns_ns": ["ns1.google.com", None, "ns2.google.com"],
            "dns_ttl": 300,
        }
        result = parse_fields(data, spec)
        assert result == {
            "dns_ips": ["8.8.8.8", "8.8.4.4"],
            "dns_ips_v6": ["2001:4860:4860::8888"],
            "dns_cname": "dns.google",
            "dns_reverse": "dns.google",
            "dns_ns": ["ns1.google.com", "ns2.google.com"],
            "dns_ttl": 300,
        }
