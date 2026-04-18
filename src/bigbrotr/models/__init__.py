"""Pure frozen dataclasses with zero I/O for the shared BigBrotr data model.

The models layer is the foundation of the diamond DAG. It has **no dependencies**
on any other BigBrotr package -- only the Python standard library. Every model uses
``@dataclass(frozen=True, slots=True)`` for immutability and memory efficiency.

Database parameter containers use ``NamedTuple`` and are cached in ``__post_init__``
to avoid repeated conversions. All validation happens in ``__post_init__`` so
invalid instances never escape the constructor.

NIP models (``Nip11``, ``Nip66``) are in the separate ``bigbrotr.nips`` package.

Public model families:
    Relay: Validated relay URL plus derived network classification.
    Event: Immutable archived event payload and identity.
    EventObservation: Observation history linking an event to the relay where
        it was seen.
    Document: Content-addressed stored document for NIP-11, NIP-66, and other
        shared document families.
    RelayDocument: History table model linking a relay to a stored document and
        role.
    ServiceState: Shared service-owned state records used for cursors,
        checkpoints, and resumable background work.
    NetworkType: Enum classifying relay URLs into clearnet, Tor, I2P, Lokinet,
        local, or unknown.

Note:
    All models use ``object.__setattr__`` in ``__post_init__`` to set computed
    fields on frozen dataclasses. This is the standard workaround for frozen
    dataclass initialization and is safe because ``__post_init__`` runs during
    ``__init__`` before the instance is exposed to external code.

See Also:
    [bigbrotr.models.relay][]: Relay URL validation and network detection.
    [bigbrotr.models.event][]: Archived Nostr event model.
    [bigbrotr.models.event_observation][]: Event-to-relay observation history.
    [bigbrotr.models.document][]: Content-addressed document storage.
    [bigbrotr.models.relay_document][]: Relay-to-document history model.
    [bigbrotr.models.service_state][]: Shared service-state types.
    [bigbrotr.models.constants][]: Shared constants and enumerations.
    [bigbrotr.nips][]: NIP-aware protocol package with runtime I/O,
        static capability registry, and builder/data helpers.
"""

from .constants import EVENT_KIND_MAX, EventKind, NetworkType, ServiceName
from .document import Document, DocumentType
from .event import Event
from .event_observation import EventObservation
from .relay import Relay
from .relay_document import RelayDocument
from .service_state import ServiceState, ServiceStateDbParams, ServiceStateType


__all__ = [
    "EVENT_KIND_MAX",
    "Document",
    "DocumentType",
    "Event",
    "EventKind",
    "EventObservation",
    "NetworkType",
    "Relay",
    "RelayDocument",
    "ServiceName",
    "ServiceState",
    "ServiceStateDbParams",
    "ServiceStateType",
]
