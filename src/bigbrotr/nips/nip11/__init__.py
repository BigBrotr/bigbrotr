"""NIP-11 Relay Information Document models.

Implements [NIP-11](https://github.com/nostr-protocol/nips/blob/master/11.md)
-- fetching, parsing, and validation of relay information documents.
Raw JSON responses are sanitized through ``parse()`` methods and validated
into typed, frozen Pydantic models. Invalid fields or wrong types are
silently dropped to handle non-conformant relays.

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

Note:
    NIP-11 results are stored as
    [MetadataType.NIP11_INFO][bigbrotr.models.metadata.MetadataType] records
    in the database via
    [Nip11.to_relay_metadata_tuple][bigbrotr.nips.nip11.nip11.Nip11.to_relay_metadata_tuple].

See Also:
    [bigbrotr.models.metadata.MetadataType][bigbrotr.models.metadata.MetadataType]:
        The ``NIP11_INFO`` variant that tags these records.
    [bigbrotr.models.metadata.Metadata][bigbrotr.models.metadata.Metadata]:
        Content-addressed wrapper for NIP-11 payloads.
    [bigbrotr.nips.nip66][bigbrotr.nips.nip66]: Companion NIP-66 monitoring
        module that collects health metrics alongside NIP-11 info.
    [bigbrotr.services.monitor.Monitor][bigbrotr.services.monitor.Monitor]:
        Service that invokes [Nip11.create][bigbrotr.nips.nip11.nip11.Nip11.create]
        during health check cycles.
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
