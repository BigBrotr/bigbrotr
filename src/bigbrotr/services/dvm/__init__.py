"""NIP-90 adapter for public readable-resource queries over Nostr.

Exports the package-level Nostr adapter surface:

- [Dvm][bigbrotr.services.dvm.service.Dvm]: Adapter lifecycle, job execution,
  and relay subscription handling over the shared read core.
- [DvmConfig][bigbrotr.services.dvm.configs.DvmConfig]: Relay, pricing, and
  exposure-policy configuration.

The package preserves the stable historical ``read_model`` request parameter
while keeping NIP-90 transport concerns local to this adapter.
"""

from .configs import DvmConfig
from .service import Dvm


__all__ = ["Dvm", "DvmConfig"]
