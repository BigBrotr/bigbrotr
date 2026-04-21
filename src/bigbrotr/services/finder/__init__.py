"""Relay discovery service for stored events and external API sources.

Exports the package-level discovery surface:

- [Finder][bigbrotr.services.finder.service.Finder]: Orchestrates the event and
  API discovery phases.
- [FinderConfig][bigbrotr.services.finder.configs.FinderConfig] plus the
  source-specific config models: configuration for stored-event discovery,
  external API polling, and candidate persistence cadence.

Event and API discovery stay inside one service boundary here, while relay
promotion remains the validator's responsibility.
"""

from .configs import (
    ApiConfig,
    ApiSourceConfig,
    EventsConfig,
    FinderConfig,
)
from .service import Finder


__all__ = [
    "ApiConfig",
    "ApiSourceConfig",
    "EventsConfig",
    "Finder",
    "FinderConfig",
]
