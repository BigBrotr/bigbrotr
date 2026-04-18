"""NIP-90 adapter for public readable-resource queries over Nostr.

Re-exports the public package symbols::

    from bigbrotr.services.dvm import Dvm, DvmConfig

See Also:
    [Dvm][bigbrotr.services.dvm.service.Dvm]: The service class.
    [DvmConfig][bigbrotr.services.dvm.configs.DvmConfig]: Adapter configuration,
        including relay settings and exposure policy.
"""

from .configs import DvmConfig
from .service import Dvm


__all__ = ["Dvm", "DvmConfig"]
