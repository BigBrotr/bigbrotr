"""NIP-85 Trusted Assertions publisher service.

See Also:
    [Assertor][bigbrotr.services.assertor.Assertor]: The service class.
    [AssertorConfig][bigbrotr.services.assertor.AssertorConfig]:
        Configuration model.
"""

from .configs import AssertorConfig
from .service import Assertor


__all__ = ["Assertor", "AssertorConfig"]
