"""
NIP-11 info operation log model.

Records whether a [NIP-11](https://github.com/nostr-protocol/nips/blob/master/11.md)
HTTP info fetch succeeded or failed, with an error reason string when the
operation was unsuccessful.

See Also:
    [bigbrotr.nips.base.BaseLogs][bigbrotr.nips.base.BaseLogs]: Base class
        providing success/reason semantic validation.
    [bigbrotr.nips.nip11.info.Nip11InfoMetadata][bigbrotr.nips.nip11.info.Nip11InfoMetadata]:
        Container that pairs fetch data with this log model.
"""

from __future__ import annotations

from bigbrotr.nips.base import BaseLogs


class Nip11InfoLogs(BaseLogs):
    """Log record for a NIP-11 relay information document retrieval.

    Inherits success/reason validation from
    [BaseLogs][bigbrotr.nips.base.BaseLogs]:

    * ``success=True`` requires ``reason=None``.
    * ``success=False`` requires a non-None ``reason`` string.

    Note:
        Common failure reasons include HTTP errors (non-200 status),
        invalid ``Content-Type`` headers, oversized responses, JSON parse
        failures, SSL certificate errors, and connection timeouts.

    See Also:
        [bigbrotr.nips.nip11.info.Nip11InfoMetadata][bigbrotr.nips.nip11.info.Nip11InfoMetadata]:
            Container that pairs this log with
            [Nip11InfoData][bigbrotr.nips.nip11.data.Nip11InfoData].
    """
