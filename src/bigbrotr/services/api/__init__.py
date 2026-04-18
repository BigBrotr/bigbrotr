"""HTTP adapter for public readable-resource exposure.

See Also:
    [Api][bigbrotr.services.api.service.Api]: The service class.
    [ApiConfig][bigbrotr.services.api.configs.ApiConfig]: Adapter configuration,
        including pagination and exposure policy.
"""

from .configs import ApiConfig
from .service import Api


__all__ = ["Api", "ApiConfig"]
