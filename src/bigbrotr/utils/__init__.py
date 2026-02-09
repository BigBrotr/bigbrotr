"""BigBrotr utility package.

Re-exports commonly used utilities for convenient imports across the codebase:

- **Configuration**: ``KeysConfig``
- **Transport**: ``create_client`` (Nostr client factory)
- **DNS**: ``resolve_host``, ``ResolvedHost``
- **Network types**: ``NetworkType`` (canonical home: ``bigbrotr.models.constants``)

Network configuration models (``NetworkConfig``, ``ClearnetConfig``, etc.) live in
``bigbrotr.services.common.configs``.  Import them directly from there.

Example::

    from bigbrotr.utils import create_client, KeysConfig
"""

from bigbrotr.models.constants import NetworkType
from bigbrotr.utils.dns import ResolvedHost, resolve_host
from bigbrotr.utils.keys import KeysConfig, load_keys_from_env
from bigbrotr.utils.transport import create_client


__all__ = [
    "KeysConfig",
    "NetworkType",
    "ResolvedHost",
    "create_client",
    "load_keys_from_env",
    "resolve_host",
]
