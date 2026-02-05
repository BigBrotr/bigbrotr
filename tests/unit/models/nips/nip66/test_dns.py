"""
Unit tests for models.nips.nip66.dns module.

Tests:
- Nip66DnsMetadata._dns() - synchronous DNS resolution
- Nip66DnsMetadata.dns() - async DNS resolution with clearnet validation
- DNS record type extraction (A, AAAA, CNAME, NS, PTR)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from models import Relay
from models.nips.nip66.dns import Nip66DnsMetadata


class TestNip66DnsMetadataDnsSync:
    """Test Nip66DnsMetadata._dns() synchronous method."""

    def test_resolves_a_records(self) -> None:
        """Resolve A records (IPv4)."""
        mock_response = MagicMock()
        mock_rdata = MagicMock()
        mock_rdata.address = "8.8.8.8"
        mock_response.__iter__ = lambda _: iter([mock_rdata])
        mock_response.rrset = MagicMock()
        mock_response.rrset.ttl = 300

        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = mock_response

        with patch("dns.resolver.Resolver", return_value=mock_resolver):
            result = Nip66DnsMetadata._dns("example.com", 5.0)

        assert result.get("dns_ips") == ["8.8.8.8"]
        assert result.get("dns_ttl") == 300

    def test_resolves_multiple_a_records(self) -> None:
        """Resolve multiple A records."""
        mock_rdata1 = MagicMock()
        mock_rdata1.address = "8.8.8.8"
        mock_rdata2 = MagicMock()
        mock_rdata2.address = "8.8.4.4"

        mock_response = MagicMock()
        mock_response.__iter__ = lambda _: iter([mock_rdata1, mock_rdata2])
        mock_response.rrset = MagicMock()
        mock_response.rrset.ttl = 300

        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = mock_response

        with patch("dns.resolver.Resolver", return_value=mock_resolver):
            result = Nip66DnsMetadata._dns("example.com", 5.0)

        assert result.get("dns_ips") == ["8.8.8.8", "8.8.4.4"]

    def test_resolves_aaaa_records(self) -> None:
        """Resolve AAAA records (IPv6)."""
        mock_a_response = MagicMock()
        mock_a_rdata = MagicMock()
        mock_a_rdata.address = "8.8.8.8"
        mock_a_response.__iter__ = lambda _: iter([mock_a_rdata])
        mock_a_response.rrset = MagicMock()
        mock_a_response.rrset.ttl = 300

        mock_aaaa_response = MagicMock()
        mock_aaaa_rdata = MagicMock()
        mock_aaaa_rdata.address = "2001:4860:4860::8888"
        mock_aaaa_response.__iter__ = lambda _: iter([mock_aaaa_rdata])

        mock_resolver = MagicMock()

        def resolve_side_effect(host: str, record_type: str) -> MagicMock:
            if record_type == "A":
                return mock_a_response
            if record_type == "AAAA":
                return mock_aaaa_response
            raise Exception(f"Unknown record type: {record_type}")

        mock_resolver.resolve.side_effect = resolve_side_effect

        with patch("dns.resolver.Resolver", return_value=mock_resolver):
            result = Nip66DnsMetadata._dns("example.com", 5.0)

        assert result.get("dns_ips_v6") == ["2001:4860:4860::8888"]

    def test_resolves_cname_record(self) -> None:
        """Resolve CNAME record."""
        mock_a_response = MagicMock()
        mock_a_rdata = MagicMock()
        mock_a_rdata.address = "8.8.8.8"
        mock_a_response.__iter__ = lambda _: iter([mock_a_rdata])
        mock_a_response.rrset = MagicMock()
        mock_a_response.rrset.ttl = 300

        mock_cname_response = MagicMock()
        mock_cname_rdata = MagicMock()
        mock_cname_rdata.target = "dns.google."
        mock_cname_response.__iter__ = lambda _: iter([mock_cname_rdata])

        mock_resolver = MagicMock()

        def resolve_side_effect(host: str, record_type: str) -> MagicMock:
            if record_type == "A":
                return mock_a_response
            if record_type == "CNAME":
                return mock_cname_response
            raise Exception(f"No {record_type} record")

        mock_resolver.resolve.side_effect = resolve_side_effect

        with patch("dns.resolver.Resolver", return_value=mock_resolver):
            result = Nip66DnsMetadata._dns("example.com", 5.0)

        assert result.get("dns_cname") == "dns.google"  # Trailing dot stripped

    def test_resolves_ns_records(self) -> None:
        """Resolve NS records."""
        mock_a_response = MagicMock()
        mock_a_rdata = MagicMock()
        mock_a_rdata.address = "8.8.8.8"
        mock_a_response.__iter__ = lambda _: iter([mock_a_rdata])
        mock_a_response.rrset = MagicMock()
        mock_a_response.rrset.ttl = 300

        mock_ns_response = MagicMock()
        mock_ns1 = MagicMock()
        mock_ns1.target = "ns1.google.com."
        mock_ns2 = MagicMock()
        mock_ns2.target = "ns2.google.com."
        mock_ns_response.__iter__ = lambda _: iter([mock_ns1, mock_ns2])

        mock_resolver = MagicMock()

        def resolve_side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            _, record_type = args[0], args[1]
            if record_type == "A":
                return mock_a_response
            if record_type == "NS":
                return mock_ns_response
            raise Exception(f"No {record_type} record")

        mock_resolver.resolve.side_effect = resolve_side_effect

        # Mock tldextract
        mock_ext = MagicMock()
        mock_ext.domain = "example"
        mock_ext.suffix = "com"

        with (
            patch("dns.resolver.Resolver", return_value=mock_resolver),
            patch("tldextract.extract", return_value=mock_ext),
        ):
            result = Nip66DnsMetadata._dns("www.example.com", 5.0)

        assert result.get("dns_ns") == ["ns1.google.com", "ns2.google.com"]

    def test_resolves_ptr_record(self) -> None:
        """Resolve PTR record (reverse DNS)."""
        mock_a_response = MagicMock()
        mock_a_rdata = MagicMock()
        mock_a_rdata.address = "8.8.8.8"
        mock_a_response.__iter__ = lambda _: iter([mock_a_rdata])
        mock_a_response.rrset = MagicMock()
        mock_a_response.rrset.ttl = 300

        mock_ptr_response = MagicMock()
        mock_ptr_rdata = MagicMock()
        mock_ptr_rdata.target = "dns.google."
        mock_ptr_response.__iter__ = lambda _: iter([mock_ptr_rdata])

        mock_resolver = MagicMock()

        call_count = 0

        def resolve_side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # A record
                return mock_a_response
            if args[1] == "PTR":
                return mock_ptr_response
            raise Exception("No record")

        mock_resolver.resolve.side_effect = resolve_side_effect

        with (
            patch("dns.resolver.Resolver", return_value=mock_resolver),
            patch("dns.reversename.from_address", return_value="8.8.8.8.in-addr.arpa"),
        ):
            result = Nip66DnsMetadata._dns("example.com", 5.0)

        assert result.get("dns_reverse") == "dns.google"

    def test_empty_result_when_no_records(self) -> None:
        """Return empty dict when no DNS records found."""
        mock_resolver = MagicMock()
        mock_resolver.resolve.side_effect = Exception("NXDOMAIN")

        with patch("dns.resolver.Resolver", return_value=mock_resolver):
            result = Nip66DnsMetadata._dns("nonexistent.invalid", 5.0)

        assert result == {}

    def test_sets_timeout_and_lifetime(self) -> None:
        """Sets resolver timeout and lifetime."""
        mock_resolver = MagicMock()
        mock_resolver.resolve.side_effect = Exception("NXDOMAIN")

        with patch("dns.resolver.Resolver", return_value=mock_resolver) as mock_resolver_cls:
            Nip66DnsMetadata._dns("example.com", 7.5)

        resolver_instance = mock_resolver_cls.return_value
        assert resolver_instance.timeout == 7.5
        assert resolver_instance.lifetime == 7.5


class TestNip66DnsMetadataDnsAsync:
    """Test Nip66DnsMetadata.dns() async class method."""

    @pytest.mark.asyncio
    async def test_clearnet_returns_dns_metadata(self, relay: Relay) -> None:
        """Returns Nip66DnsMetadata for clearnet relay."""
        dns_result = {
            "dns_ips": ["8.8.8.8"],
            "dns_ttl": 300,
        }

        with patch.object(Nip66DnsMetadata, "_dns", return_value=dns_result):
            result = await Nip66DnsMetadata.dns(relay, 5.0)

        assert isinstance(result, Nip66DnsMetadata)
        assert result.data.dns_ips == ["8.8.8.8"]
        assert result.data.dns_ttl == 300
        assert result.logs.success is True

    @pytest.mark.asyncio
    async def test_tor_raises_value_error(self, tor_relay: Relay) -> None:
        """Raises ValueError for Tor relay (DNS not applicable)."""
        with pytest.raises(ValueError, match="DNS resolve requires clearnet"):
            await Nip66DnsMetadata.dns(tor_relay, 5.0)

    @pytest.mark.asyncio
    async def test_i2p_raises_value_error(self, i2p_relay: Relay) -> None:
        """Raises ValueError for I2P relay (DNS not applicable)."""
        with pytest.raises(ValueError, match="DNS resolve requires clearnet"):
            await Nip66DnsMetadata.dns(i2p_relay, 5.0)

    @pytest.mark.asyncio
    async def test_loki_raises_value_error(self, loki_relay: Relay) -> None:
        """Raises ValueError for Lokinet relay (DNS not applicable)."""
        with pytest.raises(ValueError, match="DNS resolve requires clearnet"):
            await Nip66DnsMetadata.dns(loki_relay, 5.0)

    @pytest.mark.asyncio
    async def test_no_records_returns_failure(self, relay: Relay) -> None:
        """No DNS records returns failure logs."""
        with patch.object(Nip66DnsMetadata, "_dns", return_value={}):
            result = await Nip66DnsMetadata.dns(relay, 5.0)

        assert isinstance(result, Nip66DnsMetadata)
        assert result.logs.success is False
        assert "no DNS records found" in result.logs.reason

    @pytest.mark.asyncio
    async def test_exception_returns_failure(self, relay: Relay) -> None:
        """Exception during DNS resolution returns failure logs."""
        with patch.object(Nip66DnsMetadata, "_dns", side_effect=Exception("DNS error")):
            result = await Nip66DnsMetadata.dns(relay, 5.0)

        assert isinstance(result, Nip66DnsMetadata)
        assert result.logs.success is False
        assert "DNS error" in result.logs.reason

    @pytest.mark.asyncio
    async def test_uses_default_timeout(self, relay: Relay) -> None:
        """Uses default timeout when None provided."""
        dns_result = {"dns_ips": ["8.8.8.8"]}

        with patch.object(Nip66DnsMetadata, "_dns", return_value=dns_result) as mock_dns:
            await Nip66DnsMetadata.dns(relay, None)

        mock_dns.assert_called_once()
        # Default timeout should be used (from base module)
        call_args = mock_dns.call_args
        assert call_args[0][1] > 0  # Second positional arg is timeout

    @pytest.mark.asyncio
    async def test_uses_relay_host(self, relay: Relay) -> None:
        """Uses relay's host for DNS resolution."""
        dns_result = {"dns_ips": ["8.8.8.8"]}

        with patch.object(Nip66DnsMetadata, "_dns", return_value=dns_result) as mock_dns:
            await Nip66DnsMetadata.dns(relay, 5.0)

        mock_dns.assert_called_once()
        call_args = mock_dns.call_args
        assert call_args[0][0] == relay.host  # First positional arg is host

    @pytest.mark.asyncio
    async def test_successful_resolution_logs_success(self, relay: Relay) -> None:
        """Successful DNS resolution sets logs.success=True."""
        dns_result = {
            "dns_ips": ["8.8.8.8", "8.8.4.4"],
            "dns_ips_v6": ["2001:4860:4860::8888"],
            "dns_cname": "dns.google",
            "dns_ttl": 300,
        }

        with patch.object(Nip66DnsMetadata, "_dns", return_value=dns_result):
            result = await Nip66DnsMetadata.dns(relay, 5.0)

        assert result.logs.success is True
        assert result.logs.reason is None
        assert result.data.dns_ips == ["8.8.8.8", "8.8.4.4"]
        assert result.data.dns_ips_v6 == ["2001:4860:4860::8888"]
        assert result.data.dns_cname == "dns.google"
