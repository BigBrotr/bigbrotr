"""Unit tests for the Relay model and NetworkType enum."""

from dataclasses import FrozenInstanceError
from time import time

import pytest

from bigbrotr.models.constants import NetworkType
from bigbrotr.models.relay import Relay, RelayDbParams


# =============================================================================
# NetworkType Enum Tests
# =============================================================================


class TestNetworkTypeEnum:
    """NetworkType StrEnum."""

    def test_all_valid_types(self):
        """All expected network types exist."""
        valid = {member.value for member in NetworkType}
        assert valid == {"clearnet", "tor", "i2p", "loki", "local", "unknown"}

    def test_str_compatibility(self):
        """NetworkType values are string compatible."""
        assert NetworkType.CLEARNET == "clearnet"
        assert NetworkType.TOR == "tor"
        assert NetworkType.I2P == "i2p"
        assert NetworkType.LOKI == "loki"
        assert NetworkType.LOCAL == "local"
        assert NetworkType.UNKNOWN == "unknown"

    def test_str_conversion(self):
        """str() converts to string value."""
        assert str(NetworkType.CLEARNET) == "clearnet"
        assert str(NetworkType.TOR) == "tor"
        assert str(NetworkType.I2P) == "i2p"
        assert str(NetworkType.LOKI) == "loki"

    def test_can_use_as_dict_key(self):
        """NetworkType can be used as dict key."""
        d = {NetworkType.CLEARNET: 1, NetworkType.TOR: 2}
        assert d[NetworkType.CLEARNET] == 1
        assert d["clearnet"] == 1


# =============================================================================
# URL Parsing Tests
# =============================================================================


class TestUrlParsing:
    """URL parsing and normalization."""

    def test_simple_wss_clearnet(self):
        """Simple wss:// clearnet URL."""
        r = Relay("wss://relay.example.com")
        assert r.url == "wss://relay.example.com"
        assert r.scheme == "wss"
        assert r.host == "relay.example.com"
        assert r.network == NetworkType.CLEARNET
        assert r.port is None
        assert r.path is None

    def test_ws_clearnet_upgraded_to_wss(self):
        """Clearnet ws:// gets upgraded to wss://."""
        r = Relay("ws://relay.example.com")
        assert r.scheme == "wss"
        assert r.url == "wss://relay.example.com"
        assert r.network == NetworkType.CLEARNET

    def test_explicit_port(self):
        """Explicit port is preserved."""
        r = Relay("wss://relay.example.com:8080")
        assert r.url == "wss://relay.example.com:8080"
        assert r.port == 8080
        assert r.host == "relay.example.com"

    def test_default_port_443_omitted(self):
        """Default wss port (443) is omitted from URL but preserved in port field."""
        r = Relay("wss://relay.example.com:443")
        assert r.url == "wss://relay.example.com"
        assert r.port == 443

    def test_port_80_preserved_for_wss(self):
        """Port 80 is preserved when scheme becomes wss (not default)."""
        r = Relay("ws://relay.example.com:80")
        assert r.url == "wss://relay.example.com:80"
        assert r.port == 80
        assert r.scheme == "wss"

    def test_path_preserved(self):
        """Path is preserved."""
        r = Relay("wss://relay.example.com/nostr")
        assert r.path == "/nostr"
        assert r.url == "wss://relay.example.com/nostr"

    def test_trailing_slash_removed(self):
        """Trailing slash is removed."""
        r = Relay("wss://relay.example.com/")
        assert r.path is None
        assert r.url == "wss://relay.example.com"

    def test_double_slashes_normalized(self):
        """Double slashes in path are normalized."""
        r = Relay("wss://relay.example.com//nostr//")
        assert r.path == "/nostr"

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace is stripped."""
        r = Relay("  wss://relay.example.com  ")
        assert r.url == "wss://relay.example.com"

    def test_ipv4_address(self):
        """IPv4 address is parsed correctly."""
        r = Relay("wss://8.8.8.8")
        assert r.host == "8.8.8.8"
        assert r.network == NetworkType.CLEARNET

    def test_ipv6_address(self):
        """IPv6 address is parsed correctly."""
        r = Relay("wss://[2001:4860:4860::8888]")
        assert r.host == "2001:4860:4860::8888"
        assert r.network == NetworkType.CLEARNET
        assert r.url == "wss://[2001:4860:4860::8888]"

    def test_ipv6_with_port(self):
        """IPv6 address with port is parsed correctly."""
        r = Relay("wss://[2606:4700::1]:8080")
        assert r.host == "2606:4700::1"
        assert r.port == 8080
        assert r.url == "wss://[2606:4700::1]:8080"

    def test_subdomain(self):
        """Subdomain is preserved."""
        r = Relay("wss://nostr.relay.example.com")
        assert r.host == "nostr.relay.example.com"

    def test_deep_path(self):
        """Deep path is preserved."""
        r = Relay("wss://relay.example.com/api/v1/nostr")
        assert r.path == "/api/v1/nostr"

    def test_port_and_path(self):
        """Port and path together."""
        r = Relay("wss://relay.example.com:8080/nostr")
        assert r.port == 8080
        assert r.path == "/nostr"
        assert r.url == "wss://relay.example.com:8080/nostr"


# =============================================================================
# Network Detection Tests
# =============================================================================


class TestNetworkDetection:
    """Network type detection."""

    def test_tor_onion(self):
        """Tor .onion addresses are detected."""
        r = Relay("wss://abc123.onion")
        assert r.network == NetworkType.TOR
        assert r.scheme == "ws"  # Overlay networks use ws://
        assert r.url == "ws://abc123.onion"

    def test_i2p(self):
        """I2P .i2p addresses are detected."""
        r = Relay("wss://relay.i2p")
        assert r.network == NetworkType.I2P
        assert r.scheme == "ws"
        assert r.url == "ws://relay.i2p"

    def test_loki(self):
        """Lokinet .loki addresses are detected."""
        r = Relay("wss://relay.loki")
        assert r.network == NetworkType.LOKI
        assert r.scheme == "ws"
        assert r.url == "ws://relay.loki"

    def test_clearnet_domain(self):
        """Regular domains are clearnet."""
        r = Relay("ws://relay.example.com")
        assert r.network == NetworkType.CLEARNET
        assert r.scheme == "wss"  # Clearnet uses wss://

    def test_case_insensitive_tld(self):
        """TLD detection is case insensitive."""
        assert Relay._detect_network("ABC.ONION") == NetworkType.TOR
        assert Relay._detect_network("RELAY.I2P") == NetworkType.I2P
        assert Relay._detect_network("TEST.LOKI") == NetworkType.LOKI

    def test_detect_local_localhost(self):
        """localhost is detected as local."""
        assert Relay._detect_network("localhost") == NetworkType.LOCAL
        assert Relay._detect_network("localhost.localdomain") == NetworkType.LOCAL

    def test_detect_local_loopback_ipv4(self):
        """127.x.x.x addresses are local."""
        assert Relay._detect_network("127.0.0.1") == NetworkType.LOCAL
        assert Relay._detect_network("127.0.0.254") == NetworkType.LOCAL

    def test_detect_local_private_ipv4(self):
        """Private IPv4 ranges are local."""
        assert Relay._detect_network("10.0.0.1") == NetworkType.LOCAL
        assert Relay._detect_network("172.16.0.1") == NetworkType.LOCAL
        assert Relay._detect_network("172.31.255.255") == NetworkType.LOCAL
        assert Relay._detect_network("192.168.1.1") == NetworkType.LOCAL

    def test_detect_local_link_local(self):
        """Link-local addresses are local."""
        assert Relay._detect_network("169.254.0.1") == NetworkType.LOCAL

    def test_detect_local_ipv6_loopback(self):
        """IPv6 loopback is local."""
        assert Relay._detect_network("::1") == NetworkType.LOCAL

    def test_detect_unknown_empty(self):
        """Empty string returns unknown."""
        assert Relay._detect_network("") == NetworkType.UNKNOWN

    def test_detect_unknown_invalid_label(self):
        """Invalid domain labels return unknown."""
        assert Relay._detect_network("invalid-host-") == NetworkType.UNKNOWN
        assert Relay._detect_network("-invalid.host") == NetworkType.UNKNOWN

    def test_detect_clearnet_public_ip(self):
        """Public IP addresses are clearnet."""
        assert Relay._detect_network("8.8.8.8") == NetworkType.CLEARNET
        assert Relay._detect_network("1.1.1.1") == NetworkType.CLEARNET


# =============================================================================
# Rejection Tests
# =============================================================================


class TestRejection:
    """Invalid URLs are rejected."""

    @pytest.mark.parametrize(
        "url",
        [
            "wss://localhost",
            "wss://localhost.localdomain",
            "wss://127.0.0.1",
            "wss://127.0.0.254",
            "wss://10.0.0.1",
            "wss://10.255.255.255",
            "wss://172.16.0.1",
            "wss://172.31.255.255",
            "wss://192.168.1.1",
            "wss://192.168.255.255",
            "wss://169.254.0.1",
            "wss://[::1]",
            "wss://[fe80::1]",
        ],
    )
    def test_local_addresses_rejected(self, url):
        """Local/private addresses are rejected."""
        with pytest.raises(ValueError, match="Local addresses"):
            Relay(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://relay.example.com",
            "https://relay.example.com",
            "ftp://relay.example.com",
        ],
    )
    def test_invalid_scheme_rejected(self, url):
        """Non-websocket schemes are rejected."""
        with pytest.raises(ValueError, match="Invalid scheme"):
            Relay(url)

    @pytest.mark.parametrize(
        "url",
        [
            "relay.example.com",
            "",
        ],
    )
    def test_missing_scheme_rejected(self, url):
        """URLs without scheme are rejected."""
        with pytest.raises(ValueError):
            Relay(url)

    def test_invalid_host_rejected(self):
        """Invalid hostnames are rejected."""
        with pytest.raises(ValueError, match="Invalid host"):
            Relay("wss://invalid_host")

    def test_single_label_rejected(self):
        """Single-label hosts (no TLD) are rejected unless overlay."""
        with pytest.raises(ValueError, match="Invalid host"):
            Relay("wss://singlehost")


# =============================================================================
# Null Byte Sanitization Tests
# =============================================================================


class TestNullByteValidation:
    """Null bytes in URLs are rejected for PostgreSQL compatibility."""

    def test_null_byte_in_host_rejected(self):
        """Null bytes in host raise ValueError."""
        with pytest.raises(ValueError, match="null bytes"):
            Relay("wss://relay\x00.example.com")

    def test_null_byte_in_path_rejected(self):
        """Null bytes in path raise ValueError."""
        with pytest.raises(ValueError, match="null bytes"):
            Relay("wss://relay.example.com/path\x00here")

    def test_multiple_null_bytes_rejected(self):
        """Multiple null bytes raise ValueError."""
        with pytest.raises(ValueError, match="null bytes"):
            Relay("wss://\x00relay\x00.example\x00.com\x00")

    def test_url_without_null_bytes_unchanged(self):
        """URLs without null bytes are processed normally."""
        r = Relay("wss://relay.example.com:8080/path")
        assert r.url == "wss://relay.example.com:8080/path"

    def test_query_string_rejected(self):
        """Relay URLs with query strings are rejected."""
        with pytest.raises(ValueError, match="query string"):
            Relay("wss://relay.example.com?key=value")

    def test_fragment_rejected(self):
        """Relay URLs with fragments are rejected."""
        with pytest.raises(ValueError, match="fragment"):
            Relay("wss://relay.example.com#section")


# =============================================================================
# Immutability Tests
# =============================================================================


class TestImmutability:
    """Frozen dataclass behavior."""

    def test_url_mutation_blocked(self):
        """Cannot modify url attribute."""
        r = Relay("wss://relay.example.com")
        with pytest.raises(FrozenInstanceError):
            r.url = "wss://other.relay"

    def test_network_mutation_blocked(self):
        """Cannot modify network attribute."""
        r = Relay("wss://relay.example.com")
        with pytest.raises(FrozenInstanceError):
            r.network = NetworkType.TOR

    def test_host_mutation_blocked(self):
        """Cannot modify host attribute."""
        r = Relay("wss://relay.example.com")
        with pytest.raises(FrozenInstanceError):
            r.host = "other.host"

    def test_port_mutation_blocked(self):
        """Cannot modify port attribute."""
        r = Relay("wss://relay.example.com:8080")
        with pytest.raises(FrozenInstanceError):
            r.port = 9090

    def test_scheme_mutation_blocked(self):
        """Cannot modify scheme attribute."""
        r = Relay("wss://relay.example.com")
        with pytest.raises(FrozenInstanceError):
            r.scheme = "ws"

    def test_new_attribute_blocked(self):
        """Cannot add new attributes."""
        r = Relay("wss://relay.example.com")
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            r.new_attr = "value"


# =============================================================================
# Timestamp Tests
# =============================================================================


class TestTimestamp:
    """discovered_at timestamp handling."""

    def test_defaults_to_now(self):
        """discovered_at defaults to current time."""
        before = int(time())
        r = Relay("wss://relay.example.com")
        after = int(time())
        assert before <= r.discovered_at <= after

    def test_explicit_timestamp(self):
        """Explicit discovered_at is preserved."""
        r = Relay("wss://relay.example.com", discovered_at=1234567890)
        assert r.discovered_at == 1234567890

    def test_timestamp_zero(self):
        """discovered_at can be zero (epoch)."""
        r = Relay("wss://relay.example.com", discovered_at=0)
        assert r.discovered_at == 0


# =============================================================================
# to_db_params Tests
# =============================================================================


class TestToDbParams:
    """Relay.to_db_params() serialization."""

    def test_returns_relay_db_params(self):
        """Returns RelayDbParams NamedTuple."""
        r = Relay("wss://relay.example.com", discovered_at=1234567890)
        params = r.to_db_params()
        assert isinstance(params, RelayDbParams)
        assert len(params) == 3

    def test_structure_clearnet(self):
        """Clearnet relay parameters are correct."""
        r = Relay("wss://relay.example.com", discovered_at=1234567890)
        params = r.to_db_params()
        assert params.url == "wss://relay.example.com"
        assert params.network == "clearnet"
        assert params.discovered_at == 1234567890

    def test_structure_tor(self):
        """Tor relay uses ws:// scheme in params."""
        r = Relay("wss://abc123.onion", discovered_at=1234567890)
        params = r.to_db_params()
        assert params.url == "ws://abc123.onion"
        assert params.network == "tor"

    def test_with_port_and_path(self):
        """Port and path are included in URL."""
        r = Relay("wss://relay.example.com:8080/nostr", discovered_at=1234567890)
        params = r.to_db_params()
        assert params.url == "wss://relay.example.com:8080/nostr"

    def test_network_is_string_value(self):
        """Network is string value from enum."""
        r = Relay("wss://relay.example.com")
        params = r.to_db_params()
        assert isinstance(params.network, str)
        assert params.network == "clearnet"


# =============================================================================
# Equality Tests
# =============================================================================


class TestEquality:
    """Equality and hashing."""

    def test_equal_same_url_and_timestamp(self):
        """Relays with same URL and timestamp are equal."""
        r1 = Relay("wss://relay.example.com", discovered_at=1234567890)
        r2 = Relay("wss://relay.example.com", discovered_at=1234567890)
        assert r1 == r2

    def test_different_url(self):
        """Relays with different URLs are not equal."""
        r1 = Relay("wss://relay1.example.com", discovered_at=1234567890)
        r2 = Relay("wss://relay2.example.com", discovered_at=1234567890)
        assert r1 != r2

    def test_different_timestamp(self):
        """Relays with different timestamps are not equal."""
        r1 = Relay("wss://relay.example.com", discovered_at=1234567890)
        r2 = Relay("wss://relay.example.com", discovered_at=9999999999)
        assert r1 != r2

    def test_hashable(self):
        """Relay is hashable."""
        r1 = Relay("wss://relay.example.com", discovered_at=1234567890)
        r2 = Relay("wss://relay.example.com", discovered_at=1234567890)
        assert hash(r1) == hash(r2)

    def test_set_deduplication(self):
        """Relay can be used in sets for deduplication."""
        r1 = Relay("wss://relay.example.com", discovered_at=1234567890)
        r2 = Relay("wss://relay.example.com", discovered_at=1234567890)
        r3 = Relay("wss://other.relay.com", discovered_at=1234567890)
        s = {r1, r2, r3}
        assert len(s) == 2


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_url_case_normalized(self):
        """URL host is case-normalized."""
        r = Relay("wss://RELAY.EXAMPLE.COM")
        assert r.host == "relay.example.com"

    def test_long_hostname(self):
        """Long hostname is handled."""
        long_subdomain = "a" * 63
        url = f"wss://{long_subdomain}.example.com"
        r = Relay(url)
        assert r.host == f"{long_subdomain}.example.com"

    def test_numeric_tld(self):
        """Numeric TLD in onion address."""
        r = Relay("wss://abc123xyz789.onion")
        assert r.network == NetworkType.TOR

    def test_default_port_80_for_ws(self):
        """Default port for ws:// overlay is 80."""
        r = Relay("wss://abc.onion:80")
        assert r.url == "ws://abc.onion"
        assert r.port == 80


# =============================================================================
# Type Validation Tests
# =============================================================================


class TestTypeValidation:
    """Runtime type validation in __post_init__."""

    def test_raw_url_non_string_rejected(self):
        """raw_url must be a str."""
        with pytest.raises(TypeError, match="raw_url must be a str"):
            Relay(raw_url=12345, discovered_at=1234567890)  # type: ignore[arg-type]

    def test_discovered_at_non_int_rejected(self):
        """discovered_at must be an int."""
        with pytest.raises(TypeError, match="discovered_at must be an int"):
            Relay(raw_url="wss://relay.example.com", discovered_at="abc")  # type: ignore[arg-type]

    def test_discovered_at_float_rejected(self):
        """discovered_at must be an int, not a float."""
        with pytest.raises(TypeError, match="discovered_at must be an int"):
            Relay(raw_url="wss://relay.example.com", discovered_at=1.5)  # type: ignore[arg-type]

    def test_discovered_at_bool_rejected(self):
        """bool is not accepted as int for discovered_at."""
        with pytest.raises(TypeError, match="discovered_at must be an int"):
            Relay(raw_url="wss://relay.example.com", discovered_at=True)  # type: ignore[arg-type]

    def test_discovered_at_negative_rejected(self):
        """discovered_at must be non-negative."""
        with pytest.raises(ValueError, match="discovered_at must be non-negative"):
            Relay(raw_url="wss://relay.example.com", discovered_at=-1)

    def test_discovered_at_zero_accepted(self):
        """discovered_at=0 (epoch) is valid."""
        r = Relay(raw_url="wss://relay.example.com", discovered_at=0)
        assert r.discovered_at == 0
