"""Ranker service package.

Re-exports all public symbols for backwards-compatible imports::

    from bigbrotr.services.ranker import Ranker, RankerConfig
"""

from .configs import RankerConfig
from .service import Ranker


__all__ = [
    "Ranker",
    "RankerConfig",
]
