"""NIP-90 Data Vending Machine service for Nostr-based database queries.

See Also:
    [Dvm][bigbrotr.services.dvm.service.Dvm]: The service class.
    [DvmConfig][bigbrotr.services.dvm.service.DvmConfig]: Service configuration.
"""

from .service import Dvm, DvmConfig


__all__ = ["Dvm", "DvmConfig"]
