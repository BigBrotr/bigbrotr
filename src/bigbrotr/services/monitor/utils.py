"""Monitor service utility functions.

Pure helpers for health check result inspection, metadata collection,
relay discovery event building, and relay list selection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from bigbrotr.models import Metadata, MetadataType, RelayMetadata
from bigbrotr.models.constants import NetworkType
from bigbrotr.nips.base import BaseLogs, BaseNipMetadata
from bigbrotr.nips.event_builders import (
    build_monitor_announcement,
    build_profile_event,
    build_relay_discovery,
)
from bigbrotr.nips.nip11 import Nip11Selection
from bigbrotr.nips.nip66 import Nip66Selection
from bigbrotr.nips.nip66.logs import Nip66RttMultiPhaseLogs


if TYPE_CHECKING:
    from nostr_sdk import EventBuilder

    from bigbrotr.models import Relay
    from bigbrotr.nips.nip11.info import Nip11InfoMetadata
    from bigbrotr.nips.nip66 import (
        Nip66DnsMetadata,
        Nip66GeoMetadata,
        Nip66HttpMetadata,
        Nip66NetMetadata,
        Nip66RttMetadata,
        Nip66SslMetadata,
    )
    from bigbrotr.services.monitor.configs import MetadataFlags, MonitorConfig, ProfileConfig


class CheckResult(NamedTuple):
    """Result of a single relay health check.

    Each field contains the typed NIP metadata container if that check was run
    and produced data, or ``None`` if the check was skipped (disabled in config)
    or failed completely. Use ``has_data`` to test whether any check produced
    results.

    Attributes:
        generated_at: Unix timestamp when the health check was performed.
        nip11: NIP-11 relay information document (name, description, pubkey, etc.).
        nip66_rtt: Round-trip times for open/read/write operations in milliseconds.
        nip66_ssl: SSL certificate validation (valid, expiry timestamp, issuer).
        nip66_geo: Geolocation data (country, city, coordinates, timezone, geohash).
        nip66_net: Network information (IP address, ASN, organization).
        nip66_dns: DNS resolution data (IPs, CNAME, nameservers, reverse DNS).
        nip66_http: HTTP metadata (server software and framework headers).

    See Also:
        [MetadataFlags][bigbrotr.services.monitor.MetadataFlags]: Boolean
            flags controlling which check types are computed and stored.
    """

    generated_at: int = 0
    nip11: Nip11InfoMetadata | None = None
    nip66_rtt: Nip66RttMetadata | None = None
    nip66_ssl: Nip66SslMetadata | None = None
    nip66_geo: Nip66GeoMetadata | None = None
    nip66_net: Nip66NetMetadata | None = None
    nip66_dns: Nip66DnsMetadata | None = None
    nip66_http: Nip66HttpMetadata | None = None

    @property
    def has_data(self) -> bool:
        """True if at least one NIP check produced data."""
        return any(
            (
                self.nip11,
                self.nip66_rtt,
                self.nip66_ssl,
                self.nip66_geo,
                self.nip66_net,
                self.nip66_dns,
                self.nip66_http,
            )
        )


def get_success(result: Any) -> bool:
    """Extract success status from a metadata result's logs object."""
    logs = result.logs
    if isinstance(logs, BaseLogs):
        return bool(logs.success)
    if isinstance(logs, Nip66RttMultiPhaseLogs):
        return bool(logs.open_success)
    return False


def get_reason(result: Any) -> str | None:
    """Extract failure reason from a metadata result's logs object."""
    logs = result.logs
    if isinstance(logs, BaseLogs):
        return str(logs.reason) if logs.reason else None
    if isinstance(logs, Nip66RttMultiPhaseLogs):
        return str(logs.open_reason) if logs.open_reason else None
    return None


def safe_result(results: dict[str, Any], key: str) -> Any:
    """Extract a successful result from asyncio.gather output.

    Returns None if the key is absent or the result is an exception.
    """
    value = results.get(key)
    if value is None or isinstance(value, BaseException):
        return None
    return value


def collect_metadata(
    successful: list[tuple[Relay, CheckResult]],
    store: MetadataFlags,
) -> list[RelayMetadata]:
    """Collect storable metadata from successful health check results.

    Converts typed NIP metadata into
    [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]
    records for database insertion.

    Args:
        successful: List of ([Relay][bigbrotr.models.relay.Relay],
            [CheckResult][bigbrotr.services.monitor.CheckResult])
            pairs from health checks.
        store: Flags controlling which metadata types to persist.

    Returns:
        List of [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]
        records ready for database insertion.
    """
    metadata: list[RelayMetadata] = []
    check_specs: list[tuple[str, str, MetadataType]] = [
        ("nip11", "nip11_info", MetadataType.NIP11_INFO),
        ("nip66_rtt", "nip66_rtt", MetadataType.NIP66_RTT),
        ("nip66_ssl", "nip66_ssl", MetadataType.NIP66_SSL),
        ("nip66_geo", "nip66_geo", MetadataType.NIP66_GEO),
        ("nip66_net", "nip66_net", MetadataType.NIP66_NET),
        ("nip66_dns", "nip66_dns", MetadataType.NIP66_DNS),
        ("nip66_http", "nip66_http", MetadataType.NIP66_HTTP),
    ]
    for relay, result in successful:
        for result_field, store_field, meta_type in check_specs:
            nip_meta: BaseNipMetadata | None = getattr(result, result_field)
            if nip_meta and getattr(store, store_field):
                metadata.append(
                    RelayMetadata(
                        relay=relay,
                        metadata=Metadata(type=meta_type, data=nip_meta.to_dict()),
                        generated_at=result.generated_at,
                    )
                )
    return metadata


def get_publish_relays(
    section_relays: list[Relay] | None,
    default_relays: list[Relay],
) -> list[Relay]:
    """Return section-specific relays, falling back to the default publishing list.

    Args:
        section_relays: Section-specific relay list, or ``None`` if not configured.
        default_relays: Fallback relay list from ``publishing.relays``.

    Returns:
        ``section_relays`` if set (even if empty), otherwise ``default_relays``.
    """
    return section_relays if section_relays is not None else default_relays


def build_kind_0(profile: ProfileConfig) -> EventBuilder:
    """Build Kind 0 profile metadata event per NIP-01."""
    return build_profile_event(
        name=profile.name,
        about=profile.about,
        picture=profile.picture,
        nip05=profile.nip05,
        website=profile.website,
        banner=profile.banner,
        lud16=profile.lud16,
    )


def build_kind_10166(config: MonitorConfig) -> EventBuilder:
    """Build Kind 10166 monitor announcement event per NIP-66."""
    include = config.announcement.include
    enabled_networks = [network for network in NetworkType if config.networks.is_enabled(network)]
    first_network = enabled_networks[0] if enabled_networks else NetworkType.CLEARNET
    timeout_ms = int(config.networks.get(first_network).timeout * 1000)
    return build_monitor_announcement(
        interval=int(config.interval),
        timeout_ms=timeout_ms,
        enabled_networks=enabled_networks,
        nip11_selection=Nip11Selection(info=include.nip11_info),
        nip66_selection=Nip66Selection(
            rtt=include.nip66_rtt,
            ssl=include.nip66_ssl,
            geo=include.nip66_geo,
            net=include.nip66_net,
            dns=include.nip66_dns,
            http=include.nip66_http,
        ),
    )


def build_kind_30166(relay: Relay, result: CheckResult, include: MetadataFlags) -> EventBuilder:
    """Build a Kind 30166 relay discovery event per NIP-66."""
    nip11_canonical_json = ""
    if result.nip11 and include.nip11_info:
        meta = Metadata(type=MetadataType.NIP11_INFO, data=result.nip11.to_dict())
        nip11_canonical_json = meta.canonical_json

    return build_relay_discovery(
        relay.url,
        relay.network.value,
        nip11_canonical_json,
        rtt_data=result.nip66_rtt.data if result.nip66_rtt and include.nip66_rtt else None,
        ssl_data=result.nip66_ssl.data if result.nip66_ssl and include.nip66_ssl else None,
        net_data=result.nip66_net.data if result.nip66_net and include.nip66_net else None,
        geo_data=result.nip66_geo.data if result.nip66_geo and include.nip66_geo else None,
        nip11_data=result.nip11.data if result.nip11 and include.nip11_info else None,
        rtt_logs=result.nip66_rtt.logs if result.nip66_rtt else None,
    )
