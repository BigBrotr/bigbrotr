"""Relay monitoring service for NIP-11/NIP-66 collection and publication.

Exports the package-level monitoring surface:

- [Monitor][bigbrotr.services.monitor.service.Monitor]: Cycle orchestration for
  document collection, probe execution, and publication.
- [MonitorConfig][bigbrotr.services.monitor.configs.MonitorConfig] plus the
  nested publishing, metadata, discovery, and geo config models: policy
  surface for monitor execution.
- [CheckResult][bigbrotr.services.monitor.utils.CheckResult]: Typed result
  wrapper for one monitor probe execution.

This package owns relay-document collection and monitor-side publication.
"""

from .configs import (
    AnnouncementConfig,
    DiscoveryConfig,
    GeoConfig,
    MetadataFlags,
    MonitorConfig,
    ProcessingConfig,
    ProfileConfig,
    PublishingConfig,
    RelayListConfig,
)
from .service import Monitor
from .utils import CheckResult


__all__ = [
    "AnnouncementConfig",
    "CheckResult",
    "DiscoveryConfig",
    "GeoConfig",
    "MetadataFlags",
    "Monitor",
    "MonitorConfig",
    "ProcessingConfig",
    "ProfileConfig",
    "PublishingConfig",
    "RelayListConfig",
]
