"""NIP-90 Data Vending Machine service for Nostr-based database queries.

See Also:
    [Dvm][bigbrotr.services.dvm.service.Dvm]: The service class.
    [DvmConfig][bigbrotr.services.dvm.configs.DvmConfig]: Service configuration.
"""

from .configs import DvmConfig
from .service import Dvm


__all__ = ["Dvm", "DvmConfig"]
