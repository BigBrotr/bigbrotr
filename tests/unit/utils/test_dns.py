"""
Unit tests for utils.dns module.

Tests:
- ResolvedHost dataclass
  - Default values
  - has_ip property
- resolve_host() async function
  - IPv4 resolution
  - IPv6 resolution
  - Resolution failures
"""

import socket
from unittest.mock import patch

import pytest

from bigbrotr.utils.dns import ResolvedHost, resolve_host


# =============================================================================
# ResolvedHost Dataclass Tests
# =============================================================================


class TestResolvedHostDefaults:
    """Tests for ResolvedHost default field values."""

    def test_default_ipv4(self) -> None:
        """Test default ipv4 is None."""
        host = ResolvedHost()
        assert host.ipv4 is None

    def test_default_ipv6(self) -> None:
        """Test default ipv6 is None."""
        host = ResolvedHost()
        assert host.ipv6 is None


class TestResolvedHostInitialization:
    """Tests for ResolvedHost initialization with explicit values."""

    def test_init_with_ipv4(self) -> None:
        """Test initialization with IPv4 address only."""
        host = ResolvedHost(ipv4="192.168.1.1")
        assert host.ipv4 == "192.168.1.1"
        assert host.ipv6 is None

    def test_init_with_ipv6(self) -> None:
        """Test initialization with IPv6 address only."""
        host = ResolvedHost(ipv6="2001:db8::1")
        assert host.ipv4 is None
        assert host.ipv6 == "2001:db8::1"

    def test_init_with_both(self) -> None:
        """Test initialization with both IPv4 and IPv6 addresses."""
        host = ResolvedHost(ipv4="192.168.1.1", ipv6="2001:db8::1")
        assert host.ipv4 == "192.168.1.1"
        assert host.ipv6 == "2001:db8::1"


class TestResolvedHostImmutable:
    """Tests that ResolvedHost is frozen (immutable)."""

    def test_cannot_modify_ipv4(self) -> None:
        """Test that ipv4 cannot be modified after creation."""
        host = ResolvedHost(ipv4="192.168.1.1")
        with pytest.raises(AttributeError):
            host.ipv4 = "10.0.0.1"  # type: ignore[misc]

    def test_cannot_modify_ipv6(self) -> None:
        """Test that ipv6 cannot be modified after creation."""
        host = ResolvedHost(ipv6="2001:db8::1")
        with pytest.raises(AttributeError):
            host.ipv6 = "::1"  # type: ignore[misc]


class TestResolvedHostHasIpProperty:
    """Tests for ResolvedHost.has_ip computed property."""

    def test_has_ip_with_ipv4_only(self) -> None:
        """Test has_ip is True with IPv4 only."""
        host = ResolvedHost(ipv4="192.168.1.1")
        assert host.has_ip is True

    def test_has_ip_with_ipv6_only(self) -> None:
        """Test has_ip is True with IPv6 only."""
        host = ResolvedHost(ipv6="2001:db8::1")
        assert host.has_ip is True

    def test_has_ip_with_both(self) -> None:
        """Test has_ip is True with both addresses."""
        host = ResolvedHost(ipv4="192.168.1.1", ipv6="2001:db8::1")
        assert host.has_ip is True

    def test_has_ip_with_neither(self) -> None:
        """Test has_ip is False with no addresses."""
        host = ResolvedHost()
        assert host.has_ip is False


class TestResolvedHostSlots:
    """Tests that ResolvedHost uses __slots__ for memory efficiency."""

    def test_has_slots(self) -> None:
        """Test that __slots__ is defined on the dataclass."""
        assert hasattr(ResolvedHost, "__slots__")


# =============================================================================
# resolve_host() Tests - IPv4 Resolution
# =============================================================================


class TestResolveHostIpv4:
    """Tests for resolve_host() IPv4 address resolution."""

    async def test_resolves_ipv4(self) -> None:
        """Test successful IPv4 address resolution from hostname."""
        with patch("socket.gethostbyname", return_value="93.184.216.34"):
            result = await resolve_host("example.com")

        assert result.ipv4 == "93.184.216.34"

    async def test_ipv4_resolution_failure(self) -> None:
        """Test IPv4 resolution failure returns None for ipv4."""
        with (
            patch("socket.gethostbyname", side_effect=socket.gaierror("DNS lookup failed")),
            patch("socket.getaddrinfo", return_value=[]),
        ):
            result = await resolve_host("invalid.example.com")

        assert result.ipv4 is None


# =============================================================================
# resolve_host() Tests - IPv6 Resolution
# =============================================================================


class TestResolveHostIpv6:
    """Tests for resolve_host() IPv6 address resolution."""

    async def test_resolves_ipv6(self) -> None:
        """Test successful IPv6 address resolution from hostname."""
        mock_ipv6_result = [
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                6,
                "",
                ("2606:2800:220:1:248:1893:25c8:1946", 0, 0, 0),
            )
        ]

        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("socket.getaddrinfo", return_value=mock_ipv6_result),
        ):
            result = await resolve_host("example.com")

        assert result.ipv6 == "2606:2800:220:1:248:1893:25c8:1946"

    async def test_ipv6_resolution_failure(self) -> None:
        """Test IPv6 resolution failure returns None for ipv6."""
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("socket.getaddrinfo", side_effect=socket.gaierror("IPv6 lookup failed")),
        ):
            result = await resolve_host("example.com")

        assert result.ipv4 == "93.184.216.34"
        assert result.ipv6 is None

    async def test_ipv6_empty_result(self) -> None:
        """Test empty IPv6 result returns None for ipv6."""
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("socket.getaddrinfo", return_value=[]),
        ):
            result = await resolve_host("example.com")

        assert result.ipv4 == "93.184.216.34"
        assert result.ipv6 is None


# =============================================================================
# resolve_host() Tests - Both IPv4 and IPv6
# =============================================================================


class TestResolveHostBoth:
    """Tests for resolve_host() resolving both IPv4 and IPv6."""

    async def test_resolves_both(self) -> None:
        """Test resolving both IPv4 and IPv6 addresses."""
        mock_ipv6_result = [
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                6,
                "",
                ("2606:2800:220:1:248:1893:25c8:1946", 0, 0, 0),
            )
        ]

        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("socket.getaddrinfo", return_value=mock_ipv6_result),
        ):
            result = await resolve_host("example.com")

        assert result.ipv4 == "93.184.216.34"
        assert result.ipv6 == "2606:2800:220:1:248:1893:25c8:1946"
        assert result.has_ip is True


# =============================================================================
# resolve_host() Tests - Total Failure
# =============================================================================


class TestResolveHostFailure:
    """Tests for resolve_host() when all resolution fails."""

    async def test_total_resolution_failure(self) -> None:
        """Test both IPv4 and IPv6 resolution fail."""
        with (
            patch("socket.gethostbyname", side_effect=socket.gaierror("DNS lookup failed")),
            patch("socket.getaddrinfo", side_effect=socket.gaierror("IPv6 lookup failed")),
        ):
            result = await resolve_host("nonexistent.example.com")

        assert result.ipv4 is None
        assert result.ipv6 is None
        assert result.has_ip is False

    async def test_unicode_error_handled(self) -> None:
        """UnicodeError from invalid hostname encoding is caught and returns None."""
        with (
            patch("socket.gethostbyname", side_effect=UnicodeError("bad encoding")),
            patch("socket.getaddrinfo", side_effect=UnicodeError("bad encoding")),
        ):
            result = await resolve_host("example.com")

        assert result.ipv4 is None
        assert result.ipv6 is None

    async def test_unexpected_exception_propagates(self) -> None:
        """Non-OSError/UnicodeError exceptions propagate to the caller."""
        with (
            patch("socket.gethostbyname", side_effect=RuntimeError("unexpected")),
            pytest.raises(RuntimeError, match="unexpected"),
        ):
            await resolve_host("example.com")


# =============================================================================
# resolve_host() Tests - Edge Cases
# =============================================================================


class TestResolveHostEdgeCases:
    """Tests for resolve_host() edge cases and special inputs."""

    async def test_localhost(self) -> None:
        """Test resolving localhost addresses."""
        with (
            patch("socket.gethostbyname", return_value="127.0.0.1"),
            patch(
                "socket.getaddrinfo",
                return_value=[(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 0, 0, 0))],
            ),
        ):
            result = await resolve_host("localhost")

        assert result.ipv4 == "127.0.0.1"
        assert result.ipv6 == "::1"

    async def test_ip_address_as_input(self) -> None:
        """Test passing an IP address as hostname."""
        with (
            patch("socket.gethostbyname", return_value="192.168.1.1"),
            patch("socket.getaddrinfo", return_value=[]),
        ):
            result = await resolve_host("192.168.1.1")

        assert result.ipv4 == "192.168.1.1"

    async def test_subdomain(self) -> None:
        """Test resolving a subdomain hostname."""
        with (
            patch("socket.gethostbyname", return_value="10.0.0.1"),
            patch("socket.getaddrinfo", return_value=[]),
        ):
            result = await resolve_host("api.example.com")

        assert result.ipv4 == "10.0.0.1"


# =============================================================================
# resolve_host() Tests - Independence
# =============================================================================


class TestResolveHostIndependence:
    """Tests that IPv4 and IPv6 resolution are independent of each other."""

    async def test_ipv4_fails_ipv6_succeeds(self) -> None:
        """Test IPv4 failure does not affect IPv6 resolution."""
        mock_ipv6_result = [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 0, 0, 0))]

        with (
            patch("socket.gethostbyname", side_effect=socket.gaierror("No IPv4")),
            patch("socket.getaddrinfo", return_value=mock_ipv6_result),
        ):
            result = await resolve_host("ipv6only.example.com")

        assert result.ipv4 is None
        assert result.ipv6 == "2001:db8::1"
        assert result.has_ip is True

    async def test_ipv4_succeeds_ipv6_fails(self) -> None:
        """Test IPv6 failure does not affect IPv4 resolution."""
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("socket.getaddrinfo", side_effect=socket.gaierror("No IPv6")),
        ):
            result = await resolve_host("ipv4only.example.com")

        assert result.ipv4 == "93.184.216.34"
        assert result.ipv6 is None
        assert result.has_ip is True


# =============================================================================
# resolve_host() Tests - Async Behavior
# =============================================================================


class TestResolveHostAsync:
    """Tests for resolve_host() async behavior and return type."""

    async def test_returns_resolved_host(self) -> None:
        """Test that the return type is ResolvedHost."""
        with (
            patch("socket.gethostbyname", return_value="93.184.216.34"),
            patch("socket.getaddrinfo", return_value=[]),
        ):
            result = await resolve_host("example.com")

        assert isinstance(result, ResolvedHost)

    async def test_can_resolve_multiple_hosts(self) -> None:
        """Test resolving multiple hosts in sequence."""
        with (
            patch("socket.gethostbyname", side_effect=["1.1.1.1", "8.8.8.8"]),
            patch("socket.getaddrinfo", return_value=[]),
        ):
            result1 = await resolve_host("cloudflare.com")
            result2 = await resolve_host("google.com")

        assert result1.ipv4 == "1.1.1.1"
        assert result2.ipv4 == "8.8.8.8"
