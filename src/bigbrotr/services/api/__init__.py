"""HTTP adapter for public readable-resource exposure.

Exports the package-level HTTP adapter surface:

- [Api][bigbrotr.services.api.service.Api]: FastAPI lifecycle and route
  registration over the shared read core.
- [ApiConfig][bigbrotr.services.api.configs.ApiConfig]: Adapter-local exposure
  and pagination policy.

The package preserves the stable ``/read-models`` transport contract while
keeping HTTP concerns thin over ``bigbrotr.services.common``.
"""

from .configs import ApiConfig
from .service import Api


__all__ = ["Api", "ApiConfig"]
