"""
Unit tests for models.relay module.

Tests:
- URL parsing and normalization (wss/ws, with/without ports)
- Network detection (clearnet, tor, i2p, loki)
- Host, port, and scheme extraction
- to_db_params() serialization
- Immutability and hash/equality
"""

from time import time

import pytest

from models import NetworkType, Relay


class TestParsing:
    """URL parsing and normalization."""

    def test_wss_clearnet(self):
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

    def test_explicit_port(self):
        r = Relay("wss://relay.example.com:8080")
        assert r.url == "wss://relay.example.com:8080"
        assert r.port == 8080

    def test_default_port_443_omitted(self):
        r = Relay("wss://relay.example.com:443")
        assert r.url == "wss://relay.example.com"
        assert r.port == 443

    def test_default_port_80_omitted(self):
        """ws:// with port 80 gets upgraded to wss:// (clearnet), port omitted."""
        r = Relay("ws://relay.example.com:80")
        assert r.url == "wss://relay.example.com"
        assert r.port == 80

    def test_path_preserved(self):
        r = Relay("wss://relay.example.com/nostr")
        assert r.path == "/nostr"

    def test_trailing_slash_removed(self):
        r = Relay("wss://relay.example.com/")
        assert r.path is None

    def test_double_slashes_normalized(self):
        r = Relay("wss://relay.example.com//nostr//")
        assert r.path == "/nostr"

    def test_whitespace_stripped(self):
        r = Relay("  wss://relay.example.com  ")
        assert r.url == "wss://relay.example.com"

    def test_ipv4(self):
        r = Relay("wss://8.8.8.8")
        assert r.network == NetworkType.CLEARNET

    def test_ipv6(self):
        r = Relay("wss://[2001:4860:4860::8888]")
        assert r.network == NetworkType.CLEARNET


class TestNetworkTypeEnum:
    """NetworkType StrEnum."""

    def test_valid_types(self):
        valid = {member.value for member in NetworkType}
        assert valid == {"clearnet", "tor", "i2p", "loki", "local", "unknown"}

    def test_str_compatibility(self):
        assert NetworkType.CLEARNET == "clearnet"
        assert str(NetworkType.TOR) == "tor"
        assert NetworkType.LOCAL == "local"
        assert NetworkType.UNKNOWN == "unknown"


class TestNetworkDetection:
    """Network type detection."""

    def test_tor(self):
        r = Relay("wss://abc123.onion")
        assert r.network == NetworkType.TOR
        assert r.scheme == "ws"  # overlay networks use ws://
        assert r.url == "ws://abc123.onion"

    def test_i2p(self):
        r = Relay("wss://relay.i2p")
        assert r.network == NetworkType.I2P
        assert r.scheme == "ws"  # overlay networks use ws://
        assert r.url == "ws://relay.i2p"

    def test_loki(self):
        r = Relay("wss://relay.loki")
        assert r.network == NetworkType.LOKI
        assert r.scheme == "ws"  # overlay networks use ws://
        assert r.url == "ws://relay.loki"

    def test_clearnet(self):
        r = Relay("ws://relay.example.com")
        assert r.network == NetworkType.CLEARNET
        assert r.scheme == "wss"  # clearnet uses wss://
        assert r.url == "wss://relay.example.com"

    def test_case_insensitive(self):
        assert Relay._detect_network("ABC.ONION") == NetworkType.TOR
        assert Relay._detect_network("RELAY.I2P") == NetworkType.I2P

    def test_local_detection(self):
        assert Relay._detect_network("localhost") == NetworkType.LOCAL
        assert Relay._detect_network("127.0.0.1") == NetworkType.LOCAL
        assert Relay._detect_network("192.168.1.1") == NetworkType.LOCAL

    def test_unknown_detection(self):
        assert Relay._detect_network("") == NetworkType.UNKNOWN
        assert Relay._detect_network("invalid-host-") == NetworkType.UNKNOWN


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
            "wss://172.16.0.1",
            "wss://192.168.1.1",
            "wss://169.254.0.1",
            "wss://[::1]",
        ],
    )
    def test_local_addresses(self, url):
        with pytest.raises(ValueError, match="Local addresses"):
            Relay(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://relay.example.com",
            "https://relay.example.com",
        ],
    )
    def test_invalid_scheme(self, url):
        with pytest.raises(ValueError, match="Invalid scheme"):
            Relay(url)

    @pytest.mark.parametrize(
        "url",
        [
            "relay.example.com",
            "",
        ],
    )
    def test_missing_scheme(self, url):
        with pytest.raises(ValueError):
            Relay(url)

    def test_invalid_host(self):
        with pytest.raises(ValueError, match="Invalid host"):
            Relay("wss://invalid_host")


class TestImmutability:
    """Frozen dataclass behavior."""

    def test_attribute_mutation_blocked(self):
        r = Relay("wss://relay.example.com")
        with pytest.raises(AttributeError):
            r.network = "tor"

    def test_new_attribute_blocked(self):
        r = Relay("wss://relay.example.com")
        with pytest.raises((AttributeError, TypeError)):
            r.new_attr = "value"


class TestTimestamp:
    """Timestamp handling."""

    def test_defaults_to_now(self):
        before = int(time())
        r = Relay("wss://relay.example.com")
        after = int(time())
        assert before <= r.discovered_at <= after

    def test_explicit(self):
        r = Relay("wss://relay.example.com", discovered_at=1234567890)
        assert r.discovered_at == 1234567890


class TestDbParams:
    """Database parameter generation."""

    def test_structure(self):
        r = Relay("wss://relay.example.com", discovered_at=1234567890)
        params = r.to_db_params()
        assert params == ("wss://relay.example.com", "clearnet", 1234567890)

    def test_tor(self):
        r = Relay("wss://abc123.onion", discovered_at=1234567890)
        params = r.to_db_params()
        assert params[0] == "ws://abc123.onion"  # tor uses ws://
        assert params[1] == "tor"

    def test_with_port_and_path(self):
        r = Relay("wss://relay.example.com:8080/nostr", discovered_at=1234567890)
        assert r.to_db_params()[0] == "wss://relay.example.com:8080/nostr"


class TestEquality:
    """Equality and hashing."""

    def test_equal(self):
        r1 = Relay("wss://relay.example.com", discovered_at=1234567890)
        r2 = Relay("wss://relay.example.com", discovered_at=1234567890)
        assert r1 == r2

    def test_different(self):
        r1 = Relay("wss://relay1.example.com", discovered_at=1234567890)
        r2 = Relay("wss://relay2.example.com", discovered_at=1234567890)
        assert r1 != r2

    def test_hashable(self):
        r1 = Relay("wss://relay.example.com", discovered_at=1234567890)
        r2 = Relay("wss://relay.example.com", discovered_at=1234567890)
        assert len({r1, r2}) == 1


class TestFromDbParams:
    """Reconstruction from database parameters."""

    def test_simple_relay(self):
        r = Relay.from_db_params("wss://relay.example.com", "clearnet", 1234567890)
        assert r.url == "wss://relay.example.com"
        assert r.network == NetworkType.CLEARNET
        assert r.discovered_at == 1234567890
        assert r.host == "relay.example.com"
        assert r.port is None
        assert r.path is None
        assert r.scheme == "wss"

    def test_with_port(self):
        r = Relay.from_db_params("wss://relay.example.com:8080", "clearnet", 1234567890)
        assert r.host == "relay.example.com"
        assert r.port == 8080
        assert r.path is None

    def test_with_path(self):
        r = Relay.from_db_params("wss://relay.example.com/nostr", "clearnet", 1234567890)
        assert r.host == "relay.example.com"
        assert r.port is None
        assert r.path == "/nostr"

    def test_with_port_and_path(self):
        r = Relay.from_db_params("wss://relay.example.com:8080/nostr", "clearnet", 1234567890)
        assert r.host == "relay.example.com"
        assert r.port == 8080
        assert r.path == "/nostr"

    def test_ipv6(self):
        r = Relay.from_db_params("wss://[2606:4700::1]:8080", "clearnet", 1234567890)
        assert r.host == "2606:4700::1"  # host without brackets
        assert r.port == 8080

    def test_tor_network(self):
        r = Relay.from_db_params("ws://abc123.onion", "tor", 1234567890)
        assert r.network == NetworkType.TOR
        assert r.scheme == "ws"

    def test_roundtrip(self):
        """to_db_params -> from_db_params should preserve data."""
        original = Relay("wss://relay.example.com:8080/nostr", discovered_at=1234567890)
        params = original.to_db_params()
        reconstructed = Relay.from_db_params(*params)
        assert reconstructed.url == original.url
        assert reconstructed.network == original.network
        assert reconstructed.discovered_at == original.discovered_at
        assert reconstructed.host == original.host
        assert reconstructed.port == original.port
        assert reconstructed.path == original.path
