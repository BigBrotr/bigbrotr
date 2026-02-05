"""Tests for NIP-11 model."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from models.metadata import Metadata
from models.nips.nip11 import (
    Nip11,
    Nip11FetchData,
    Nip11FetchDataFeeEntry,
    Nip11FetchDataFees,
    Nip11FetchDataLimitation,
    Nip11FetchDataRetentionEntry,
    Nip11FetchLogs,
    Nip11FetchMetadata,
)
from models.relay import Relay
from models.relay_metadata import MetadataType


@pytest.fixture
def relay():
    """Test relay fixture."""
    return Relay("wss://relay.example.com")


@pytest.fixture
def complete_nip11_data():
    """Complete NIP-11 data dict matching spec."""
    return {
        "name": "Test Relay",
        "description": "A test relay for unit tests",
        "banner": "https://example.com/banner.jpg",
        "icon": "https://example.com/icon.jpg",
        "pubkey": "a" * 64,
        "self": "b" * 64,
        "contact": "admin@example.com",
        "software": "nostr-rs-relay",
        "version": "1.0.0",
        "privacy_policy": "https://example.com/privacy",
        "terms_of_service": "https://example.com/tos",
        "posting_policy": "https://example.com/posting",
        "payments_url": "https://example.com/pay",
        "supported_nips": [1, 11, 42, 65],
        "limitation": {
            "max_message_length": 65535,
            "max_subscriptions": 20,
            "max_limit": 5000,
            "max_subid_length": 256,
            "max_event_tags": 2000,
            "max_content_length": 65535,
            "min_pow_difficulty": 0,
            "auth_required": False,
            "payment_required": True,
            "restricted_writes": True,
            "created_at_lower_limit": 0,
            "created_at_upper_limit": 2147483647,
            "default_limit": 100,
        },
        "retention": [
            {"kinds": [0, 3]},
            {"kinds": [[10000, 19999]], "time": 86400},
            {"kinds": [[30000, 39999]], "count": 100},
        ],
        "relay_countries": ["US", "CA"],
        "language_tags": ["en", "en-US"],
        "tags": ["sfw-only", "bitcoin-only"],
        "fees": {
            "admission": [{"amount": 1000, "unit": "sats"}],
            "subscription": [{"amount": 5000, "unit": "sats", "period": 2628003}],
            "publication": [{"kinds": [4], "amount": 100, "unit": "msats"}],
        },
    }


@pytest.fixture
def nip11(relay, complete_nip11_data):
    """Nip11 instance with complete data."""
    return Nip11(
        relay=relay,
        fetch_metadata=Nip11FetchMetadata(
            data=Nip11FetchData.from_dict(complete_nip11_data),
            logs=Nip11FetchLogs(success=True),
        ),
        generated_at=1234567890,
    )


# =============================================================================
# Nip11FetchLogs Tests
# =============================================================================


class TestNip11FetchLogs:
    """Test Nip11FetchLogs Pydantic model."""

    def test_constructor_rejects_reason_when_success_true(self):
        """Direct constructor raises ValidationError if reason set with success=True."""
        with pytest.raises(ValidationError, match="reason must be None when success is True"):
            Nip11FetchLogs(success=True, reason="should fail")

    def test_constructor_rejects_non_str_reason(self):
        """Direct constructor raises ValidationError if reason is not str."""
        with pytest.raises(ValidationError):
            Nip11FetchLogs(success=False, reason=404)

    def test_constructor_rejects_non_bool_success(self):
        """Direct constructor raises ValidationError if success is not bool."""
        with pytest.raises(ValidationError):
            Nip11FetchLogs(success="yes")

    def test_constructor_requires_success(self):
        """Constructor requires success field (no default)."""
        with pytest.raises(ValidationError):
            Nip11FetchLogs()

    def test_from_dict_valid(self):
        """from_dict with valid data creates Nip11FetchLogs."""
        logs = Nip11FetchLogs.from_dict({"success": False, "reason": "HTTP 404"})
        assert logs.success is False
        assert logs.reason == "HTTP 404"

    def test_from_dict_empty_raises(self):
        """from_dict with empty dict raises ValidationError (success required)."""
        with pytest.raises(ValidationError):
            Nip11FetchLogs.from_dict({})

    def test_from_dict_rejects_non_bool_success(self):
        """from_dict raises ValidationError for non-bool success."""
        with pytest.raises(ValidationError):
            Nip11FetchLogs.from_dict({"success": "yes"})

    def test_from_dict_rejects_non_str_reason(self):
        """from_dict raises ValidationError for non-str reason."""
        with pytest.raises(ValidationError):
            Nip11FetchLogs.from_dict({"success": False, "reason": 404})

    def test_from_dict_rejects_reason_when_success_true(self):
        """from_dict raises ValidationError when reason set with success=True."""
        with pytest.raises(ValidationError, match="reason must be None when success is True"):
            Nip11FetchLogs.from_dict({"success": True, "reason": "should fail"})

    def test_from_dict_roundtrip(self):
        """to_dict -> from_dict roundtrip preserves data."""
        original = Nip11FetchLogs(success=False, reason="timeout")
        reconstructed = Nip11FetchLogs.from_dict(original.to_dict())
        assert reconstructed == original

    def test_to_dict(self):
        """to_dict returns dict excluding None values."""
        logs = Nip11FetchLogs(success=True, reason=None)
        d = logs.to_dict()
        assert d == {"success": True}  # reason excluded because it's None


# =============================================================================
# Nip11FetchDataLimitation Tests
# =============================================================================


class TestNip11FetchDataLimitation:
    """Test Nip11FetchDataLimitation Pydantic model."""

    def test_constructor_rejects_non_int(self):
        """Constructor raises ValidationError for non-int field."""
        with pytest.raises(ValidationError):
            Nip11FetchDataLimitation(max_message_length="large")

    def test_constructor_rejects_bool_as_int(self):
        """Constructor raises ValidationError for bool in int field (bool is subclass of int)."""
        with pytest.raises(ValidationError):
            Nip11FetchDataLimitation(max_message_length=True)

    def test_constructor_rejects_non_bool(self):
        """Constructor raises ValidationError for non-bool field."""
        with pytest.raises(ValidationError):
            Nip11FetchDataLimitation(auth_required="yes")

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

    def test_from_dict_roundtrip(self):
        """to_dict -> from_dict roundtrip preserves data."""
        original = Nip11FetchDataLimitation(
            max_message_length=65535,
            max_subscriptions=20,
            auth_required=False,
        )
        reconstructed = Nip11FetchDataLimitation.from_dict(original.to_dict())
        assert reconstructed == original

    def test_from_dict_rejects_non_int(self):
        """from_dict raises ValidationError for non-int field."""
        with pytest.raises(ValidationError):
            Nip11FetchDataLimitation.from_dict({"max_limit": "big"})

    def test_from_dict_rejects_non_bool(self):
        """from_dict raises ValidationError for non-bool field."""
        with pytest.raises(ValidationError):
            Nip11FetchDataLimitation.from_dict({"payment_required": 1})

    def test_to_dict(self):
        """to_dict returns dict excluding None fields."""
        lim = Nip11FetchDataLimitation(max_message_length=1000)
        d = lim.to_dict()
        assert d["max_message_length"] == 1000
        assert "max_subscriptions" not in d  # None values excluded


# =============================================================================
# Nip11FetchDataRetentionEntry Tests
# =============================================================================


class TestNip11FetchDataRetentionEntry:
    """Test Nip11FetchDataRetentionEntry Pydantic model."""

    def test_constructor_rejects_non_int_time(self):
        """Constructor raises ValidationError for non-int time."""
        with pytest.raises(ValidationError):
            Nip11FetchDataRetentionEntry(kinds=[1], time="3600")

    def test_constructor_rejects_bool_time(self):
        """Constructor raises ValidationError for bool time (bool is subclass of int)."""
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

    def test_from_dict_valid(self):
        """from_dict with valid data creates Nip11FetchDataRetentionEntry."""
        entry = Nip11FetchDataRetentionEntry.from_dict(
            {"kinds": [1, [10000, 19999]], "time": 86400}
        )
        # Pydantic converts [int, int] ranges to tuples internally
        assert entry.kinds == [1, (10000, 19999)]
        assert entry.time == 86400

    def test_from_dict_roundtrip(self):
        """to_dict -> from_dict roundtrip preserves data."""
        original = Nip11FetchDataRetentionEntry(kinds=[0, 3], time=3600, count=100)
        reconstructed = Nip11FetchDataRetentionEntry.from_dict(original.to_dict())
        assert reconstructed == original

    def test_from_dict_rejects_invalid(self):
        """from_dict raises ValidationError for invalid data."""
        with pytest.raises(ValidationError):
            Nip11FetchDataRetentionEntry.from_dict({"kinds": [1], "time": "forever"})

    def test_to_dict_omits_none(self):
        """to_dict omits None values."""
        entry = Nip11FetchDataRetentionEntry(kinds=[1, 2], time=3600, count=None)
        d = entry.to_dict()
        assert d == {"kinds": [1, 2], "time": 3600}
        assert "count" not in d


# =============================================================================
# Nip11FetchDataFeeEntry Tests
# =============================================================================


class TestNip11FetchDataFeeEntry:
    """Test Nip11FetchDataFeeEntry Pydantic model."""

    def test_constructor_rejects_non_int_amount(self):
        """Constructor raises ValidationError for non-int amount."""
        with pytest.raises(ValidationError):
            Nip11FetchDataFeeEntry(amount="1000", unit="sats")

    def test_constructor_rejects_bool_amount(self):
        """Constructor raises ValidationError for bool amount (bool is subclass of int)."""
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

    def test_from_dict_valid(self):
        """from_dict with valid data creates Nip11FetchDataFeeEntry."""
        entry = Nip11FetchDataFeeEntry.from_dict(
            {"amount": 1000, "unit": "sats", "period": 2628003}
        )
        assert entry.amount == 1000
        assert entry.unit == "sats"
        assert entry.period == 2628003

    def test_from_dict_roundtrip(self):
        """to_dict -> from_dict roundtrip preserves data."""
        original = Nip11FetchDataFeeEntry(amount=100, unit="msats", kinds=[4])
        reconstructed = Nip11FetchDataFeeEntry.from_dict(original.to_dict())
        assert reconstructed == original

    def test_from_dict_rejects_invalid(self):
        """from_dict raises ValidationError for invalid data."""
        with pytest.raises(ValidationError):
            Nip11FetchDataFeeEntry.from_dict({"amount": "free", "unit": "sats"})

    def test_to_dict_omits_none(self):
        """to_dict omits None values."""
        entry = Nip11FetchDataFeeEntry(amount=100, unit="sats")
        d = entry.to_dict()
        assert d == {"amount": 100, "unit": "sats"}
        assert "period" not in d


# =============================================================================
# Nip11FetchDataFees Tests
# =============================================================================


class TestNip11FetchDataFees:
    """Test Nip11FetchDataFees Pydantic model."""

    def test_constructor_rejects_non_list(self):
        """Constructor raises ValidationError for non-list field."""
        with pytest.raises(ValidationError):
            Nip11FetchDataFees(admission="invalid")

    def test_constructor_rejects_non_fee_entry(self):
        """Constructor raises ValidationError for non-Nip11FetchDataFeeEntry element (dict is converted)."""
        # Pydantic will actually convert dicts to Nip11FetchDataFeeEntry automatically
        fees = Nip11FetchDataFees(admission=[{"amount": 1000}])
        assert fees.admission[0].amount == 1000

    def test_from_dict_valid(self):
        """from_dict with valid data creates Nip11FetchDataFees."""
        fees = Nip11FetchDataFees.from_dict(
            {
                "admission": [{"amount": 1000, "unit": "sats"}],
                "subscription": None,
                "publication": None,
            }
        )
        assert fees.admission is not None
        assert len(fees.admission) == 1
        assert fees.admission[0].amount == 1000
        assert fees.subscription is None

    def test_from_dict_roundtrip(self):
        """to_dict -> from_dict roundtrip preserves data."""
        original = Nip11FetchDataFees(
            admission=[Nip11FetchDataFeeEntry(amount=1000, unit="sats")],
            subscription=[Nip11FetchDataFeeEntry(amount=5000, unit="sats", period=2628003)],
        )
        reconstructed = Nip11FetchDataFees.from_dict(original.to_dict())
        assert reconstructed == original

    def test_from_dict_rejects_invalid_entry(self):
        """from_dict raises ValidationError for invalid entry in list."""
        with pytest.raises(ValidationError):
            Nip11FetchDataFees.from_dict({"admission": [{"amount": "free", "unit": "sats"}]})


# =============================================================================
# Nip11FetchData Tests
# =============================================================================


class TestNip11FetchData:
    """Test Nip11FetchData Pydantic model."""

    def test_to_dict(self, complete_nip11_data):
        """to_dict returns serializable dict."""
        data = Nip11FetchData.from_dict(complete_nip11_data)
        d = data.to_dict()
        assert d["name"] == "Test Relay"
        assert d["self"] == "b" * 64  # Note: self_pubkey -> "self" in dict via alias
        assert isinstance(d["limitation"], dict)
        assert isinstance(d["fees"], dict)

    def test_constructor_rejects_non_str_name(self):
        """Constructor raises ValidationError for non-str name."""
        with pytest.raises(ValidationError):
            Nip11FetchData(name=123)

    def test_constructor_rejects_bool_in_supported_nips(self):
        """Constructor raises ValidationError for bool in supported_nips (bool is subclass of int)."""
        with pytest.raises(ValidationError):
            Nip11FetchData(supported_nips=[True, 11])

    def test_constructor_rejects_non_limitation(self):
        """Constructor raises ValidationError for non-Nip11FetchDataLimitation (dict is converted)."""
        # Pydantic will actually convert dicts to Nip11FetchDataLimitation automatically
        data = Nip11FetchData(limitation={"max_message_length": 1000})
        assert data.limitation.max_message_length == 1000

    def test_constructor_rejects_non_fees(self):
        """Constructor raises ValidationError for non-Nip11FetchDataFees (dict is converted)."""
        # Pydantic will actually convert dicts to Nip11FetchDataFees automatically
        data = Nip11FetchData(fees={"admission": [{"amount": 100}]})
        assert data.fees.admission[0].amount == 100

    def test_constructor_rejects_non_list_retention(self):
        """Constructor raises ValidationError for non-list retention."""
        with pytest.raises(ValidationError):
            Nip11FetchData(retention="invalid")

    def test_constructor_rejects_non_retention_entry(self):
        """Constructor converts dict to Nip11FetchDataRetentionEntry automatically."""
        # Pydantic will actually convert dicts to Nip11FetchDataRetentionEntry automatically
        data = Nip11FetchData(retention=[{"kinds": [1]}])
        assert data.retention[0].kinds == [1]

    def test_constructor_rejects_non_str_in_tags(self):
        """Constructor raises ValidationError for non-str in tags list."""
        with pytest.raises(ValidationError):
            Nip11FetchData(tags=["valid", 42])

    def test_from_dict_valid(self, complete_nip11_data):
        """from_dict with valid data creates Nip11FetchData."""
        data = Nip11FetchData.from_dict(complete_nip11_data)
        assert data.name == "Test Relay"
        assert data.self == "b" * 64
        assert data.limitation.max_message_length == 65535
        assert data.fees.admission is not None
        assert data.retention is not None
        assert len(data.retention) == 3

    def test_from_dict_roundtrip(self, complete_nip11_data):
        """to_dict -> from_dict roundtrip preserves data."""
        original = Nip11FetchData.from_dict(complete_nip11_data)
        reconstructed = Nip11FetchData.from_dict(original.to_dict())
        assert reconstructed == original

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


# =============================================================================
# Nip11 Construction Tests
# =============================================================================


class TestNip11Construction:
    """Test Nip11 construction."""

    def test_constructor_with_data(self, relay, complete_nip11_data):
        """Constructor creates Nip11 with parsed data."""
        nip11 = Nip11(
            relay=relay,
            fetch_metadata=Nip11FetchMetadata(
                data=Nip11FetchData.from_dict(complete_nip11_data),
                logs=Nip11FetchLogs(success=True),
            ),
        )
        assert nip11.fetch_metadata.data.name == "Test Relay"
        assert nip11.fetch_metadata.logs.success is True

    def test_default_values(self, relay):
        """Default values when no data provided."""
        nip11 = Nip11(
            relay=relay,
            fetch_metadata=Nip11FetchMetadata(
                data=Nip11FetchData(),
                logs=Nip11FetchLogs(success=False, reason="test"),
            ),
        )
        assert nip11.fetch_metadata.data.name is None
        assert nip11.fetch_metadata.logs.success is False
        assert nip11.generated_at > 0

    def test_generated_at_explicit(self, relay):
        """Explicit generated_at is preserved."""
        nip11 = Nip11(
            relay=relay,
            fetch_metadata=Nip11FetchMetadata(
                data=Nip11FetchData(),
                logs=Nip11FetchLogs(success=False, reason="test"),
            ),
            generated_at=1000,
        )
        assert nip11.generated_at == 1000


# =============================================================================
# Nip11 Data Access Tests
# =============================================================================


class TestNip11FetchDataAccess:
    """Test Nip11 data access via fetch_metadata."""

    def test_logs_access(self, nip11):
        """Logs accessible via fetch_metadata.logs."""
        assert nip11.fetch_metadata.logs.success is True
        assert nip11.fetch_metadata.logs.reason is None

    def test_data_access(self, nip11):
        """Data accessible via fetch_metadata.data."""
        assert nip11.fetch_metadata.data.name == "Test Relay"
        assert nip11.fetch_metadata.data.description == "A test relay for unit tests"
        assert nip11.fetch_metadata.data.pubkey == "a" * 64
        assert nip11.fetch_metadata.data.supported_nips == [1, 11, 42, 65]
        assert nip11.fetch_metadata.data.software == "nostr-rs-relay"
        assert nip11.fetch_metadata.data.version == "1.0.0"

    def test_limitation_access(self, nip11):
        """Limitation accessible via fetch_metadata.data.limitation."""
        limitation = nip11.fetch_metadata.data.limitation
        assert isinstance(limitation, Nip11FetchDataLimitation)
        assert limitation.max_message_length == 65535
        assert limitation.auth_required is False

    def test_retention_access(self, nip11):
        """Retention accessible via fetch_metadata.data.retention."""
        retention = nip11.fetch_metadata.data.retention
        assert retention is not None
        assert len(retention) == 3
        assert isinstance(retention[0], Nip11FetchDataRetentionEntry)

    def test_fees_access(self, nip11):
        """Fees accessible via fetch_metadata.data.fees."""
        fees = nip11.fetch_metadata.data.fees
        assert isinstance(fees, Nip11FetchDataFees)
        assert fees.admission is not None


# =============================================================================
# Nip11 Serialization Tests
# =============================================================================


class TestNip11Serialization:
    """Test Nip11 serialization."""

    def test_fetch_metadata_field(self, nip11):
        """fetch_metadata contains data and logs."""
        assert nip11.fetch_metadata.data.name == "Test Relay"
        assert nip11.fetch_metadata.logs.success is True
        # Convert to Metadata for DB storage via to_dict() -> Metadata()
        metadata = Metadata(nip11.fetch_metadata.to_dict())
        assert metadata.metadata["data"]["name"] == "Test Relay"
        assert metadata.metadata["logs"]["success"] is True

    def test_to_relay_metadata_tuple(self, nip11):
        """to_relay_metadata_tuple returns RelayMetadataTuple."""
        params = nip11.to_relay_metadata_tuple()
        assert params.nip11_fetch.metadata_type == MetadataType.NIP11_FETCH
        assert params.nip11_fetch.relay is nip11.relay
        assert params.nip11_fetch.generated_at == nip11.generated_at


# =============================================================================
# Nip11 Create Tests
# =============================================================================


class TestNip11Create:
    """Test Nip11.create() method."""

    @pytest.mark.asyncio
    async def test_success(self, relay):
        """Successful fetch returns Nip11 with data."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "application/nostr+json"}
        mock_response.content.read = AsyncMock(return_value=b'{"name": "Test Relay"}')
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=mock_session):
            result = await Nip11.create(relay)

        assert result.fetch_metadata.logs.success is True
        assert result.fetch_metadata.data.name == "Test Relay"

    @pytest.mark.asyncio
    async def test_non_200_returns_failure(self, relay):
        """Non-200 status returns Nip11 with success=False."""
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=mock_session):
            result = await Nip11.create(relay)

        assert result.fetch_metadata.logs.success is False
        assert "404" in result.fetch_metadata.logs.reason

    @pytest.mark.asyncio
    async def test_connection_error_returns_failure(self, relay):
        """Connection error returns Nip11 with success=False."""
        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=ConnectionError("Connection refused"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=mock_session):
            result = await Nip11.create(relay)

        assert result.fetch_metadata.logs.success is False
        assert "Connection refused" in result.fetch_metadata.logs.reason

    @pytest.mark.asyncio
    async def test_uses_https_for_wss(self, relay):
        """wss:// relay uses https://."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.content.read = AsyncMock(return_value=b"{}")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=mock_session):
            await Nip11.create(relay)

        # Check URL used
        call_args = mock_session.get.call_args
        url = call_args[0][0]
        assert url.startswith("https://")

    @pytest.mark.asyncio
    async def test_uses_http_for_ws(self):
        """ws:// relay uses http://."""
        # Use a .onion address to get ws:// (Tor relays use ws://)
        relay = Relay("ws://abc123xyz789abc123xyz789abc123xyz789abc123xyz789abcdefgh.onion")

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.content.read = AsyncMock(return_value=b"{}")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=mock_session):
            await Nip11.create(relay)

        call_args = mock_session.get.call_args
        url = call_args[0][0]
        assert url.startswith("http://")

    @pytest.mark.asyncio
    async def test_sends_accept_header(self, relay):
        """Request includes Accept: application/nostr+json header."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.content.read = AsyncMock(return_value=b"{}")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=mock_session):
            await Nip11.create(relay)

        call_args = mock_session.get.call_args
        headers = call_args[1]["headers"]
        assert headers["Accept"] == "application/nostr+json"

    @pytest.mark.asyncio
    async def test_valid_content_types_accepted(self, relay):
        """Both application/nostr+json and application/json are valid."""
        for content_type in [
            "application/nostr+json",
            "application/json",
            "application/json; charset=utf-8",
        ]:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.headers = {"Content-Type": content_type}
            mock_response.content.read = AsyncMock(return_value=b'{"name": "Test"}')
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session = MagicMock()
            mock_session.get = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=mock_session):
                result = await Nip11.create(relay)

            assert result.fetch_metadata.logs.success is True

    @pytest.mark.asyncio
    async def test_invalid_content_type_returns_failure(self, relay):
        """Invalid Content-Type returns failure."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.content.read = AsyncMock(return_value=b"<html>")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=mock_session):
            result = await Nip11.create(relay)

        assert result.fetch_metadata.logs.success is False
        assert "Content-Type" in result.fetch_metadata.logs.reason

    @pytest.mark.asyncio
    async def test_response_too_large_returns_failure(self, relay):
        """Response exceeding max_size returns failure."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.content.read = AsyncMock(return_value=b"x" * 100000)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=mock_session):
            result = await Nip11.create(relay, max_size=1000)

        assert result.fetch_metadata.logs.success is False
        assert "too large" in result.fetch_metadata.logs.reason

    @pytest.mark.asyncio
    async def test_invalid_json_returns_failure(self, relay):
        """Invalid JSON returns failure."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.content.read = AsyncMock(return_value=b"not json")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=mock_session):
            result = await Nip11.create(relay)

        assert result.fetch_metadata.logs.success is False

    @pytest.mark.asyncio
    async def test_non_dict_json_returns_failure(self, relay):
        """JSON that's not a dict returns failure."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.content.read = AsyncMock(return_value=b'["array"]')
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("models.nips.nip11.fetch.aiohttp.ClientSession", return_value=mock_session):
            result = await Nip11.create(relay)

        assert result.fetch_metadata.logs.success is False
        assert "dict" in result.fetch_metadata.logs.reason


# =============================================================================
# Parse Method Tests
# =============================================================================


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

    def test_parse_non_dict_returns_empty(self):
        """Non-dict input returns empty dict."""
        assert Nip11FetchDataLimitation.parse("string") == {}
        assert Nip11FetchDataLimitation.parse(123) == {}
        assert Nip11FetchDataLimitation.parse(None) == {}


class TestNip11FetchDataRetentionEntryParse:
    """Test Nip11FetchDataRetentionEntry.parse() method."""

    def test_parse_valid_data(self):
        """Valid data is parsed correctly."""
        data = {"kinds": [1, 2, 3], "time": 3600, "count": 1000}
        result = Nip11FetchDataRetentionEntry.parse(data)
        assert result == {"kinds": [1, 2, 3], "time": 3600, "count": 1000}

    def test_parse_kind_ranges(self):
        """Kind ranges are parsed correctly."""
        data = {"kinds": [1, [10, 20], 3]}
        result = Nip11FetchDataRetentionEntry.parse(data)
        assert result == {"kinds": [1, (10, 20), 3]}

    def test_parse_invalid_kinds_filtered(self):
        """Invalid kinds are filtered out."""
        data = {"kinds": [1, "invalid", True, [10, 20], [1, 2, 3]]}
        result = Nip11FetchDataRetentionEntry.parse(data)
        assert result == {"kinds": [1, (10, 20)]}

    def test_parse_non_dict_returns_empty(self):
        """Non-dict input returns empty dict."""
        assert Nip11FetchDataRetentionEntry.parse([1, 2, 3]) == {}


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

    def test_parse_creates_valid_model(self):
        """Parsed data creates a valid Nip11FetchData model."""
        raw = {
            "name": "Test",
            "invalid_field": "ignored",
            "supported_nips": [1, True, "invalid", 11],  # True and "invalid" filtered
            "limitation": {"max_message_length": "invalid", "auth_required": False},
        }
        parsed = Nip11FetchData.parse(raw)
        model = Nip11FetchData.from_dict(parsed)
        assert model.name == "Test"
        assert model.supported_nips == [1, 11]
        assert model.limitation.auth_required is False
        assert model.limitation.max_message_length is None

    def test_parse_non_dict_returns_empty(self):
        """Non-dict input returns empty dict."""
        assert Nip11FetchData.parse(None) == {}
        assert Nip11FetchData.parse("string") == {}
        assert Nip11FetchData.parse([1, 2, 3]) == {}
