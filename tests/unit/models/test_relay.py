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

from models import Relay


class TestParsing:
    """URL parsing and normalization."""

    def test_wss_clearnet(self):
        r = Relay("wss://relay.example.com")
        assert r.url == "wss://relay.example.com"
        assert r.scheme == "wss"
        assert r.host == "relay.example.com"
        assert r.network == "clearnet"
        assert r.port is None
        assert r.path is None

    def test_ws_clearnet(self):
        r = Relay("ws://relay.example.com")
        assert r.scheme == "ws"

    def test_explicit_port(self):
        r = Relay("wss://relay.example.com:8080")
        assert r.url == "wss://relay.example.com:8080"
        assert r.port == 8080

    def test_default_port_443_omitted(self):
        r = Relay("wss://relay.example.com:443")
        assert r.url == "wss://relay.example.com"
        assert r.port == 443

    def test_default_port_80_omitted(self):
        r = Relay("ws://relay.example.com:80")
        assert r.url == "ws://relay.example.com"
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
        assert r.network == "clearnet"

    def test_ipv6(self):
        r = Relay("wss://[2001:4860:4860::8888]")
        assert r.network == "clearnet"


class TestNetworkDetection:
    """Network type detection."""

    def test_tor(self):
        assert Relay("wss://abc123.onion").network == "tor"

    def test_i2p(self):
        assert Relay("wss://relay.i2p").network == "i2p"

    def test_loki(self):
        assert Relay("wss://relay.loki").network == "loki"

    def test_case_insensitive(self):
        assert Relay._detect_network("ABC.ONION") == "tor"
        assert Relay._detect_network("RELAY.I2P") == "i2p"

    def test_empty_host(self):
        assert Relay._detect_network("") == "unknown"


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
        with pytest.raises(AttributeError):
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
        assert params == ("relay.example.com", "clearnet", 1234567890)

    def test_tor(self):
        r = Relay("wss://abc123.onion", discovered_at=1234567890)
        assert r.to_db_params()[1] == "tor"

    def test_with_port_and_path(self):
        r = Relay("wss://relay.example.com:8080/nostr", discovered_at=1234567890)
        assert r.to_db_params()[0] == "relay.example.com:8080/nostr"


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
