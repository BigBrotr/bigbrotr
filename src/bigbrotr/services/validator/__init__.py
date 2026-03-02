"""Validator service package.

Re-exports all public symbols for backwards-compatible imports::

    from bigbrotr.services.validator import Validator, ValidatorConfig
"""

from bigbrotr.services.common.types import CandidateCheckpoint

from .configs import CleanupConfig, ProcessingConfig, ValidatorConfig
from .service import Validator


__all__ = [
    "CandidateCheckpoint",
    "CleanupConfig",
    "ProcessingConfig",
    "Validator",
    "ValidatorConfig",
]
