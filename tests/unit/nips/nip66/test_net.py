"""
Unit tests for models.nips.nip66.net module.

Tests:
- Nip66NetMetadata._net() - synchronous ASN lookup
- Nip66NetMetadata.execute() - async network lookup with clearnet validation
- IPv4 and IPv6 ASN resolution
- Dual-stack handling
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bigbrotr.models import Relay
from bigbrotr.nips.nip66.net import Nip66NetMetadata


class TestNip66NetMetadataNetSync:
    """Test Nip66NetMetadata._net() synchronous method."""

    def test_ipv4_only_lookup(self, mock_asn_response: MagicMock) -> None:
        """Successful lookup with IPv4 only."""
        mock_asn_reader = MagicMock()
        mock_asn_reader.asn.return_value = mock_asn_response

        result = Nip66NetMetadata._net("8.8.8.8", None, mock_asn_reader)

        assert result["net_ip"] == "8.8.8.8"
        assert result.get("net_ipv6") is None
        assert result["net_asn"] == 15169
        assert result["net_asn_org"] == "GOOGLE"
        assert result["net_network"] == "8.8.8.0/24"
        assert result.get("net_network_v6") is None

    def test_ipv6_only_lookup(self) -> None:
        """Successful lookup with IPv6 only."""
        mock_asn_response = MagicMock()
        mock_asn_response.autonomous_system_number = 15169
        mock_asn_response.autonomous_system_organization = "GOOGLE"
        mock_asn_response.network = "2001:4860::/32"

        mock_asn_reader = MagicMock()
        mock_asn_reader.asn.return_value = mock_asn_response

        result = Nip66NetMetadata._net(None, "2001:4860:4860::8888", mock_asn_reader)

        assert result.get("net_ip") is None
        assert result["net_ipv6"] == "2001:4860:4860::8888"
        assert result["net_asn"] == 15169
        assert result["net_asn_org"] == "GOOGLE"
        assert result.get("net_network") is None
        assert result["net_network_v6"] == "2001:4860::/32"

    def test_dual_stack_lookup(self) -> None:
        """Successful lookup with both IPv4 and IPv6."""
        mock_asn_response_v4 = MagicMock()
        mock_asn_response_v4.autonomous_system_number = 15169
        mock_asn_response_v4.autonomous_system_organization = "GOOGLE"
        mock_asn_response_v4.network = "8.8.8.0/24"

        mock_asn_response_v6 = MagicMock()
        mock_asn_response_v6.autonomous_system_number = 15169
        mock_asn_response_v6.autonomous_system_organization = "GOOGLE"
        mock_asn_response_v6.network = "2001:4860::/32"

        mock_asn_reader = MagicMock()
        mock_asn_reader.asn.side_effect = [mock_asn_response_v4, mock_asn_response_v6]

        result = Nip66NetMetadata._net("8.8.8.8", "2001:4860:4860::8888", mock_asn_reader)

        assert result["net_ip"] == "8.8.8.8"
        assert result["net_ipv6"] == "2001:4860:4860::8888"
        assert result["net_asn"] == 15169
        assert result["net_asn_org"] == "GOOGLE"
        assert result["net_network"] == "8.8.8.0/24"
        assert result["net_network_v6"] == "2001:4860::/32"

    def test_ipv4_lookup_exception_still_returns_ip(self) -> None:
        """IPv4 lookup exception still includes the IP address."""
        mock_asn_reader = MagicMock()
        mock_asn_reader.asn.side_effect = Exception("ASN lookup failed")

        result = Nip66NetMetadata._net("8.8.8.8", None, mock_asn_reader)

        assert result["net_ip"] == "8.8.8.8"
        assert "net_asn" not in result

    def test_ipv6_lookup_exception_still_returns_ip(self) -> None:
        """IPv6 lookup exception still includes the IP address."""
        mock_asn_reader = MagicMock()
        mock_asn_reader.asn.side_effect = Exception("ASN lookup failed")

        result = Nip66NetMetadata._net(None, "2001:4860:4860::8888", mock_asn_reader)

        assert result["net_ipv6"] == "2001:4860:4860::8888"
        assert "net_asn" not in result

    def test_dual_stack_ipv4_fails_ipv6_succeeds(self) -> None:
        """IPv4 lookup fails but IPv6 succeeds."""
        mock_asn_response_v6 = MagicMock()
        mock_asn_response_v6.autonomous_system_number = 15169
        mock_asn_response_v6.autonomous_system_organization = "GOOGLE"
        mock_asn_response_v6.network = "2001:4860::/32"

        mock_asn_reader = MagicMock()

        def asn_side_effect(ip: str) -> MagicMock:
            if ip == "8.8.8.8":
                raise Exception("IPv4 lookup failed")
            return mock_asn_response_v6

        mock_asn_reader.asn.side_effect = asn_side_effect

        result = Nip66NetMetadata._net("8.8.8.8", "2001:4860:4860::8888", mock_asn_reader)

        assert result["net_ip"] == "8.8.8.8"
        assert result["net_ipv6"] == "2001:4860:4860::8888"
        assert result["net_asn"] == 15169  # From IPv6
        assert result["net_asn_org"] == "GOOGLE"
        assert "net_network" not in result  # IPv4 failed
        assert result["net_network_v6"] == "2001:4860::/32"

    def test_no_ips_returns_empty_dict(self) -> None:
        """No IPs provided returns empty dict."""
        mock_asn_reader = MagicMock()

        result = Nip66NetMetadata._net(None, None, mock_asn_reader)

        assert result == {}

    def test_asn_from_ipv4_not_overwritten_by_ipv6(self) -> None:
        """ASN from IPv4 is not overwritten by IPv6 lookup."""
        mock_asn_response_v4 = MagicMock()
        mock_asn_response_v4.autonomous_system_number = 15169
        mock_asn_response_v4.autonomous_system_organization = "GOOGLE"
        mock_asn_response_v4.network = "8.8.8.0/24"

        mock_asn_response_v6 = MagicMock()
        mock_asn_response_v6.autonomous_system_number = 99999
        mock_asn_response_v6.autonomous_system_organization = "OTHER"
        mock_asn_response_v6.network = "2001:4860::/32"

        mock_asn_reader = MagicMock()
        mock_asn_reader.asn.side_effect = [mock_asn_response_v4, mock_asn_response_v6]

        result = Nip66NetMetadata._net("8.8.8.8", "2001:4860:4860::8888", mock_asn_reader)

        # IPv4 lookup runs first, so its ASN takes precedence
        assert result["net_asn"] == 15169
        assert result["net_asn_org"] == "GOOGLE"

    def test_network_string_conversion(self) -> None:
        """Network is converted to string from ipaddress object."""
        mock_asn_response = MagicMock()
        mock_asn_response.autonomous_system_number = 15169
        mock_asn_response.autonomous_system_organization = "GOOGLE"
        # Simulate ipaddress.IPv4Network object
        mock_network = MagicMock()
        mock_network.__str__ = lambda _: "8.8.8.0/24"
        mock_asn_response.network = mock_network

        mock_asn_reader = MagicMock()
        mock_asn_reader.asn.return_value = mock_asn_response

        result = Nip66NetMetadata._net("8.8.8.8", None, mock_asn_reader)

        assert result["net_network"] == "8.8.8.0/24"


class TestNip66NetMetadataNetAsync:
    """Test Nip66NetMetadata.execute() async class method."""

    @pytest.mark.asyncio
    async def test_clearnet_returns_net_metadata(
        self,
        relay: Relay,
        mock_asn_reader: MagicMock,
    ) -> None:
        """Returns Nip66NetMetadata for clearnet relay."""
        net_result = {
            "net_ip": "8.8.8.8",
            "net_asn": 15169,
            "net_asn_org": "GOOGLE",
            "net_network": "8.8.8.0/24",
        }

        mock_resolved = MagicMock()
        mock_resolved.ipv4 = "8.8.8.8"
        mock_resolved.ipv6 = None
        mock_resolved.has_ip = True

        with (
            patch(
                "bigbrotr.nips.nip66.net.resolve_host",
                new_callable=AsyncMock,
                return_value=mock_resolved,
            ),
            patch.object(Nip66NetMetadata, "_net", return_value=net_result),
        ):
            result = await Nip66NetMetadata.execute(relay, mock_asn_reader)

        assert isinstance(result, Nip66NetMetadata)
        assert result.data.net_ip == "8.8.8.8"
        assert result.data.net_asn == 15169
        assert result.logs.success is True

    @pytest.mark.asyncio
    async def test_tor_raises_value_error(
        self,
        tor_relay: Relay,
        mock_asn_reader: MagicMock,
    ) -> None:
        """Raises ValueError for Tor relay (net not applicable)."""
        with pytest.raises(ValueError, match="net lookup requires clearnet"):
            await Nip66NetMetadata.execute(tor_relay, mock_asn_reader)

    @pytest.mark.asyncio
    async def test_i2p_raises_value_error(
        self,
        i2p_relay: Relay,
        mock_asn_reader: MagicMock,
    ) -> None:
        """Raises ValueError for I2P relay (net not applicable)."""
        with pytest.raises(ValueError, match="net lookup requires clearnet"):
            await Nip66NetMetadata.execute(i2p_relay, mock_asn_reader)

    @pytest.mark.asyncio
    async def test_loki_raises_value_error(
        self,
        loki_relay: Relay,
        mock_asn_reader: MagicMock,
    ) -> None:
        """Raises ValueError for Lokinet relay (net not applicable)."""
        with pytest.raises(ValueError, match="net lookup requires clearnet"):
            await Nip66NetMetadata.execute(loki_relay, mock_asn_reader)

    @pytest.mark.asyncio
    async def test_no_ip_resolved_returns_failure(
        self,
        relay: Relay,
        mock_asn_reader: MagicMock,
    ) -> None:
        """Returns failure logs when hostname cannot be resolved to IP."""
        mock_resolved = MagicMock()
        mock_resolved.ipv4 = None
        mock_resolved.ipv6 = None
        mock_resolved.has_ip = False

        with patch(
            "bigbrotr.nips.nip66.net.resolve_host",
            new_callable=AsyncMock,
            return_value=mock_resolved,
        ):
            result = await Nip66NetMetadata.execute(relay, mock_asn_reader)

        assert isinstance(result, Nip66NetMetadata)
        assert result.logs.success is False
        assert "could not resolve hostname" in result.logs.reason

    @pytest.mark.asyncio
    async def test_no_asn_data_returns_failure(
        self,
        relay: Relay,
        mock_asn_reader: MagicMock,
    ) -> None:
        """Returns failure logs when no ASN data found."""
        mock_resolved = MagicMock()
        mock_resolved.ipv4 = "8.8.8.8"
        mock_resolved.ipv6 = None
        mock_resolved.has_ip = True

        with (
            patch(
                "bigbrotr.nips.nip66.net.resolve_host",
                new_callable=AsyncMock,
                return_value=mock_resolved,
            ),
            patch.object(Nip66NetMetadata, "_net", return_value={}),
        ):
            result = await Nip66NetMetadata.execute(relay, mock_asn_reader)

        assert isinstance(result, Nip66NetMetadata)
        assert result.logs.success is False
        assert "no ASN data found" in result.logs.reason

    @pytest.mark.asyncio
    async def test_dual_stack_passed_to_net(
        self,
        relay: Relay,
        mock_asn_reader: MagicMock,
    ) -> None:
        """Both IPv4 and IPv6 are passed to _net when available."""
        net_result = {
            "net_ip": "8.8.8.8",
            "net_ipv6": "2001:4860:4860::8888",
            "net_asn": 15169,
        }

        mock_resolved = MagicMock()
        mock_resolved.ipv4 = "8.8.8.8"
        mock_resolved.ipv6 = "2001:4860:4860::8888"
        mock_resolved.has_ip = True

        with (
            patch(
                "bigbrotr.nips.nip66.net.resolve_host",
                new_callable=AsyncMock,
                return_value=mock_resolved,
            ),
            patch.object(Nip66NetMetadata, "_net", return_value=net_result) as mock_net,
        ):
            await Nip66NetMetadata.execute(relay, mock_asn_reader)

        mock_net.assert_called_once_with("8.8.8.8", "2001:4860:4860::8888", mock_asn_reader)

    @pytest.mark.asyncio
    async def test_success_with_partial_data(
        self,
        relay: Relay,
        mock_asn_reader: MagicMock,
    ) -> None:
        """Success when only some ASN fields are available."""
        net_result = {
            "net_ip": "8.8.8.8",
            "net_asn": 15169,
            # No net_asn_org or net_network
        }

        mock_resolved = MagicMock()
        mock_resolved.ipv4 = "8.8.8.8"
        mock_resolved.ipv6 = None
        mock_resolved.has_ip = True

        with (
            patch(
                "bigbrotr.nips.nip66.net.resolve_host",
                new_callable=AsyncMock,
                return_value=mock_resolved,
            ),
            patch.object(Nip66NetMetadata, "_net", return_value=net_result),
        ):
            result = await Nip66NetMetadata.execute(relay, mock_asn_reader)

        assert result.logs.success is True
        assert result.data.net_asn == 15169
        assert result.data.net_asn_org is None
