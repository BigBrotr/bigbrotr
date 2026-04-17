"""
Content-addressed documents with SHA-256 deduplication.

Stores arbitrary JSON-compatible data with a type classification
([MetadataType][bigbrotr.models.document.MetadataType]). A deterministic
content hash is computed from the canonical JSON representation of the
data, enabling content-addressed deduplication in PostgreSQL.

The [Document][bigbrotr.models.document.Document] class is agnostic about
the internal structure of ``data``; higher-level models in
[bigbrotr.nips.nip11][] and [bigbrotr.nips.nip66][] define their own
conventions for what goes inside it.

See Also:
    [bigbrotr.models.relay_metadata][]: Junction model linking a
        [Relay][bigbrotr.models.relay.Relay] to a
        [Document][bigbrotr.models.document.Document] record.
    [bigbrotr.nips.nip11][]: Produces ``nip11_info``-typed metadata from
        relay information documents.
    [bigbrotr.nips.nip66][]: Produces ``nip66_*``-typed metadata from
        health check results (RTT, SSL, DNS, Geo, Net, HTTP).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, NamedTuple


if TYPE_CHECKING:
    from collections.abc import Mapping

from ._validation import (
    deep_freeze,
    normalize_json_data,
    validate_mapping,
    validate_str_not_empty,
)


class MetadataType(StrEnum):
    """Document type identifiers stored in the ``document.type`` column.

    Each value corresponds to a specific data source or monitoring test
    performed by the [Monitor][bigbrotr.services.monitor.Monitor] service.

    Attributes:
        NIP11_INFO: NIP-11 relay information document fetched via HTTP(S).
        NIP66_RTT: NIP-66 round-trip time measurements (WebSocket latency).
        NIP66_SSL: NIP-66 SSL/TLS certificate information (expiry, issuer, chain).
        NIP66_GEO: NIP-66 geolocation data (country, city, coordinates).
        NIP66_NET: NIP-66 network and ASN information (provider, AS number).
        NIP66_DNS: NIP-66 DNS resolution data (A/AAAA records, response times).
        NIP66_HTTP: NIP-66 HTTP header information (server, content-type, CORS).

    See Also:
        [Document][bigbrotr.models.document.Document]: The content-addressed container
            that carries a [MetadataType][bigbrotr.models.document.MetadataType] alongside
            its data.
        [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]: Junction model
            linking a relay to a stored document record.
    """

    NIP11_INFO = "nip11_info"
    NIP66_RTT = "nip66_rtt"
    NIP66_SSL = "nip66_ssl"
    NIP66_GEO = "nip66_geo"
    NIP66_NET = "nip66_net"
    NIP66_DNS = "nip66_dns"
    NIP66_HTTP = "nip66_http"


class DocumentDbParams(NamedTuple):
    """Positional parameters for the document database insert procedure.

    Produced by [Document.to_db_params()][bigbrotr.models.document.Document.to_db_params]
    and consumed by the ``document_insert`` stored procedure in PostgreSQL.

    Attributes:
        id: SHA-256 content hash (32 bytes), part of composite PK ``(id, type)``.
        type: Document type identifier, part of composite PK ``(id, type)``.
            Built-in callers typically use
            [MetadataType][bigbrotr.models.document.MetadataType], but arbitrary
            non-empty strings are accepted.
        data: Canonical JSON string for PostgreSQL JSONB storage.

    See Also:
        [Document][bigbrotr.models.document.Document]: The model that produces these
            parameters.
    """

    id: bytes
    type: str
    data: str


@dataclass(frozen=True, slots=True)
class Document:
    """Immutable document with deterministic content hashing.

    On construction, the ``data`` dict is validated for strict JSON
    compatibility, normalized only for deterministic ordering, and a
    canonical JSON string is produced. The SHA-256 hash of that string
    serves as a content-addressed identifier for deduplication.

    The hash is derived from ``data`` only -- ``type`` is not included in
    the hash computation but is part of the composite primary key
    ``(id, type)`` in the database.

    Attributes:
        type: The metadata classification. Built-in callers use the
            [MetadataType][bigbrotr.models.document.MetadataType] catalog, but
            arbitrary non-empty string IDs are accepted for extensibility.
        data: Deterministically normalized JSON-compatible dictionary.

    Examples:
        ```python
        meta = Document(type=MetadataType.NIP11_INFO, data={"name": "My Relay"})
        meta.content_hash    # 32-byte SHA-256 digest
        meta.canonical_json  # '{"name":"My Relay"}'
        meta.to_db_params()  # DocumentDbParams(...)
        ```

        Identical data always produces the same hash (content-addressed):

        ```python
        m1 = Document(type=MetadataType.NIP11_INFO, data={"b": 2, "a": 1})
        m2 = Document(type=MetadataType.NIP11_INFO, data={"a": 1, "b": 2})
        m1.content_hash == m2.content_hash  # True
        ```

    Note:
        The content hash is derived from ``data`` alone. The ``type`` is stored
        alongside the hash on the ``document`` table with composite primary key
        ``(id, type)``, ensuring each document is tied to exactly one type.
        The ``relay_metadata`` junction table references the stored document
        via a compound foreign key on ``(metadata_id, metadata_type)``.

        Computed fields (``_canonical_json``, ``_content_hash``, ``_db_params``)
        are set via ``object.__setattr__`` in ``__post_init__`` because the
        dataclass is frozen.

    Warning:
        String data containing null bytes (``\\x00``) will raise ``ValueError``
        during validation. PostgreSQL TEXT and JSONB columns do not support null
        bytes, and unsupported JSON values are rejected before hashing.

    See Also:
        [MetadataType][bigbrotr.models.document.MetadataType]: Enum of supported
            metadata classifications.
        [DocumentDbParams][bigbrotr.models.document.DocumentDbParams]: Database
            parameter container produced by
            [to_db_params()][bigbrotr.models.document.Document.to_db_params].
        [RelayMetadata][bigbrotr.models.relay_metadata.RelayMetadata]: Junction
            linking a [Relay][bigbrotr.models.relay.Relay] to this document record.
    """

    type: str
    data: Mapping[str, Any] = field(default_factory=dict)

    _canonical_json: str = field(default="", init=False, repr=False, compare=False)
    _content_hash: bytes = field(default=b"", init=False, repr=False, compare=False)
    _db_params: DocumentDbParams = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
        hash=False,  # type: ignore[assignment]  # mypy expects bool literal, field() accepts it at runtime
    )

    def __post_init__(self) -> None:
        """Validate, normalize deterministically, and hash the data dictionary."""
        object.__setattr__(self, "type", _normalize_metadata_type(self.type))
        validate_mapping(self.data, "data")
        normalized = normalize_json_data(self.data, "data")

        canonical = json.dumps(
            normalized,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        object.__setattr__(self, "_canonical_json", canonical)

        content_hash = hashlib.sha256(canonical.encode("utf-8")).digest()
        object.__setattr__(self, "_content_hash", content_hash)

        object.__setattr__(self, "data", deep_freeze(normalized))
        object.__setattr__(self, "_db_params", self._compute_db_params())

    @property
    def content_hash(self) -> bytes:
        """SHA-256 digest of the canonical JSON representation.

        Computed once at construction time. Identical semantic data always
        produces the same 32-byte hash, enabling content-addressed
        deduplication in the ``document`` table.

        Returns:
            32-byte SHA-256 digest suitable for PostgreSQL BYTEA columns.

        See Also:
            [canonical_json][bigbrotr.models.document.Document.canonical_json]:
                The JSON string from which this hash is derived.
        """
        return self._content_hash

    @property
    def canonical_json(self) -> str:
        """Canonical JSON string used for hashing and JSONB storage.

        Format: sorted keys, compact separators, UTF-8 encoding.

        Returns:
            Deterministic JSON string of the normalized value.
        """
        return self._canonical_json

    def _compute_db_params(self) -> DocumentDbParams:
        """Compute positional parameters for the database insert procedure.

        Called once during ``__post_init__`` to populate the ``_db_params``
        cache. All subsequent access goes through
        [to_db_params()][bigbrotr.models.document.Document.to_db_params].

        Returns:
            [DocumentDbParams][bigbrotr.models.document.DocumentDbParams] with
            the content hash as ``id``, the canonical JSON as ``data``,
            and the metadata type.
        """
        return DocumentDbParams(
            id=self._content_hash,
            type=self.type,
            data=self._canonical_json,
        )

    def to_db_params(self) -> DocumentDbParams:
        """Return cached positional parameters for the database insert procedure.

        The result is computed once during construction and cached for the
        lifetime of the (frozen) instance.

        Returns:
            [DocumentDbParams][bigbrotr.models.document.DocumentDbParams] with
            the content hash as ``id``, the canonical JSON as ``data``,
            and the metadata type.
        """
        return self._db_params


def _normalize_metadata_type(value: str | StrEnum) -> str:
    """Normalize enum-backed or plain-string metadata identifiers."""
    normalized = value.value if isinstance(value, StrEnum) else value
    validate_str_not_empty(normalized, "type")
    return normalized
