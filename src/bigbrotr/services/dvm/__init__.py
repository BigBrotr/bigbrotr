"""NIP-90 Data Vending Machine service for Nostr-based database queries.

Re-exports all public symbols for backwards-compatible imports::

    from bigbrotr.services.dvm import Dvm, DvmConfig

See Also:
    [Dvm][bigbrotr.services.dvm.service.Dvm]: The service class.
    [DvmConfig][bigbrotr.services.dvm.configs.DvmConfig]: Service configuration.
"""

from .configs import DvmConfig
from .service import Dvm


__all__ = ["Dvm", "DvmConfig"]
