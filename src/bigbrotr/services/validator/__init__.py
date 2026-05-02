"""Candidate-relay validation and promotion service.

Exports the package-level validation surface:

- [Validator][bigbrotr.services.validator.service.Validator]: Relay handshake
  validation and promotion flow.
- [ValidatorConfig][bigbrotr.services.validator.configs.ValidatorConfig] plus
  the processing and cleanup config models: concurrency, retry, and stale
  candidate cleanup policy.

Discovery and promotion stay separate by contract: finder discovers candidate
URLs, while validator decides whether they become canonical relays.
"""

from .configs import CleanupConfig, ProcessingConfig, ValidatorConfig
from .service import Validator


__all__ = [
    "CleanupConfig",
    "ProcessingConfig",
    "Validator",
    "ValidatorConfig",
]
