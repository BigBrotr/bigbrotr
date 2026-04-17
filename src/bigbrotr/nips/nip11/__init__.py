"""NIP-11 Relay Information Document models.

Implements [NIP-11](https://github.com/nostr-protocol/nips/blob/master/11.md)
-- retrieval, parsing, and validation of relay information documents.
Raw JSON responses are sanitized through ``parse()`` methods and validated
into typed, frozen Pydantic models. Invalid fields or wrong types are
silently dropped to handle non-conformant relays.

Model hierarchy:

```text
Nip11                                    Top-level container
+-- relay: Relay                         Source relay reference
+-- generated_at: int                    Unix timestamp
+-- info: Nip11InfoMetadata              Data + logs container
    +-- data: Nip11InfoData              Parsed NIP-11 document
    |   +-- name, description, banner, icon, pubkey, ...
    |   +-- supported_nips: list[int]
    |   +-- limitation: Nip11InfoDataLimitation
    |   +-- retention: list[Nip11InfoDataRetentionEntry]
    |   +-- fees: Nip11InfoDataFees
    |       +-- admission / subscription / publication
    |           +-- list[Nip11InfoDataFeeEntry]
    +-- logs: Nip11InfoLogs              Operation result status
        +-- success: bool
        +-- reason: str | None
```

Note:
    NIP-11 results are stored as
    [DocumentType.NIP11_INFO][bigbrotr.models.document.DocumentType] records
    in the database via
    [Nip11.to_relay_document_tuple][bigbrotr.nips.nip11.nip11.Nip11.to_relay_document_tuple].

See Also:
    [bigbrotr.models.document.DocumentType][bigbrotr.models.document.DocumentType]:
        The ``NIP11_INFO`` variant that tags these records.
    [bigbrotr.models.document.Document][bigbrotr.models.document.Document]:
        Content-addressed wrapper for NIP-11 payloads.
    [bigbrotr.nips.nip66][bigbrotr.nips.nip66]: Companion NIP-66 monitoring
        module that collects health metrics alongside NIP-11 info.
    [bigbrotr.services.monitor.Monitor][bigbrotr.services.monitor.Monitor]:
        Service that invokes [Nip11.fetch][bigbrotr.nips.nip11.nip11.Nip11.fetch]
        during health check cycles.
"""

from .data import (
    KindRange,
    Nip11InfoData,
    Nip11InfoDataFeeEntry,
    Nip11InfoDataFees,
    Nip11InfoDataLimitation,
    Nip11InfoDataRetentionEntry,
)
from .info import Nip11InfoMetadata
from .logs import Nip11InfoLogs
from .nip11 import (
    Nip11,
    Nip11Dependencies,
    Nip11Options,
    Nip11Selection,
    RelayNip11DocumentTuple,
)


__all__ = [
    "KindRange",
    "Nip11",
    "Nip11Dependencies",
    "Nip11InfoData",
    "Nip11InfoDataFeeEntry",
    "Nip11InfoDataFees",
    "Nip11InfoDataLimitation",
    "Nip11InfoDataRetentionEntry",
    "Nip11InfoLogs",
    "Nip11InfoMetadata",
    "Nip11Options",
    "Nip11Selection",
    "RelayNip11DocumentTuple",
]
