"""Event-archive ingestion service for validated relays.

Exports the package-level archive-ingestion surface:

- [Synchronizer][bigbrotr.services.synchronizer.service.Synchronizer]: Relay
  loop and event-stream orchestration for validated relays.
- [SynchronizerConfig][bigbrotr.services.synchronizer.configs.SynchronizerConfig]
  plus the processing and timeout config models: sync-window, batching, and
  network policy.

This package owns event archive ingestion and relay cursors; shared derived
facts belong downstream in the refresher.
"""

from .configs import (
    ProcessingConfig,
    SynchronizerConfig,
    TimeoutsConfig,
)
from .service import Synchronizer


__all__ = [
    "ProcessingConfig",
    "Synchronizer",
    "SynchronizerConfig",
    "TimeoutsConfig",
]
