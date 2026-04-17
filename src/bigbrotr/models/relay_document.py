"""
Junction model linking a [Relay][bigbrotr.models.relay.Relay] to a
[Document][bigbrotr.models.document.Document] record.

Maps to the ``relay_document`` table, representing a time-series snapshot
that associates a relay with a specific stored document. Document records
are deduplicated via content-addressed hashing (SHA-256 computed in Python).
The database uses the ``relay_document_insert_cascade`` stored procedure
to atomically insert the relay, document, and junction record in a single call.

See Also:
    [bigbrotr.models.relay][]: The [Relay][bigbrotr.models.relay.Relay] model
        wrapped by this junction.
    [bigbrotr.models.document][]: The [Document][bigbrotr.models.document.Document]
        model wrapped by this junction.
    [bigbrotr.models.event_relay][]: Analogous junction model linking a
        [Relay][bigbrotr.models.relay.Relay] to an
        [Event][bigbrotr.models.event.Event].
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import NamedTuple

from ._validation import validate_instance, validate_timestamp
from .document import Document
from .relay import Relay


class RelayDocumentDbParams(NamedTuple):
    """Positional parameters for the relay-document junction insert procedure.

    Produced by
    [RelayDocument.to_db_params()][bigbrotr.models.relay_document.RelayDocument.to_db_params]
    and consumed by the ``relay_document_insert_cascade`` stored procedure
    in PostgreSQL.

    Attributes:
        relay_url: Relay WebSocket URL (from [RelayDbParams][bigbrotr.models.relay.RelayDbParams]).
        relay_network: Network type string (e.g., ``"clearnet"``, ``"tor"``).
        relay_stored_at: Unix timestamp when the relay entered the canonical stored relay pool.
        document_id: SHA-256 content hash (32 bytes,
            from [DocumentDbParams][bigbrotr.models.document.DocumentDbParams]).
        role: Document role identifier. Built-in callers typically
            use [MetadataType][bigbrotr.models.document.MetadataType], but
            arbitrary non-empty strings are accepted.
        document_data: Canonical JSON string for JSONB storage.
        associated_at: Unix timestamp when the document became associated with the relay.

    See Also:
        [RelayDocument][bigbrotr.models.relay_document.RelayDocument]: The model that
            produces these parameters.
        [RelayDbParams][bigbrotr.models.relay.RelayDbParams]: Source of the relay fields.
        [DocumentDbParams][bigbrotr.models.document.DocumentDbParams]: Source of the
            document fields.
    """

    relay_url: str
    relay_network: str
    relay_stored_at: int
    document_id: bytes
    role: str
    document_data: str
    associated_at: int


@dataclass(frozen=True, slots=True)
class RelayDocument:
    """Immutable junction linking a [Relay][bigbrotr.models.relay.Relay] to a
    [Document][bigbrotr.models.document.Document] record.

    The document role identifier is carried by the
    [Document][bigbrotr.models.document.Document] object and stored on both the
    ``document`` table (as part of the composite PK) and the ``relay_document``
    junction table (as part of the compound FK) for type-filtered queries.

    Attributes:
        relay: The [Relay][bigbrotr.models.relay.Relay] this document belongs to.
        document: The [Document][bigbrotr.models.document.Document] record
            (with type and content hash).
        associated_at: Unix timestamp when the document became associated with the relay
            (defaults to now).

    Examples:
        ```python
        relay = Relay("wss://relay.damus.io")
        document = Document(type=MetadataType.NIP11_INFO, data={"name": "Damus"})
        rd = RelayDocument(relay=relay, document=document)
        rd.associated_at      # Auto-set to current time
        params = rd.to_db_params()
        params.relay_url      # 'wss://relay.damus.io'
        params.role           # MetadataType.NIP11_INFO
        ```

    Note:
        The ``role`` exists on both the ``document`` table (composite
        PK ``(id, type)``) and the ``relay_document`` junction table
        (compound FK ``(document_id, role)``). This enforces referential
        integrity at the type level and enables efficient type-filtered queries
        (e.g., "latest NIP-11 info for all relays") without joining through
        the ``document`` table.

    See Also:
        [Relay][bigbrotr.models.relay.Relay]: The relay half of this junction.
        [Document][bigbrotr.models.document.Document]: The document half of this
            junction.
        [MetadataType][bigbrotr.models.document.MetadataType]: Built-in catalog
            of metadata classifications used by the current application.
        [RelayDocumentDbParams][bigbrotr.models.relay_document.RelayDocumentDbParams]:
            Database parameter container produced by
            [to_db_params()][bigbrotr.models.relay_document.RelayDocument.to_db_params].
        [EventRelay][bigbrotr.models.event_relay.EventRelay]: Analogous junction
            model for event-to-relay associations.
    """

    relay: Relay
    document: Document
    associated_at: int = field(default_factory=lambda: int(time()))
    _db_params: RelayDocumentDbParams = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
        hash=False,  # type: ignore[assignment]  # mypy expects bool literal, field() accepts it at runtime
    )

    def __post_init__(self) -> None:
        """Validate field types and compute database parameters (fail-fast)."""
        validate_instance(self.relay, Relay, "relay")
        validate_instance(self.document, Document, "document")
        validate_timestamp(self.associated_at, "associated_at")
        object.__setattr__(self, "_db_params", self._compute_db_params())

    def _compute_db_params(self) -> RelayDocumentDbParams:
        """Compute positional parameters for the cascade insert procedure.

        Merges the [RelayDbParams][bigbrotr.models.relay.RelayDbParams] and
        [DocumentDbParams][bigbrotr.models.document.DocumentDbParams] from the
        contained models with the junction ``associated_at`` timestamp and
        ``role`` into a single flat tuple.

        Returns:
            [RelayDocumentDbParams][bigbrotr.models.relay_document.RelayDocumentDbParams]
            combining relay, document, and junction fields.
        """
        r = self.relay.to_db_params()
        d = self.document.to_db_params()
        return RelayDocumentDbParams(
            relay_url=r.url,
            relay_network=r.network,
            relay_stored_at=r.stored_at,
            document_id=d.id,
            role=d.type,
            document_data=d.data,
            associated_at=self.associated_at,
        )

    def to_db_params(self) -> RelayDocumentDbParams:
        """Return cached positional parameters for the cascade insert procedure.

        Returns:
            [RelayDocumentDbParams][bigbrotr.models.relay_document.RelayDocumentDbParams]
            combining relay, document, and junction fields.
        """
        return self._db_params
