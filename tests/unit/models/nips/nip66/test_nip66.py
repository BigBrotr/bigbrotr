"""
Unit tests for models.nips.nip66.nip66 module.

Tests:
- Nip66 construction and validation
- Nip66.to_relay_metadata_tuple() conversion
- Nip66.create() async factory method
- RelayNip66MetadataTuple named tuple
"""

from __future__ import annotations

from time import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models import Relay, RelayMetadata
from models.metadata import MetadataType
from models.nips.nip66 import (
    Nip66,
    Nip66DnsData,
    Nip66DnsLogs,
    Nip66DnsMetadata,
    Nip66GeoMetadata,
    Nip66HttpMetadata,
    Nip66NetMetadata,
    Nip66RttData,
    Nip66RttLogs,
    Nip66RttMetadata,
    Nip66SslMetadata,
    RelayNip66MetadataTuple,
)
from models.nips.nip66.nip66 import Nip66Dependencies, Nip66TestFlags


class TestNip66Construction:
    """Test Nip66 construction and validation."""

    def test_with_all_metadata(
        self,
        relay: Relay,
        complete_rtt_metadata: Nip66RttMetadata,
        complete_ssl_metadata: Nip66SslMetadata,
        complete_geo_metadata: Nip66GeoMetadata,
        complete_net_metadata: Nip66NetMetadata,
        complete_dns_metadata: Nip66DnsMetadata,
        complete_http_metadata: Nip66HttpMetadata,
    ) -> None:
        """Construct with all six metadata types."""
        nip66 = Nip66(
            relay=relay,
            rtt_metadata=complete_rtt_metadata,
            ssl_metadata=complete_ssl_metadata,
            geo_metadata=complete_geo_metadata,
            net_metadata=complete_net_metadata,
            dns_metadata=complete_dns_metadata,
            http_metadata=complete_http_metadata,
        )
        assert nip66.relay is relay
        assert nip66.rtt_metadata is not None
        assert nip66.ssl_metadata is not None
        assert nip66.geo_metadata is not None
        assert nip66.net_metadata is not None
        assert nip66.dns_metadata is not None
        assert nip66.http_metadata is not None

    def test_with_rtt_only(
        self,
        relay: Relay,
        complete_rtt_metadata: Nip66RttMetadata,
    ) -> None:
        """Construct with RTT metadata only, others are None."""
        nip66 = Nip66(relay=relay, rtt_metadata=complete_rtt_metadata)
        assert nip66.rtt_metadata.data.rtt_open == 100
        assert nip66.rtt_metadata.logs.open_success is True
        assert nip66.ssl_metadata is None
        assert nip66.geo_metadata is None
        assert nip66.net_metadata is None
        assert nip66.dns_metadata is None
        assert nip66.http_metadata is None

    def test_with_ssl_only(
        self,
        relay: Relay,
        complete_ssl_metadata: Nip66SslMetadata,
    ) -> None:
        """Construct with SSL metadata only."""
        nip66 = Nip66(relay=relay, ssl_metadata=complete_ssl_metadata)
        assert nip66.rtt_metadata is None
        assert nip66.ssl_metadata.data.ssl_valid is True
        assert nip66.geo_metadata is None

    def test_with_geo_only(
        self,
        relay: Relay,
        complete_geo_metadata: Nip66GeoMetadata,
    ) -> None:
        """Construct with geo metadata only."""
        nip66 = Nip66(relay=relay, geo_metadata=complete_geo_metadata)
        assert nip66.rtt_metadata is None
        assert nip66.ssl_metadata is None
        assert nip66.geo_metadata.data.geo_country == "US"

    def test_with_net_only(
        self,
        relay: Relay,
        complete_net_metadata: Nip66NetMetadata,
    ) -> None:
        """Construct with net metadata only."""
        nip66 = Nip66(relay=relay, net_metadata=complete_net_metadata)
        assert nip66.net_metadata.data.net_ip == "8.8.8.8"
        assert nip66.net_metadata.data.net_asn == 15169
        assert nip66.rtt_metadata is None

    def test_with_dns_only(
        self,
        relay: Relay,
        complete_dns_metadata: Nip66DnsMetadata,
    ) -> None:
        """Construct with DNS metadata only."""
        nip66 = Nip66(relay=relay, dns_metadata=complete_dns_metadata)
        assert nip66.dns_metadata.data.dns_ips == ["8.8.8.8", "8.8.4.4"]
        assert nip66.rtt_metadata is None

    def test_with_http_only(
        self,
        relay: Relay,
        complete_http_metadata: Nip66HttpMetadata,
    ) -> None:
        """Construct with HTTP metadata only."""
        nip66 = Nip66(relay=relay, http_metadata=complete_http_metadata)
        assert nip66.http_metadata.data.http_server == "nginx/1.24.0"
        assert nip66.rtt_metadata is None

    def test_generated_at_default(
        self,
        relay: Relay,
        complete_rtt_metadata: Nip66RttMetadata,
    ) -> None:
        """generated_at defaults to current time."""
        before = int(time())
        nip66 = Nip66(relay=relay, rtt_metadata=complete_rtt_metadata)
        after = int(time())
        assert before <= nip66.generated_at <= after

    def test_generated_at_explicit(
        self,
        relay: Relay,
        complete_rtt_metadata: Nip66RttMetadata,
    ) -> None:
        """Explicit generated_at is preserved."""
        nip66 = Nip66(relay=relay, rtt_metadata=complete_rtt_metadata, generated_at=1000)
        assert nip66.generated_at == 1000

    def test_empty_nip66(self, relay: Relay) -> None:
        """Construct with no metadata (all None)."""
        nip66 = Nip66(relay=relay)
        assert nip66.relay is relay
        assert nip66.rtt_metadata is None
        assert nip66.ssl_metadata is None
        assert nip66.geo_metadata is None
        assert nip66.net_metadata is None
        assert nip66.dns_metadata is None
        assert nip66.http_metadata is None


class TestNip66MetadataAccess:
    """Test metadata access via attributes."""

    def test_rtt_data_access(self, nip66_full: Nip66) -> None:
        """Access RTT values via data attributes."""
        assert nip66_full.rtt_metadata.data.rtt_open == 100
        assert nip66_full.rtt_metadata.data.rtt_read == 150
        assert nip66_full.rtt_metadata.data.rtt_write == 200

    def test_rtt_logs_access(self, nip66_full: Nip66) -> None:
        """Access probe test results via logs attributes."""
        assert nip66_full.rtt_metadata.logs.open_success is True
        assert nip66_full.rtt_metadata.logs.read_success is True
        assert nip66_full.rtt_metadata.logs.write_success is False
        assert nip66_full.rtt_metadata.logs.write_reason == "auth-required: please authenticate"

    def test_ssl_metadata_access(self, nip66_full: Nip66) -> None:
        """Access SSL values via data attributes."""
        assert nip66_full.ssl_metadata.data.ssl_valid is True
        assert nip66_full.ssl_metadata.data.ssl_issuer == "Let's Encrypt"
        assert nip66_full.ssl_metadata.data.ssl_protocol == "TLSv1.3"
        assert nip66_full.ssl_metadata.data.ssl_cipher_bits == 256

    def test_geo_metadata_access(self, nip66_full: Nip66) -> None:
        """Access geo values via data attributes."""
        assert nip66_full.geo_metadata.data.geo_country == "US"
        assert nip66_full.geo_metadata.data.geo_country_name == "United States"
        assert nip66_full.geo_metadata.data.geo_is_eu is False
        assert nip66_full.geo_metadata.data.geohash == "9q9hvu7wp"

    def test_net_metadata_access(self, nip66_full: Nip66) -> None:
        """Access net values via data attributes."""
        assert nip66_full.net_metadata.data.net_ip == "8.8.8.8"
        assert nip66_full.net_metadata.data.net_ipv6 == "2001:4860:4860::8888"
        assert nip66_full.net_metadata.data.net_asn == 15169
        assert nip66_full.net_metadata.data.net_asn_org == "GOOGLE"

    def test_dns_metadata_access(self, nip66_full: Nip66) -> None:
        """Access DNS values via data attributes."""
        assert nip66_full.dns_metadata.data.dns_ips == ["8.8.8.8", "8.8.4.4"]
        assert nip66_full.dns_metadata.data.dns_ips_v6 == ["2001:4860:4860::8888"]
        assert nip66_full.dns_metadata.data.dns_ttl == 300

    def test_http_metadata_access(self, nip66_full: Nip66) -> None:
        """Access HTTP values via data attributes."""
        assert nip66_full.http_metadata.data.http_server == "nginx/1.24.0"
        assert nip66_full.http_metadata.data.http_powered_by == "Strfry"


class TestNip66ToRelayMetadataTuple:
    """Test to_relay_metadata_tuple() method."""

    def test_returns_named_tuple_of_six(self, nip66_full: Nip66) -> None:
        """Returns RelayNip66MetadataTuple with 6 fields."""
        result = nip66_full.to_relay_metadata_tuple()
        assert isinstance(result, RelayNip66MetadataTuple)
        assert isinstance(result.nip66_rtt, RelayMetadata)
        assert isinstance(result.nip66_ssl, RelayMetadata)
        assert isinstance(result.nip66_geo, RelayMetadata)
        assert isinstance(result.nip66_net, RelayMetadata)
        assert isinstance(result.nip66_dns, RelayMetadata)
        assert isinstance(result.nip66_http, RelayMetadata)

    def test_correct_metadata_types(self, nip66_full: Nip66) -> None:
        """Each RelayMetadata has correct type via metadata.type."""
        result = nip66_full.to_relay_metadata_tuple()
        assert result.nip66_rtt.metadata.type == MetadataType.NIP66_RTT
        assert result.nip66_ssl.metadata.type == MetadataType.NIP66_SSL
        assert result.nip66_geo.metadata.type == MetadataType.NIP66_GEO
        assert result.nip66_net.metadata.type == MetadataType.NIP66_NET
        assert result.nip66_dns.metadata.type == MetadataType.NIP66_DNS
        assert result.nip66_http.metadata.type == MetadataType.NIP66_HTTP

    def test_returns_none_for_missing_metadata(self, nip66_rtt_only: Nip66) -> None:
        """Returns None for missing metadata types."""
        result = nip66_rtt_only.to_relay_metadata_tuple()
        assert isinstance(result.nip66_rtt, RelayMetadata)
        assert result.nip66_rtt.metadata.value["data"]["rtt_open"] == 100
        assert result.nip66_ssl is None
        assert result.nip66_geo is None
        assert result.nip66_net is None
        assert result.nip66_dns is None
        assert result.nip66_http is None

    def test_preserves_relay(self, nip66_full: Nip66) -> None:
        """Each RelayMetadata preserves relay reference."""
        result = nip66_full.to_relay_metadata_tuple()
        assert result.nip66_rtt.relay is nip66_full.relay
        assert result.nip66_ssl.relay is nip66_full.relay
        assert result.nip66_geo.relay is nip66_full.relay
        assert result.nip66_net.relay is nip66_full.relay
        assert result.nip66_dns.relay is nip66_full.relay
        assert result.nip66_http.relay is nip66_full.relay

    def test_preserves_generated_at(self, nip66_full: Nip66) -> None:
        """Each RelayMetadata preserves generated_at timestamp."""
        result = nip66_full.to_relay_metadata_tuple()
        assert result.nip66_rtt.generated_at == 1234567890
        assert result.nip66_ssl.generated_at == 1234567890
        assert result.nip66_geo.generated_at == 1234567890
        assert result.nip66_net.generated_at == 1234567890
        assert result.nip66_dns.generated_at == 1234567890
        assert result.nip66_http.generated_at == 1234567890

    def test_all_none_returns_all_none(self, relay: Relay) -> None:
        """All None metadata returns all None in tuple."""
        nip66 = Nip66(relay=relay)
        result = nip66.to_relay_metadata_tuple()
        assert result.nip66_rtt is None
        assert result.nip66_ssl is None
        assert result.nip66_geo is None
        assert result.nip66_net is None
        assert result.nip66_dns is None
        assert result.nip66_http is None


class TestNip66Create:
    """Test Nip66.create() class method."""

    @pytest.mark.asyncio
    async def test_returns_nip66_on_success(
        self,
        relay: Relay,
        mock_keys: MagicMock,
        mock_event_builder: MagicMock,
        mock_read_filter: MagicMock,
    ) -> None:
        """Returns Nip66 instance on successful create."""
        rtt_metadata = Nip66RttMetadata(
            data=Nip66RttData(rtt_open=100, rtt_read=150),
            logs=Nip66RttLogs(open_success=True, read_success=True),
        )
        dns_metadata = Nip66DnsMetadata(
            data=Nip66DnsData(dns_ips=["8.8.8.8"], dns_ttl=300),
            logs=Nip66DnsLogs(success=True, reason=None),
        )
        deps = Nip66Dependencies(
            keys=mock_keys, event_builder=mock_event_builder, read_filter=mock_read_filter
        )

        with (
            patch.object(
                Nip66DnsMetadata, "dns", new_callable=AsyncMock, return_value=dns_metadata
            ),
            patch.object(
                Nip66RttMetadata, "rtt", new_callable=AsyncMock, return_value=rtt_metadata
            ),
            patch.object(Nip66SslMetadata, "ssl", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66GeoMetadata, "geo", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66NetMetadata, "net", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66HttpMetadata, "http", new_callable=AsyncMock, return_value=None),
        ):
            result = await Nip66.create(relay, deps=deps)

        assert isinstance(result, Nip66)
        assert result.rtt_metadata.data.rtt_open == 100
        assert result.dns_metadata.data.dns_ips == ["8.8.8.8"]

    @pytest.mark.asyncio
    async def test_all_tests_fail_returns_nip66_with_none_metadata(
        self,
        relay: Relay,
        mock_keys: MagicMock,
        mock_event_builder: MagicMock,
        mock_read_filter: MagicMock,
    ) -> None:
        """All tests returning None creates Nip66 with None metadata."""
        deps = Nip66Dependencies(
            keys=mock_keys, event_builder=mock_event_builder, read_filter=mock_read_filter
        )

        with (
            patch.object(Nip66DnsMetadata, "dns", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66RttMetadata, "rtt", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66SslMetadata, "ssl", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66GeoMetadata, "geo", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66NetMetadata, "net", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66HttpMetadata, "http", new_callable=AsyncMock, return_value=None),
        ):
            result = await Nip66.create(relay, deps=deps)

        assert isinstance(result, Nip66)
        assert result.rtt_metadata is None
        assert result.ssl_metadata is None
        assert result.geo_metadata is None
        assert result.net_metadata is None
        assert result.dns_metadata is None
        assert result.http_metadata is None

    @pytest.mark.asyncio
    async def test_rtt_skipped_without_keys(self, relay: Relay) -> None:
        """run_rtt=True without keys/event_builder/read_filter skips RTT."""
        dns_metadata = Nip66DnsMetadata(
            data=Nip66DnsData(dns_ips=["8.8.8.8"]),
            logs=Nip66DnsLogs(success=True, reason=None),
        )
        flags = Nip66TestFlags(run_rtt=True, run_geo=False, run_net=False)

        with (
            patch.object(
                Nip66DnsMetadata, "dns", new_callable=AsyncMock, return_value=dns_metadata
            ),
            patch.object(Nip66SslMetadata, "ssl", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66HttpMetadata, "http", new_callable=AsyncMock, return_value=None),
        ):
            result = await Nip66.create(relay, flags=flags)

        assert isinstance(result, Nip66)
        assert result.rtt_metadata is None  # Skipped due to missing params

    @pytest.mark.asyncio
    async def test_can_skip_all_except_dns(self, relay: Relay) -> None:
        """Can skip all tests except DNS."""
        dns_metadata = Nip66DnsMetadata(
            data=Nip66DnsData(dns_ips=["8.8.8.8"], dns_ttl=300),
            logs=Nip66DnsLogs(success=True, reason=None),
        )
        flags = Nip66TestFlags(
            run_rtt=False, run_ssl=False, run_geo=False, run_net=False, run_http=False
        )

        with patch.object(
            Nip66DnsMetadata, "dns", new_callable=AsyncMock, return_value=dns_metadata
        ):
            result = await Nip66.create(relay, flags=flags)

        assert isinstance(result, Nip66)
        assert result.dns_metadata.data.dns_ips == ["8.8.8.8"]
        assert result.rtt_metadata is None
        assert result.ssl_metadata is None
        assert result.geo_metadata is None
        assert result.net_metadata is None
        assert result.http_metadata is None

    @pytest.mark.asyncio
    async def test_geo_requires_city_reader(self, relay: Relay) -> None:
        """run_geo=True without city_reader skips geo."""
        dns_metadata = Nip66DnsMetadata(
            data=Nip66DnsData(dns_ips=["8.8.8.8"]),
            logs=Nip66DnsLogs(success=True, reason=None),
        )
        flags = Nip66TestFlags(run_rtt=False, run_geo=True, run_net=False)

        with (
            patch.object(
                Nip66DnsMetadata, "dns", new_callable=AsyncMock, return_value=dns_metadata
            ),
            patch.object(Nip66SslMetadata, "ssl", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66HttpMetadata, "http", new_callable=AsyncMock, return_value=None),
        ):
            result = await Nip66.create(relay, flags=flags)

        assert result.geo_metadata is None  # Skipped

    @pytest.mark.asyncio
    async def test_net_requires_asn_reader(self, relay: Relay) -> None:
        """run_net=True without asn_reader skips net."""
        dns_metadata = Nip66DnsMetadata(
            data=Nip66DnsData(dns_ips=["8.8.8.8"]),
            logs=Nip66DnsLogs(success=True, reason=None),
        )
        flags = Nip66TestFlags(run_rtt=False, run_geo=False, run_net=True)

        with (
            patch.object(
                Nip66DnsMetadata, "dns", new_callable=AsyncMock, return_value=dns_metadata
            ),
            patch.object(Nip66SslMetadata, "ssl", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66HttpMetadata, "http", new_callable=AsyncMock, return_value=None),
        ):
            result = await Nip66.create(relay, flags=flags)

        assert result.net_metadata is None  # Skipped

    @pytest.mark.asyncio
    async def test_uses_default_timeout(self, relay: Relay) -> None:
        """Uses default timeout when None provided."""
        dns_metadata = Nip66DnsMetadata(
            data=Nip66DnsData(dns_ips=["8.8.8.8"]),
            logs=Nip66DnsLogs(success=True, reason=None),
        )
        flags = Nip66TestFlags(run_rtt=False, run_geo=False, run_net=False)

        with (
            patch.object(
                Nip66DnsMetadata, "dns", new_callable=AsyncMock, return_value=dns_metadata
            ),
            patch.object(Nip66SslMetadata, "ssl", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66HttpMetadata, "http", new_callable=AsyncMock, return_value=None),
        ):
            result = await Nip66.create(relay, timeout=None, flags=flags)

        assert isinstance(result, Nip66)

    @pytest.mark.asyncio
    async def test_passes_proxy_url(
        self,
        relay: Relay,
        mock_keys: MagicMock,
        mock_event_builder: MagicMock,
        mock_read_filter: MagicMock,
    ) -> None:
        """Passes proxy_url to RTT and HTTP tests."""
        rtt_metadata = Nip66RttMetadata(
            data=Nip66RttData(rtt_open=100),
            logs=Nip66RttLogs(open_success=True),
        )
        deps = Nip66Dependencies(
            keys=mock_keys, event_builder=mock_event_builder, read_filter=mock_read_filter
        )

        with (
            patch.object(Nip66DnsMetadata, "dns", new_callable=AsyncMock, return_value=None),
            patch.object(
                Nip66RttMetadata, "rtt", new_callable=AsyncMock, return_value=rtt_metadata
            ) as mock_rtt,
            patch.object(Nip66SslMetadata, "ssl", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66GeoMetadata, "geo", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66NetMetadata, "net", new_callable=AsyncMock, return_value=None),
            patch.object(Nip66HttpMetadata, "http", new_callable=AsyncMock, return_value=None),
        ):
            await Nip66.create(relay, deps=deps, proxy_url="socks5://localhost:9050")

        mock_rtt.assert_called_once()
        call_args = mock_rtt.call_args
        # Positional args: relay, rtt_deps, timeout, proxy_url, allow_insecure
        assert call_args[0][3] == "socks5://localhost:9050"

    @pytest.mark.asyncio
    async def test_all_disabled_returns_empty_nip66(self, relay: Relay) -> None:
        """All tests disabled returns Nip66 with all None metadata."""
        flags = Nip66TestFlags(
            run_rtt=False,
            run_ssl=False,
            run_geo=False,
            run_net=False,
            run_dns=False,
            run_http=False,
        )
        result = await Nip66.create(relay, flags=flags)

        assert isinstance(result, Nip66)
        assert result.rtt_metadata is None
        assert result.ssl_metadata is None
        assert result.geo_metadata is None
        assert result.net_metadata is None
        assert result.dns_metadata is None
        assert result.http_metadata is None


class TestRelayNip66MetadataTuple:
    """Test RelayNip66MetadataTuple named tuple."""

    def test_named_tuple_fields(self) -> None:
        """Verify named tuple has all expected fields."""
        fields = RelayNip66MetadataTuple._fields
        assert "nip66_rtt" in fields
        assert "nip66_ssl" in fields
        assert "nip66_geo" in fields
        assert "nip66_net" in fields
        assert "nip66_dns" in fields
        assert "nip66_http" in fields
        assert len(fields) == 6

    def test_can_create_with_all_none(self) -> None:
        """Can create tuple with all None values."""
        result = RelayNip66MetadataTuple(
            nip66_rtt=None,
            nip66_ssl=None,
            nip66_geo=None,
            nip66_net=None,
            nip66_dns=None,
            nip66_http=None,
        )
        assert all(v is None for v in result)

    def test_can_iterate(self, nip66_full: Nip66) -> None:
        """Can iterate over tuple values."""
        result = nip66_full.to_relay_metadata_tuple()
        values = list(result)
        assert len(values) == 6
        assert all(isinstance(v, RelayMetadata) for v in values)


class TestNip66Immutability:
    """Test that Nip66 is frozen/immutable."""

    def test_cannot_modify_relay(self, nip66_full: Nip66, relay: Relay) -> None:
        """Cannot modify relay after creation."""
        from pydantic import ValidationError

        new_relay = Relay(raw_url="wss://other.example.com", discovered_at=1)
        with pytest.raises((ValidationError, TypeError, AttributeError)):
            nip66_full.relay = new_relay  # type: ignore[misc]

    def test_cannot_modify_metadata(
        self,
        nip66_full: Nip66,
        complete_ssl_metadata: Nip66SslMetadata,
    ) -> None:
        """Cannot modify metadata after creation."""
        from pydantic import ValidationError

        with pytest.raises((ValidationError, TypeError, AttributeError)):
            nip66_full.ssl_metadata = complete_ssl_metadata  # type: ignore[misc]

    def test_cannot_modify_generated_at(self, nip66_full: Nip66) -> None:
        """Cannot modify generated_at after creation."""
        from pydantic import ValidationError

        with pytest.raises((ValidationError, TypeError, AttributeError)):
            nip66_full.generated_at = 999  # type: ignore[misc]
