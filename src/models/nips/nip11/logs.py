"""NIP-11 logs models."""

from __future__ import annotations

from models.nips.base import BaseLogs


class Nip11FetchLogs(BaseLogs):
    """Fetch operation logs with semantic validation.

    Inherits from BaseLogs:
        - success: StrictBool (required)
        - reason: None when success=True, str when success=False
        - from_dict() and to_dict() methods
    """
