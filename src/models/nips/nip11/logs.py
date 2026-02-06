"""
NIP-11 fetch operation log model.

Records whether a NIP-11 HTTP fetch succeeded or failed, with an
error reason string when the operation was unsuccessful.
"""

from __future__ import annotations

from models.nips.base import BaseLogs


class Nip11FetchLogs(BaseLogs):
    """Log record for a NIP-11 relay information document fetch.

    Inherits success/reason validation from ``BaseLogs``:

    * ``success=True`` requires ``reason=None``.
    * ``success=False`` requires a non-None ``reason`` string.
    """
