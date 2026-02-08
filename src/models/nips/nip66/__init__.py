"""
NIP-66 Relay Monitoring and Discovery models.

Implements relay capability testing and monitoring data collection as
defined by NIP-66. Each test type (RTT, SSL, GEO, NET, DNS, HTTP) has
its own data model, logs model, and metadata container. Raw data is
sanitized through ``parse()`` methods and validated into typed, frozen
Pydantic models. Invalid fields or wrong types are silently dropped.

See: https://github.com/nostr-protocol/nips/blob/master/66.md

Model hierarchy::

    Nip66                                        Top-level container
    +-- relay: Relay                             Source relay reference
    +-- generated_at: int                        Unix timestamp
    +-- rtt_metadata: Nip66RttMetadata           Round-trip time probes
    |   +-- data: Nip66RttData
    |   +-- logs: Nip66RttLogs                   (open/read/write results)
    +-- ssl_metadata: Nip66SslMetadata           SSL/TLS certificate
    |   +-- data: Nip66SslData
    |   +-- logs: Nip66SslLogs
    +-- geo_metadata: Nip66GeoMetadata           Geolocation (GeoIP)
    |   +-- data: Nip66GeoData
    |   +-- logs: Nip66GeoLogs
    +-- net_metadata: Nip66NetMetadata           Network/ASN info
    |   +-- data: Nip66NetData
    |   +-- logs: Nip66NetLogs
    +-- dns_metadata: Nip66DnsMetadata           DNS resolution
    |   +-- data: Nip66DnsData
    |   +-- logs: Nip66DnsLogs
    +-- http_metadata: Nip66HttpMetadata         HTTP server headers
        +-- data: Nip66HttpData
        +-- logs: Nip66HttpLogs
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
from .nip66 import Nip66, Nip66Dependencies, Nip66TestFlags, RelayNip66MetadataTuple
from .rtt import Nip66RttMetadata, RttDependencies
from .ssl import Nip66SslMetadata


__all__ = [
    "Nip66",
    "Nip66BaseLogs",
    "Nip66Dependencies",
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
    "Nip66TestFlags",
    "RelayNip66MetadataTuple",
    "RttDependencies",
]
