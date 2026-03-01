"""REST API service for read-only database exposure.

See Also:
    [Api][bigbrotr.services.api.service.Api]: The service class.
    [ApiConfig][bigbrotr.services.api.configs.ApiConfig]: Service configuration.
"""

from .configs import ApiConfig
from .service import Api


__all__ = ["Api", "ApiConfig"]
