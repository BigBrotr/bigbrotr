"""NIP models package.

Re-exports Nip11 and Nip66 for API compatibility.
Also exports base classes for inheritance.
"""

from models.nips.base import BaseData, BaseLogs, BaseMetadata
from models.nips.nip11 import Nip11
from models.nips.nip66 import Nip66


__all__ = ["BaseData", "BaseLogs", "BaseMetadata", "Nip11", "Nip66"]
