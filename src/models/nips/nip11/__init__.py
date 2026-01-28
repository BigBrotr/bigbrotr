"""
NIP-11 Relay Information Document.

Fetches and parses relay information documents per NIP-11 specification.
Raw JSON is sanitized via parse() then validated into typed frozen Pydantic models.
Invalid fields or wrong types are silently dropped (not raised as errors).

See: https://github.com/nostr-protocol/nips/blob/master/11.md

Model Hierarchy::

    Nip11                                    # Main class with relay reference
    ├── relay: Relay                         # Source relay
    ├── generated_at: int                    # Unix timestamp of fetch
    └── fetch_metadata: Nip11FetchMetadata   # Container for data + logs
        ├── data: Nip11FetchData             # NIP-11 document fields
        │   ├── name: str | None
        │   ├── description: str | None
        │   ├── banner: str | None
        │   ├── icon: str | None
        │   ├── pubkey: str | None
        │   ├── self_pubkey: str | None      # JSON alias: "self"
        │   ├── contact: str | None
        │   ├── software: str | None
        │   ├── version: str | None
        │   ├── privacy_policy: str | None
        │   ├── terms_of_service: str | None
        │   ├── posting_policy: str | None
        │   ├── payments_url: str | None
        │   ├── supported_nips: list[int] | None
        │   ├── limitation: Nip11FetchDataLimitation
        │   │   ├── max_message_length: int | None
        │   │   ├── max_subscriptions: int | None
        │   │   ├── max_limit: int | None
        │   │   ├── max_subid_length: int | None
        │   │   ├── max_event_tags: int | None
        │   │   ├── max_content_length: int | None
        │   │   ├── min_pow_difficulty: int | None
        │   │   ├── auth_required: bool | None
        │   │   ├── payment_required: bool | None
        │   │   ├── restricted_writes: bool | None
        │   │   ├── created_at_lower_limit: int | None
        │   │   ├── created_at_upper_limit: int | None
        │   │   └── default_limit: int | None
        │   ├── retention: list[Nip11FetchDataRetentionEntry] | None
        │   │   └── Nip11FetchDataRetentionEntry
        │   │       ├── kinds: list[int | tuple[int, int]] | None
        │   │       ├── time: int | None
        │   │       └── count: int | None
        │   ├── fees: Nip11FetchDataFees
        │   │   ├── admission: list[Nip11FetchDataFeeEntry] | None
        │   │   ├── subscription: list[Nip11FetchDataFeeEntry] | None
        │   │   └── publication: list[Nip11FetchDataFeeEntry] | None
        │   │       └── Nip11FetchDataFeeEntry
        │   │           ├── amount: int | None
        │   │           ├── unit: str | None
        │   │           ├── period: int | None
        │   │           └── kinds: list[int] | None
        │   ├── relay_countries: list[str] | None
        │   ├── language_tags: list[str] | None
        │   └── tags: list[str] | None
        └── logs: Nip11FetchLogs             # Fetch operation result
            ├── success: bool                # True if fetch succeeded
            └── reason: str | None           # Error message (only when success=False)

Usage::

    from models.nips.nip11 import Nip11
    from models.relay import Relay

    # Fetch from relay (always returns Nip11, never None)
    relay = Relay("wss://relay.damus.io")
    nip11 = await Nip11.create(relay)

    # Check fetch status
    if nip11.fetch_metadata.logs.success:
        # Access data fields
        data = nip11.fetch_metadata.data
        print(f"Name: {data.name}")
        print(f"NIPs: {data.supported_nips}")
        print(f"Auth required: {data.limitation.auth_required}")
        print(f"Max message: {data.limitation.max_message_length}")
    else:
        # Handle failure
        print(f"Failed: {nip11.fetch_metadata.logs.reason}")

    # Convert for database storage
    metadata_list = nip11.to_relay_metadata_tuple()
    relay_metadata = metadata_list.nip11_fetch
"""

from .data import (
    KindRange,
    Nip11FetchData,
    Nip11FetchDataFeeEntry,
    Nip11FetchDataFees,
    Nip11FetchDataLimitation,
    Nip11FetchDataRetentionEntry,
)
from .fetch import Nip11FetchMetadata
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
    "Nip11FetchMetadata",
    "RelayNip11MetadataTuple",
]
