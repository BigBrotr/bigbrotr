"""NIP-66 Relay Monitoring and Discovery models.

Implements [NIP-66](https://github.com/nostr-protocol/nips/blob/master/66.md)
-- relay capability testing and monitoring data collection. Each test type
(RTT, SSL, GEO, NET, DNS, HTTP) has its own data model, logs model, and
metadata container. Raw data is sanitized through ``parse()`` methods and
validated into typed, frozen Pydantic models. Invalid fields or wrong types
are silently dropped.

Model hierarchy:

```text
Nip66                                        Top-level container
+-- relay: Relay                             Source relay reference
+-- generated_at: int                        Unix timestamp
+-- rtt: Nip66RttMetadata                    Round-trip time probes
|   +-- data: Nip66RttData
|   +-- logs: Nip66RttMultiPhaseLogs          (open/read/write results)
+-- ssl: Nip66SslMetadata                    SSL/TLS certificate
|   +-- data: Nip66SslData
|   +-- logs: Nip66SslLogs
+-- geo: Nip66GeoMetadata                    Geolocation (GeoIP)
|   +-- data: Nip66GeoData
|   +-- logs: Nip66GeoLogs
+-- net: Nip66NetMetadata                    Network/ASN info
|   +-- data: Nip66NetData
|   +-- logs: Nip66NetLogs
+-- dns: Nip66DnsMetadata                    DNS resolution
|   +-- data: Nip66DnsData
|   +-- logs: Nip66DnsLogs
+-- http: Nip66HttpMetadata                  HTTP server headers
    +-- data: Nip66HttpData
    +-- logs: Nip66HttpLogs
```

Note:
    Each test produces a separate
    [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata] record
    with a distinct [MetadataType][bigbrotr.models.metadata.MetadataType]
    variant (``NIP66_RTT``, ``NIP66_SSL``, ``NIP66_GEO``, ``NIP66_NET``,
    ``NIP66_DNS``, ``NIP66_HTTP``). Tests are executed concurrently via
    ``asyncio.gather`` in [Nip66.create][bigbrotr.nips.nip66.nip66.Nip66.create].

See Also:
    [bigbrotr.nips.nip11][bigbrotr.nips.nip11]: Companion NIP-11 module for
        relay information documents.
    [bigbrotr.models.metadata.MetadataType][bigbrotr.models.metadata.MetadataType]:
        Enum with ``NIP66_*`` variants for each test type.
    [bigbrotr.services.monitor.Monitor][bigbrotr.services.monitor.Monitor]:
        Service that orchestrates NIP-66 checks per relay.
    [bigbrotr.nips.event_builders][bigbrotr.nips.event_builders]: Event builders
        that construct kind 0, 10166, and 30166 events from typed NIP data.
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
    Nip66RttMultiPhaseLogs,
    Nip66SslLogs,
)
from .net import Nip66NetMetadata
from .nip66 import (
    Nip66,
    Nip66Dependencies,
    Nip66Options,
    Nip66Selection,
    RelayNip66MetadataTuple,
)
from .rtt import Nip66RttDependencies, Nip66RttMetadata
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
    "Nip66Options",
    "Nip66RttData",
    "Nip66RttDependencies",
    "Nip66RttMetadata",
    "Nip66RttMultiPhaseLogs",
    "Nip66Selection",
    "Nip66SslData",
    "Nip66SslLogs",
    "Nip66SslMetadata",
    "RelayNip66MetadataTuple",
]
