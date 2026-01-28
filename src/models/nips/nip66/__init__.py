"""
NIP-66 Relay Monitoring and Discovery.

Tests relay capabilities and collects monitoring data per NIP-66 specification.
Raw data is sanitized via parse() then validated into typed frozen Pydantic models.
Invalid fields or wrong types are silently dropped (not raised as errors).

See: https://github.com/nostr-protocol/nips/blob/master/66.md

Model Hierarchy::

    Nip66                                        # Main class
    ├── relay: Relay                             # Source relay
    ├── generated_at: int                        # Unix timestamp
    ├── rtt_metadata: Nip66RttMetadata | None
    │   ├── data: Nip66RttData
    │   │   ├── rtt_open: int | None
    │   │   ├── rtt_read: int | None
    │   │   └── rtt_write: int | None
    │   └── logs: Nip66RttLogs
    │       ├── open_success: bool (required)
    │       ├── open_reason: str | None
    │       ├── read_success: bool | None
    │       ├── read_reason: str | None
    │       ├── write_success: bool | None
    │       └── write_reason: str | None
    ├── ssl_metadata: Nip66SslMetadata | None
    │   ├── data: Nip66SslData
    │   │   ├── ssl_valid: bool | None
    │   │   ├── ssl_subject_cn: str | None
    │   │   ├── ssl_issuer: str | None
    │   │   ├── ssl_issuer_cn: str | None
    │   │   ├── ssl_expires: int | None
    │   │   ├── ssl_not_before: int | None
    │   │   ├── ssl_san: list[str] | None
    │   │   ├── ssl_serial: str | None
    │   │   ├── ssl_version: int | None
    │   │   ├── ssl_fingerprint: str | None
    │   │   ├── ssl_protocol: str | None
    │   │   ├── ssl_cipher: str | None
    │   │   └── ssl_cipher_bits: int | None
    │   └── logs: Nip66SslLogs
    │       ├── success: bool
    │       └── reason: str | None
    ├── geo_metadata: Nip66GeoMetadata | None
    │   ├── data: Nip66GeoData
    │   │   ├── geo_country: str | None
    │   │   ├── geo_country_name: str | None
    │   │   ├── geo_continent: str | None
    │   │   ├── geo_continent_name: str | None
    │   │   ├── geo_is_eu: bool | None
    │   │   ├── geo_region: str | None
    │   │   ├── geo_city: str | None
    │   │   ├── geo_postal: str | None
    │   │   ├── geo_lat: float | None
    │   │   ├── geo_lon: float | None
    │   │   ├── geo_accuracy: int | None
    │   │   ├── geo_tz: str | None
    │   │   ├── geohash: str | None
    │   │   └── geo_geoname_id: int | None
    │   └── logs: Nip66GeoLogs
    │       ├── success: bool
    │       └── reason: str | None
    ├── net_metadata: Nip66NetMetadata | None
    │   ├── data: Nip66NetData
    │   │   ├── net_ip: str | None
    │   │   ├── net_ipv6: str | None
    │   │   ├── net_asn: int | None
    │   │   ├── net_asn_org: str | None
    │   │   ├── net_network: str | None
    │   │   └── net_network_v6: str | None
    │   └── logs: Nip66NetLogs
    │       ├── success: bool
    │       └── reason: str | None
    ├── dns_metadata: Nip66DnsMetadata | None
    │   ├── data: Nip66DnsData
    │   │   ├── dns_ips: list[str] | None
    │   │   ├── dns_ips_v6: list[str] | None
    │   │   ├── dns_cname: str | None
    │   │   ├── dns_reverse: str | None
    │   │   ├── dns_ns: list[str] | None
    │   │   └── dns_ttl: int | None
    │   └── logs: Nip66DnsLogs
    │       ├── success: bool
    │       └── reason: str | None
    └── http_metadata: Nip66HttpMetadata | None
        ├── data: Nip66HttpData
        │   ├── http_server: str | None
        │   └── http_powered_by: str | None
        └── logs: Nip66HttpLogs
            ├── success: bool
            └── reason: str | None

Usage::

    from models.nips.nip66 import Nip66
    from models.relay import Relay

    # Create monitoring data (always returns Nip66, never None)
    relay = Relay("wss://relay.damus.io")
    nip66 = await Nip66.create(
        relay,
        keys=keys,
        event_builder=event_builder,
        read_filter=read_filter,
        city_reader=city_reader,
        asn_reader=asn_reader,
    )

    # Check RTT results
    if nip66.rtt_metadata:
        print(f"Open RTT: {nip66.rtt_metadata.data.rtt_open}ms")
        print(f"Write allowed: {nip66.rtt_metadata.logs.write_success}")

    # Check other metadata
    if nip66.geo_metadata and nip66.geo_metadata.logs.success:
        print(f"Country: {nip66.geo_metadata.data.geo_country}")

    # Convert for database storage
    metadata_tuple = nip66.to_relay_metadata_tuple()
"""

from .data import (
    Nip66DnsData,
    Nip66GeoData,
    Nip66HttpData,
    Nip66NetData,
    Nip66RttData,
    Nip66SslData,
)
from .dns import Nip66DnsMetadata
from .geo import Nip66GeoMetadata
from .http import Nip66HttpMetadata
from .logs import (
    Nip66BaseLogs,
    Nip66DnsLogs,
    Nip66GeoLogs,
    Nip66HttpLogs,
    Nip66NetLogs,
    Nip66RttLogs,
    Nip66SslLogs,
)
from .net import Nip66NetMetadata
from .nip66 import Nip66, RelayNip66MetadataTuple
from .rtt import Nip66RttMetadata
from .ssl import Nip66SslMetadata


__all__ = [
    "Nip66",
    "Nip66BaseLogs",
    "Nip66DnsData",
    "Nip66DnsLogs",
    "Nip66DnsMetadata",
    "Nip66GeoData",
    "Nip66GeoLogs",
    "Nip66GeoMetadata",
    "Nip66HttpData",
    "Nip66HttpLogs",
    "Nip66HttpMetadata",
    "Nip66NetData",
    "Nip66NetLogs",
    "Nip66NetMetadata",
    "Nip66RttData",
    "Nip66RttLogs",
    "Nip66RttMetadata",
    "Nip66SslData",
    "Nip66SslLogs",
    "Nip66SslMetadata",
    "RelayNip66MetadataTuple",
]
