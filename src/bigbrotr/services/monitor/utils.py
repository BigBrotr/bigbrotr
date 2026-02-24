"""Monitor service utility functions.

Pure helpers for health check result inspection and metadata collection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bigbrotr.models import Metadata, MetadataType, RelayMetadata
from bigbrotr.nips.base import BaseLogs, BaseNipMetadata
from bigbrotr.nips.nip66.logs import Nip66RttMultiPhaseLogs


if TYPE_CHECKING:
    from bigbrotr.models import Relay
    from bigbrotr.services.monitor.configs import MetadataFlags
    from bigbrotr.services.monitor.service import CheckResult


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
