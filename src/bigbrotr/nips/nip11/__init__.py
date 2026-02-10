"""NIP-11 Relay Information Document models.

Implements fetching, parsing, and validation of relay information documents
as defined by NIP-11. Raw JSON responses are sanitized through `parse()`
methods and validated into typed, frozen Pydantic models. Invalid fields
or wrong types are silently dropped to handle non-conformant relays.

See: https://github.com/nostr-protocol/nips/blob/master/11.md

Model hierarchy:

```text
Nip11                                    Top-level container
+-- relay: Relay                         Source relay reference
+-- generated_at: int                    Unix timestamp of fetch
+-- fetch_metadata: Nip11InfoMetadata   Data + logs container
    +-- data: Nip11FetchData             Parsed NIP-11 document
    |   +-- name, description, banner, icon, pubkey, ...
    |   +-- supported_nips: list[int]
    |   +-- limitation: Nip11FetchDataLimitation
    |   +-- retention: list[Nip11FetchDataRetentionEntry]
    |   +-- fees: Nip11FetchDataFees
    |       +-- admission / subscription / publication
    |           +-- list[Nip11FetchDataFeeEntry]
    +-- logs: Nip11FetchLogs             Fetch result status
        +-- success: bool
        +-- reason: str | None
```
"""

from .data import (
    KindRange,
    Nip11FetchData,
    Nip11FetchDataFeeEntry,
    Nip11FetchDataFees,
    Nip11FetchDataLimitation,
    Nip11FetchDataRetentionEntry,
)
from .fetch import Nip11InfoMetadata
from .logs import Nip11FetchLogs
from .nip11 import Nip11, RelayNip11MetadataTuple


__all__ = [
    "KindRange",
    "Nip11",
    "Nip11FetchData",
    "Nip11FetchDataFeeEntry",
    "Nip11FetchDataFees",
    "Nip11FetchDataLimitation",
    "Nip11FetchDataRetentionEntry",
    "Nip11FetchLogs",
    "Nip11InfoMetadata",
    "RelayNip11MetadataTuple",
]
