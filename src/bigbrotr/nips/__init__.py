"""
NIP model implementations for NIP-11 and NIP-66.

Re-exports the top-level ``Nip11`` and ``Nip66`` classes along with the
shared base classes used for inheritance across all NIP data models.
"""

from bigbrotr.nips.base import BaseData, BaseLogs, BaseMetadata
from bigbrotr.nips.nip11 import Nip11
from bigbrotr.nips.nip66 import Nip66


__all__ = ["BaseData", "BaseLogs", "BaseMetadata", "Nip11", "Nip66"]
