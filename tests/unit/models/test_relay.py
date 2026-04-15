"""Unit tests for the Relay model."""

from dataclasses import FrozenInstanceError
from time import time

import pytest

from bigbrotr.models.constants import NetworkType
from bigbrotr.models.relay import Relay, RelayDbParams
from bigbrotr.models.relay_url import (
    _MAX_URL_LENGTH,
    detect_relay_network,
    normalize_relay_url,
)
from tests.fixtures.relays import LOKI_HOST, ONION_HOST


# =============================================================================
# URL Parsing Tests
# =============================================================================


class TestUrlParsing:
    """URL parsing and normalization."""

    def test_simple_wss_clearnet(self):
        r = Relay("wss://relay.example.com")
        assert r.url == "wss://relay.example.com"
        assert r.scheme == "wss"
        assert r.host == "relay.example.com"
        assert r.network == NetworkType.CLEARNET
        assert r.port is None
        assert r.path is None

    def test_ws_clearnet_not_canonical(self):
        with pytest.raises(ValueError, match="not in canonical form"):
            Relay("ws://relay.example.com")

    def test_explicit_port(self):
        r = Relay("wss://relay.example.com:8080")
        assert r.url == "wss://relay.example.com:8080"
        assert r.port == 8080
        assert r.host == "relay.example.com"

    def test_default_port_443_not_canonical(self):
        with pytest.raises(ValueError, match="not in canonical form"):
            Relay("wss://relay.example.com:443")

    def test_port_80_not_canonical_with_ws(self):
        with pytest.raises(ValueError, match="not in canonical form"):
            Relay("ws://relay.example.com:80")

    def test_path_preserved(self):
        r = Relay("wss://relay.example.com/nostr")
        assert r.path == "/nostr"
        assert r.url == "wss://relay.example.com/nostr"

    def test_trailing_slash_not_canonical(self):
        with pytest.raises(ValueError, match="not in canonical form"):
            Relay("wss://relay.example.com/")

    def test_double_slashes_not_canonical(self):
        with pytest.raises(ValueError, match="not in canonical form"):
            Relay("wss://relay.example.com//nostr//")

    def test_whitespace_not_canonical(self):
        with pytest.raises(ValueError, match="not in canonical form"):
            Relay("  wss://relay.example.com  ")

    def test_ipv4_address(self):
        r = Relay("wss://8.8.8.8")
        assert r.host == "8.8.8.8"
        assert r.network == NetworkType.CLEARNET

    def test_ipv6_address(self):
        r = Relay("wss://[2001:4860:4860::8888]")
        assert r.host == "2001:4860:4860::8888"
        assert r.network == NetworkType.CLEARNET
        assert r.url == "wss://[2001:4860:4860::8888]"

    def test_ipv6_with_port(self):
        r = Relay("wss://[2606:4700::1]:8080")
        assert r.host == "2606:4700::1"
        assert r.port == 8080
        assert r.url == "wss://[2606:4700::1]:8080"

    def test_subdomain(self):
        r = Relay("wss://nostr.relay.example.com")
        assert r.host == "nostr.relay.example.com"

    def test_deep_path(self):
        r = Relay("wss://relay.example.com/api/v1/nostr")
        assert r.path == "/api/v1/nostr"

    def test_port_and_path(self):
        r = Relay("wss://relay.example.com:8080/nostr")
        assert r.port == 8080
        assert r.path == "/nostr"
        assert r.url == "wss://relay.example.com:8080/nostr"

    @pytest.mark.parametrize(
        ("url", "expected_path"),
        [
            ("wss://haven.example.com/inbox", "/inbox"),
            ("wss://haven.example.com/outbox", "/outbox"),
            ("wss://haven.example.com/chat", "/chat"),
            ("wss://hypertuna.com/npub1abc123def456/groupName", "/npub1abc123def456/groupName"),
            ("wss://lang.relays.land/it", "/it"),
            ("wss://cache.primal.net/v1", "/v1"),
            ("wss://lnbits.example.com/nostrclient/api/v1/relay", "/nostrclient/api/v1/relay"),
            ("wss://relay.example.com/nostrrelay/myRelay", "/nostrrelay/myRelay"),
            ("wss://pyramid.example.com/favorites", "/favorites"),
            ("wss://relay.example.com/npub1abc:groupName", "/npub1abc:groupName"),
        ],
    )
    def test_legitimate_paths_accepted(self, url, expected_path):
        r = Relay(url)
        assert r.path == expected_path


# =============================================================================
# Network Detection Tests
# =============================================================================


class TestNetworkDetection:
    """Network type detection via detect_relay_network()."""

    def test_tor_onion(self):
        r = Relay(f"ws://{ONION_HOST}.onion")
        assert r.network == NetworkType.TOR
        assert r.scheme == "ws"
        assert r.url == f"ws://{ONION_HOST}.onion"

    def test_tor_wss_not_canonical(self):
        with pytest.raises(ValueError, match="not in canonical form"):
            Relay(f"wss://{ONION_HOST}.onion")

    def test_i2p(self):
        r = Relay("ws://relay.i2p")
        assert r.network == NetworkType.I2P
        assert r.scheme == "ws"
        assert r.url == "ws://relay.i2p"

    def test_loki(self):
        r = Relay(f"ws://{LOKI_HOST}.loki")
        assert r.network == NetworkType.LOKI
        assert r.scheme == "ws"
        assert r.url == f"ws://{LOKI_HOST}.loki"

    def test_clearnet_domain(self):
        r = Relay("wss://relay.example.com")
        assert r.network == NetworkType.CLEARNET
        assert r.scheme == "wss"

    def test_case_insensitive_tld(self):
        assert detect_relay_network(ONION_HOST.upper() + ".ONION") == NetworkType.TOR
        assert detect_relay_network("RELAY.I2P") == NetworkType.I2P
        assert detect_relay_network(LOKI_HOST.upper() + ".LOKI") == NetworkType.LOKI

    def test_detect_local_localhost(self):
        assert detect_relay_network("localhost") == NetworkType.LOCAL
        assert detect_relay_network("localhost.localdomain") == NetworkType.LOCAL

    def test_detect_local_loopback_ipv4(self):
        assert detect_relay_network("127.0.0.1") == NetworkType.LOCAL
        assert detect_relay_network("127.0.0.254") == NetworkType.LOCAL

    def test_detect_local_private_ipv4(self):
        assert detect_relay_network("10.0.0.1") == NetworkType.LOCAL
        assert detect_relay_network("172.16.0.1") == NetworkType.LOCAL
        assert detect_relay_network("172.31.255.255") == NetworkType.LOCAL
        assert detect_relay_network("192.168.1.1") == NetworkType.LOCAL

    def test_detect_local_link_local(self):
        assert detect_relay_network("169.254.0.1") == NetworkType.LOCAL

    def test_detect_local_ipv6_loopback(self):
        assert detect_relay_network("::1") == NetworkType.LOCAL

    def test_local_canonical_relay_preserves_wss_scheme(self):
        relay = Relay("wss://localhost")
        assert relay.network == NetworkType.LOCAL
        assert relay.scheme == "wss"
        assert relay.url == "wss://localhost"

    def test_local_canonical_relay_preserves_ws_scheme(self):
        relay = Relay("ws://127.0.0.1:7447")
        assert relay.network == NetworkType.LOCAL
        assert relay.scheme == "ws"
        assert relay.url == "ws://127.0.0.1:7447"

    def test_parse_local_relay_requires_explicit_policy(self):
        with pytest.raises(ValueError, match="Local addresses"):
            Relay.parse("wss://localhost")

        relay = Relay.parse("wss://localhost", allow_local=True)
        assert relay.network == NetworkType.LOCAL
        assert relay.url == "wss://localhost"

    def test_detect_unknown_empty(self):
        assert detect_relay_network("") == NetworkType.UNKNOWN

    def test_detect_unknown_single_label(self):
        assert detect_relay_network("singlehost") == NetworkType.UNKNOWN

    def test_detect_unknown_invalid_label(self):
        assert detect_relay_network("invalid-host-") == NetworkType.UNKNOWN
        assert detect_relay_network("-invalid.host") == NetworkType.UNKNOWN

    def test_detect_clearnet_public_ip(self):
        assert detect_relay_network("8.8.8.8") == NetworkType.CLEARNET
        assert detect_relay_network("1.1.1.1") == NetworkType.CLEARNET

    def test_tor_subdomain_accepted(self):
        host = f"relay.{ONION_HOST}.onion"
        assert detect_relay_network(host) == NetworkType.TOR

    def test_tor_multi_subdomain_accepted(self):
        host = f"a.b.{ONION_HOST}.onion"
        assert detect_relay_network(host) == NetworkType.TOR

    def test_tor_invalid_subdomain_rejected(self):
        host = f"-bad.{ONION_HOST}.onion"
        assert detect_relay_network(host) == NetworkType.UNKNOWN

    def test_tor_fake_hash_rejected(self):
        assert detect_relay_network("dmsupermax.onion") == NetworkType.UNKNOWN
        assert detect_relay_network("nostr-relay.onion") == NetworkType.UNKNOWN

    def test_bare_overlay_tld_rejected(self):
        assert detect_relay_network(".onion") == NetworkType.UNKNOWN
        assert detect_relay_network(".i2p") == NetworkType.UNKNOWN
        assert detect_relay_network(".loki") == NetworkType.UNKNOWN

    def test_underscore_in_hostname_accepted(self):
        assert detect_relay_network("test_room.spaces.coracle.social") == NetworkType.CLEARNET
        assert detect_relay_network("a_b.example.com") == NetworkType.CLEARNET


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
    def test_local_addresses_rejected_by_default_parse_policy(self, url):
        with pytest.raises(ValueError, match="Local addresses"):
            Relay.parse(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://relay.example.com",
            "https://relay.example.com",
            "ftp://relay.example.com",
        ],
    )
    def test_invalid_scheme_rejected(self, url):
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
        with pytest.raises(ValueError):
            Relay(url)

    def test_invalid_host_rejected(self):
        with pytest.raises(ValueError, match="Invalid host"):
            Relay("wss://invalid_host")

    def test_single_label_rejected(self):
        with pytest.raises(ValueError, match="Invalid host"):
            Relay("wss://singlehost")

    @pytest.mark.parametrize(
        "url",
        [
            "wss://relay.example.com?key=value",
            "wss://relay.example.com#section",
            "wss://relay.example.com/%0Awss:/other.relay",
            "wss://relay.example.com/path%0D%0Amore",
            "wss://relay.example.com/%00hidden",
            "wss://relay.example.com/%09tab",
            "wss://relay.example.com/%20wss:/other.relay",
            "wss://relay.example.com/path%20path",
            "wss://atlas.nostr.land/wss://relay.damus.io/wss://nos.lol",
            "wss://relay.example.com/ws://other.relay",
            "wss://relay.example.com/http://example.com",
            "wss://relay.example.com/https://example.com",
        ],
    )
    def test_non_canonical_url_rejected(self, url):
        with pytest.raises(ValueError, match="not in canonical form"):
            Relay(url)


# =============================================================================
# Null Byte Validation Tests
# =============================================================================


class TestNullByteValidation:
    """Null bytes in URLs are rejected for PostgreSQL compatibility."""

    def test_null_byte_in_host_rejected(self):
        with pytest.raises(ValueError, match="null bytes"):
            Relay("wss://relay\x00.example.com")

    def test_null_byte_in_path_rejected(self):
        with pytest.raises(ValueError, match="null bytes"):
            Relay("wss://relay.example.com/path\x00here")

    def test_multiple_null_bytes_rejected(self):
        with pytest.raises(ValueError, match="null bytes"):
            Relay("wss://\x00relay\x00.example\x00.com\x00")


# =============================================================================
# Immutability Tests
# =============================================================================


class TestImmutability:
    """Frozen dataclass behavior."""

    def test_url_mutation_blocked(self):
        r = Relay("wss://relay.example.com")
        with pytest.raises(FrozenInstanceError):
            r.url = "wss://other.relay"

    def test_network_mutation_blocked(self):
        r = Relay("wss://relay.example.com")
        with pytest.raises(FrozenInstanceError):
            r.network = NetworkType.TOR

    def test_host_mutation_blocked(self):
        r = Relay("wss://relay.example.com")
        with pytest.raises(FrozenInstanceError):
            r.host = "other.host"

    def test_port_mutation_blocked(self):
        r = Relay("wss://relay.example.com:8080")
        with pytest.raises(FrozenInstanceError):
            r.port = 9090

    def test_scheme_mutation_blocked(self):
        r = Relay("wss://relay.example.com")
        with pytest.raises(FrozenInstanceError):
            r.scheme = "ws"

    def test_new_attribute_blocked(self):
        r = Relay("wss://relay.example.com")
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            r.new_attr = "value"


# =============================================================================
# Timestamp Tests
# =============================================================================


class TestTimestamp:
    """discovered_at timestamp handling."""

    def test_defaults_to_now(self):
        before = int(time())
        r = Relay("wss://relay.example.com")
        after = int(time())
        assert before <= r.discovered_at <= after

    def test_explicit_timestamp(self):
        r = Relay("wss://relay.example.com", discovered_at=1234567890)
        assert r.discovered_at == 1234567890

    def test_timestamp_zero(self):
        r = Relay("wss://relay.example.com", discovered_at=0)
        assert r.discovered_at == 0


# =============================================================================
# to_db_params Tests
# =============================================================================


class TestToDbParams:
    """Relay.to_db_params() serialization."""

    def test_returns_relay_db_params(self):
        r = Relay("wss://relay.example.com", discovered_at=1234567890)
        params = r.to_db_params()
        assert isinstance(params, RelayDbParams)
        assert len(params) == 3

    def test_structure_clearnet(self):
        r = Relay("wss://relay.example.com", discovered_at=1234567890)
        params = r.to_db_params()
        assert params.url == "wss://relay.example.com"
        assert params.network == "clearnet"
        assert params.discovered_at == 1234567890

    def test_structure_tor(self):
        r = Relay(f"ws://{ONION_HOST}.onion", discovered_at=1234567890)
        params = r.to_db_params()
        assert params.url == f"ws://{ONION_HOST}.onion"
        assert params.network == "tor"

    def test_with_port_and_path(self):
        r = Relay("wss://relay.example.com:8080/nostr", discovered_at=1234567890)
        params = r.to_db_params()
        assert params.url == "wss://relay.example.com:8080/nostr"

    def test_network_is_string_value(self):
        r = Relay("wss://relay.example.com")
        params = r.to_db_params()
        assert isinstance(params.network, str)
        assert params.network == "clearnet"

    def test_caching(self):
        r = Relay("wss://relay.example.com", discovered_at=1234567890)
        assert r.to_db_params() is r.to_db_params()


# =============================================================================
# Equality Tests
# =============================================================================


class TestEquality:
    """Equality and hashing."""

    def test_equal_same_url_and_timestamp(self):
        r1 = Relay("wss://relay.example.com", discovered_at=1234567890)
        r2 = Relay("wss://relay.example.com", discovered_at=1234567890)
        assert r1 == r2

    def test_different_url(self):
        r1 = Relay("wss://relay1.example.com", discovered_at=1234567890)
        r2 = Relay("wss://relay2.example.com", discovered_at=1234567890)
        assert r1 != r2

    def test_different_timestamp(self):
        r1 = Relay("wss://relay.example.com", discovered_at=1234567890)
        r2 = Relay("wss://relay.example.com", discovered_at=9999999999)
        assert r1 != r2

    def test_hashable(self):
        r1 = Relay("wss://relay.example.com", discovered_at=1234567890)
        r2 = Relay("wss://relay.example.com", discovered_at=1234567890)
        assert hash(r1) == hash(r2)

    def test_set_deduplication(self):
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

    def test_url_case_not_canonical(self):
        with pytest.raises(ValueError, match="not in canonical form"):
            Relay("wss://RELAY.EXAMPLE.COM")

    def test_long_hostname(self):
        long_subdomain = "a" * 63
        url = f"wss://{long_subdomain}.example.com"
        r = Relay(url)
        assert r.host == f"{long_subdomain}.example.com"

    def test_numeric_tld(self):
        r = Relay(f"ws://{ONION_HOST}.onion")
        assert r.network == NetworkType.TOR

    def test_default_port_80_for_ws_not_canonical(self):
        with pytest.raises(ValueError, match="not in canonical form"):
            Relay(f"wss://{ONION_HOST}.onion:80")


# =============================================================================
# Type Validation Tests
# =============================================================================


class TestTypeValidation:
    """Runtime type validation in __post_init__."""

    def test_url_non_string_rejected(self):
        with pytest.raises(TypeError, match="url must be a str"):
            Relay(url=12345, discovered_at=1234567890)  # type: ignore[arg-type]

    def test_discovered_at_non_int_rejected(self):
        with pytest.raises(TypeError, match="discovered_at must be an int"):
            Relay(url="wss://relay.example.com", discovered_at="abc")  # type: ignore[arg-type]

    def test_discovered_at_float_rejected(self):
        with pytest.raises(TypeError, match="discovered_at must be an int"):
            Relay(url="wss://relay.example.com", discovered_at=1.5)  # type: ignore[arg-type]

    def test_discovered_at_bool_rejected(self):
        with pytest.raises(TypeError, match="discovered_at must be an int"):
            Relay(url="wss://relay.example.com", discovered_at=True)  # type: ignore[arg-type]

    def test_discovered_at_negative_rejected(self):
        with pytest.raises(ValueError, match="discovered_at must be non-negative"):
            Relay(url="wss://relay.example.com", discovered_at=-1)

    def test_discovered_at_zero_accepted(self):
        r = Relay(url="wss://relay.example.com", discovered_at=0)
        assert r.discovered_at == 0


# =============================================================================
# normalize_relay_url Tests
# =============================================================================


class TestNormalizeRelayUrl:
    """normalize_relay_url() strips garbage while preserving valid components."""

    def test_clean_url_unchanged(self):
        assert normalize_relay_url("wss://relay.example.com") == "wss://relay.example.com"

    def test_clean_url_with_path_unchanged(self):
        assert (
            normalize_relay_url("wss://relay.example.com/inbox") == "wss://relay.example.com/inbox"
        )

    def test_strips_query_string(self):
        result = normalize_relay_url("wss://relay.example.com?key=value")
        assert result == "wss://relay.example.com"

    def test_strips_query_preserves_path(self):
        result = normalize_relay_url("wss://relay.example.com/v1?secret=abc123")
        assert result == "wss://relay.example.com/v1"

    def test_strips_fragment(self):
        result = normalize_relay_url("wss://relay.example.com#section")
        assert result == "wss://relay.example.com"

    def test_strips_query_and_fragment(self):
        result = normalize_relay_url("wss://relay.example.com/v1?key=val#top")
        assert result == "wss://relay.example.com/v1"

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("wss://relay.example.com/%0Awss:/other", "wss://relay.example.com"),
            ("wss://relay.example.com/path%0D%0Amore", "wss://relay.example.com"),
            ("wss://relay.example.com/%00hidden", "wss://relay.example.com"),
            ("wss://relay.example.com/%09tab", "wss://relay.example.com"),
        ],
    )
    def test_strips_path_with_control_characters(self, url, expected):
        assert normalize_relay_url(url) == expected

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("wss://relay.example.com/%20other", "wss://relay.example.com"),
            ("wss://relay.example.com/path%20path", "wss://relay.example.com"),
        ],
    )
    def test_strips_path_with_whitespace(self, url, expected):
        assert normalize_relay_url(url) == expected

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("wss://atlas.nostr.land/wss://relay.damus.io/wss://nos.lol", "wss://atlas.nostr.land"),
            ("wss://relay.example.com/ws://other.relay", "wss://relay.example.com"),
            ("wss://relay.example.com/http://example.com", "wss://relay.example.com"),
            ("wss://relay.example.com/https://example.com", "wss://relay.example.com"),
        ],
    )
    def test_strips_path_with_embedded_uri_scheme(self, url, expected):
        assert normalize_relay_url(url) == expected

    def test_preserves_port(self):
        result = normalize_relay_url("wss://relay.example.com:8080?q=1")
        assert result == "wss://relay.example.com:8080"

    def test_preserves_port_and_path(self):
        result = normalize_relay_url("wss://relay.example.com:8080/nostr?q=1")
        assert result == "wss://relay.example.com:8080/nostr"

    def test_collapses_double_slashes_in_path(self):
        result = normalize_relay_url("wss://relay.example.com//nostr//")
        assert result == "wss://relay.example.com/nostr"

    def test_strips_trailing_slash(self):
        result = normalize_relay_url("wss://relay.example.com/")
        assert result == "wss://relay.example.com"

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("wss://localhost", "wss://localhost"),
            ("ws://127.0.0.1:7447", "ws://127.0.0.1:7447"),
            ("wss://[::1]:7447", "wss://[::1]:7447"),
        ],
    )
    def test_allow_local_preserves_local_urls(self, url, expected):
        assert normalize_relay_url(url, allow_local=True) == expected

    def test_result_creates_valid_relay(self):
        dirty = "wss://relay.example.com/v1?secret=abc&lud16=user@host.com#top"
        clean = normalize_relay_url(dirty)
        r = Relay(clean)
        assert r.url == "wss://relay.example.com/v1"
        assert r.path == "/v1"

    def test_garbage_path_result_creates_valid_relay(self):
        dirty = "wss://relay.damus.io/%0Awss://nos.lol"
        clean = normalize_relay_url(dirty)
        r = Relay(clean)
        assert r.url == "wss://relay.damus.io"
        assert r.path is None

    def test_invalid_scheme_raises(self):
        with pytest.raises(ValueError, match="Invalid scheme"):
            normalize_relay_url("http://relay.example.com")

    def test_missing_host_raises(self):
        with pytest.raises(ValueError):
            normalize_relay_url("wss://")

    def test_no_scheme_raises(self):
        with pytest.raises(ValueError):
            normalize_relay_url("relay.example.com")

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            (f"wss://{ONION_HOST}.onion", f"ws://{ONION_HOST}.onion"),
            ("ws://relay.i2p/path?query", "ws://relay.i2p/path"),
            ("wss://relay.i2p:80", "ws://relay.i2p"),
            (f"wss://{LOKI_HOST}.loki:80/path", f"ws://{LOKI_HOST}.loki/path"),
            (f"ws://{LOKI_HOST}.loki", f"ws://{LOKI_HOST}.loki"),
        ],
    )
    def test_overlay_network_sanitization(self, url, expected):
        assert normalize_relay_url(url) == expected

    def test_url_exceeding_max_length_rejected(self):
        long_path = "/" + "a" * 2048
        with pytest.raises(ValueError, match="exceeds maximum length"):
            normalize_relay_url(f"wss://relay.example.com{long_path}")

    def test_url_at_max_length_accepted(self):
        base = "wss://relay.example.com/"
        url = base + "a" * (_MAX_URL_LENGTH - len(base))
        result = normalize_relay_url(url)
        assert len(result) == _MAX_URL_LENGTH

    # --- IDN to Punycode ---

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("wss://café.com", "wss://xn--caf-dma.com"),
            ("wss://münchen.de", "wss://xn--mnchen-3ya.de"),
            ("wss://café.com:8080/inbox", "wss://xn--caf-dma.com:8080/inbox"),
        ],
    )
    def test_idn_to_punycode(self, url, expected):
        assert normalize_relay_url(url) == expected

    def test_idn_non_ascii_path_stripped(self):
        assert normalize_relay_url("wss://relay.com/café") == "wss://relay.com"

    def test_idn_without_scheme_rejected(self):
        with pytest.raises(ValueError):
            normalize_relay_url("café.com")

    def test_idn_invalid_label_rejected(self):
        with pytest.raises(ValueError, match="Invalid internationalized"):
            normalize_relay_url("wss://\udcff.com")

    # --- Trailing dot ---

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("wss://relay.damus.io.", "wss://relay.damus.io"),
            ("wss://relay.example.com.:8080/path", "wss://relay.example.com:8080/path"),
        ],
    )
    def test_trailing_dot_stripped(self, url, expected):
        assert normalize_relay_url(url) == expected

    # --- IP normalization ---

    def test_ipv6_compressed(self):
        result = normalize_relay_url("wss://[2606:4700:4700:0000:0000:0000:0000:1111]:8080")
        assert result == "wss://[2606:4700:4700::1111]:8080"

    # --- Dot segment resolution ---

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("wss://relay.com/a/../b", "wss://relay.com/b"),
            ("wss://relay.com/a/./b", "wss://relay.com/a/b"),
            ("wss://relay.com/a/b/../../c", "wss://relay.com/c"),
            ("wss://relay.com/../a", "wss://relay.com/a"),
        ],
    )
    def test_dot_segments_resolved(self, url, expected):
        assert normalize_relay_url(url) == expected

    # --- Port range ---

    @pytest.mark.parametrize("port", [0, 65536, 99999])
    def test_port_out_of_range_rejected(self, port):
        with pytest.raises(ValueError):
            normalize_relay_url(f"wss://relay.com:{port}")

    @pytest.mark.parametrize(
        ("port", "expected"),
        [
            (1, "wss://relay.com:1"),
            (8080, "wss://relay.com:8080"),
            (65535, "wss://relay.com:65535"),
        ],
    )
    def test_port_in_range_accepted(self, port, expected):
        assert normalize_relay_url(f"wss://relay.com:{port}") == expected

    # --- Overlay hostname edge cases ---

    def test_i2p_b32_accepted(self):
        b32 = "a" * 52
        url = f"ws://{b32}.b32.i2p"
        assert normalize_relay_url(url) == url

    def test_i2p_b32_wrong_length_rejected(self):
        with pytest.raises(ValueError):
            normalize_relay_url("ws://tooshort.b32.i2p")
