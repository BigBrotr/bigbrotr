"""
NIP model implementations for NIP-11 and NIP-66.

Re-exports the top-level ``Nip11`` and ``Nip66`` classes along with the
shared base classes used for inheritance across all NIP data models.
"""

from models.nips.base import BaseData, BaseLogs, BaseMetadata
from models.nips.nip11 import Nip11
from models.nips.nip66 import Nip66


__all__ = ["BaseData", "BaseLogs", "BaseMetadata", "Nip11", "Nip66"]
