"""
NIP-11 relay information data models.

Defines the typed Pydantic models that represent the fields of a NIP-11
relay information document, including server limitations, retention policies,
and fee schedules.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import ConfigDict, Field, StrictBool, StrictInt

from bigbrotr.nips.base import BaseData
from bigbrotr.nips.parsing import FieldSpec


KindRange = tuple[StrictInt, StrictInt]


class Nip11FetchDataLimitation(BaseData):
    """Server-imposed limitations advertised in the NIP-11 document.

    All fields are optional; relays may omit any or all of them.
    """

    max_message_length: StrictInt | None = None
    max_subscriptions: StrictInt | None = None
    max_limit: StrictInt | None = None
    max_subid_length: StrictInt | None = None
    max_event_tags: StrictInt | None = None
    max_content_length: StrictInt | None = None
    min_pow_difficulty: StrictInt | None = None
    auth_required: StrictBool | None = None
    payment_required: StrictBool | None = None
    restricted_writes: StrictBool | None = None
    created_at_lower_limit: StrictInt | None = None
    created_at_upper_limit: StrictInt | None = None
    default_limit: StrictInt | None = None

    _FIELD_SPEC: ClassVar[FieldSpec] = FieldSpec(
        int_fields=frozenset(
            {
                "max_message_length",
                "max_subscriptions",
                "max_limit",
                "max_subid_length",
                "max_event_tags",
                "max_content_length",
                "min_pow_difficulty",
                "created_at_lower_limit",
                "created_at_upper_limit",
                "default_limit",
            }
        ),
        bool_fields=frozenset(
            {
                "auth_required",
                "payment_required",
                "restricted_writes",
            }
        ),
    )


class Nip11FetchDataRetentionEntry(BaseData):
    """Single retention policy entry from a NIP-11 document.

    The ``kinds`` field can contain plain integers or ``[start, end]``
    range pairs, requiring custom parsing logic in ``parse()``.
    """

    kinds: list[StrictInt | KindRange] | None = None
    time: StrictInt | None = None
    count: StrictInt | None = None

    @classmethod
    def parse(cls, data: Any) -> dict[str, Any]:
        """Parse a retention entry, handling mixed int/range kinds lists.

        Args:
            data: Raw dictionary for a single retention entry.

        Returns:
            Validated dictionary with ``kinds``, ``time``, and ``count``.
        """
        if not isinstance(data, dict):
            return {}
        result: dict[str, Any] = {}

        if "kinds" in data and isinstance(data["kinds"], list):
            kinds: list[int | tuple[int, int]] = []
            for item in data["kinds"]:
                if isinstance(item, int) and not isinstance(item, bool):
                    kinds.append(item)
                elif (
                    isinstance(item, list)
                    and len(item) == 2  # noqa: PLR2004 - [min, max] range pair
                    and isinstance(item[0], int)
                    and not isinstance(item[0], bool)
                    and isinstance(item[1], int)
                    and not isinstance(item[1], bool)
                ):
                    kinds.append((item[0], item[1]))
            if kinds:
                result["kinds"] = kinds

        for key in ("time", "count"):
            if key in data:
                value = data[key]
                if isinstance(value, int) and not isinstance(value, bool):
                    result[key] = value
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary, converting tuples to lists for JSON."""
        return self.model_dump(exclude_none=True, mode="json")


class Nip11FetchDataFeeEntry(BaseData):
    """Single fee entry (admission, subscription, or publication)."""

    amount: StrictInt | None = None
    unit: str | None = None
    period: StrictInt | None = None
    kinds: list[StrictInt] | None = None

    _FIELD_SPEC: ClassVar[FieldSpec] = FieldSpec(
        int_fields=frozenset({"amount", "period"}),
        str_fields=frozenset({"unit"}),
        int_list_fields=frozenset({"kinds"}),
    )


class Nip11FetchDataFees(BaseData):
    """Fee schedule categories from a NIP-11 document.

    Contains nested lists of ``Nip11FetchDataFeeEntry`` objects for
    admission, subscription, and publication fees.
    """

    admission: list[Nip11FetchDataFeeEntry] | None = None
    subscription: list[Nip11FetchDataFeeEntry] | None = None
    publication: list[Nip11FetchDataFeeEntry] | None = None

    @classmethod
    def parse(cls, data: Any) -> dict[str, Any]:
        """Parse fee schedule data with nested fee entry objects.

        Args:
            data: Raw dictionary containing fee category lists.

        Returns:
            Validated dictionary with non-empty fee entry lists.
        """
        if not isinstance(data, dict):
            return {}
        result: dict[str, Any] = {}
        for key in ("admission", "subscription", "publication"):
            if key in data and isinstance(data[key], list):
                entries = [Nip11FetchDataFeeEntry.parse(e) for e in data[key]]
                entries = [e for e in entries if e]
                if entries:
                    result[key] = entries
        return result


class Nip11FetchData(BaseData):
    """Complete NIP-11 relay information document.

    Overrides ``parse()`` to handle nested objects (limitation, retention,
    fees) and ``to_dict()`` to use ``by_alias=True`` for the ``self``
    field, which maps to ``self_pubkey`` internally.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    # Relay identification
    name: str | None = None
    description: str | None = None
    banner: str | None = None
    icon: str | None = None
    pubkey: str | None = None
    self_pubkey: str | None = Field(default=None, alias="self")
    contact: str | None = None
    software: str | None = None
    version: str | None = None

    # Policy URLs
    privacy_policy: str | None = None
    terms_of_service: str | None = None
    posting_policy: str | None = None
    payments_url: str | None = None

    # Capabilities
    supported_nips: list[StrictInt] | None = None
    limitation: Nip11FetchDataLimitation = Field(default_factory=Nip11FetchDataLimitation)
    retention: list[Nip11FetchDataRetentionEntry] | None = None
    fees: Nip11FetchDataFees = Field(default_factory=Nip11FetchDataFees)

    # Content filtering
    relay_countries: list[str] | None = None
    language_tags: list[str] | None = None
    tags: list[str] | None = None

    @property
    def self(self) -> str | None:
        """Relay's own public key from the NIP-11 ``self`` field."""
        return self.self_pubkey

    _FIELD_SPEC: ClassVar[FieldSpec] = FieldSpec(
        str_fields=frozenset(
            {
                "name",
                "description",
                "banner",
                "icon",
                "pubkey",
                "self",
                "contact",
                "software",
                "version",
                "privacy_policy",
                "terms_of_service",
                "posting_policy",
                "payments_url",
            }
        ),
        str_list_fields=frozenset(
            {
                "relay_countries",
                "language_tags",
                "tags",
            }
        ),
    )

    @staticmethod
    def _parse_sub_objects(data: dict[str, Any]) -> dict[str, Any]:
        """Parse nested limitation, retention, and fees sub-objects.

        Args:
            data: Raw dictionary from the relay HTTP response.

        Returns:
            Validated dictionary containing only non-empty sub-objects.
        """
        result: dict[str, Any] = {}

        if "limitation" in data:
            limitation = Nip11FetchDataLimitation.parse(data["limitation"])
            if limitation:
                result["limitation"] = limitation

        if "retention" in data and isinstance(data["retention"], list):
            entries = [Nip11FetchDataRetentionEntry.parse(e) for e in data["retention"]]
            entries = [e for e in entries if e]
            if entries:
                result["retention"] = entries

        if "fees" in data:
            fees = Nip11FetchDataFees.parse(data["fees"])
            if fees:
                result["fees"] = fees

        return result

    @classmethod
    def parse(cls, data: Any) -> dict[str, Any]:
        """Parse a complete NIP-11 document with nested sub-objects.

        Handles string fields, supported_nips list, and nested limitation,
        retention, and fees objects.

        Args:
            data: Raw dictionary from the relay HTTP response.

        Returns:
            Validated dictionary suitable for model construction.
        """
        if not isinstance(data, dict):
            return {}
        result: dict[str, Any] = {}

        for key in cls._FIELD_SPEC.str_fields:
            if key in data and isinstance(data[key], str):
                result[key] = data[key]

        if "supported_nips" in data and isinstance(data["supported_nips"], list):
            nips = [
                n for n in data["supported_nips"] if isinstance(n, int) and not isinstance(n, bool)
            ]
            if nips:
                result["supported_nips"] = nips

        result.update(cls._parse_sub_objects(data))

        for key in cls._FIELD_SPEC.str_list_fields:
            if key in data and isinstance(data[key], list):
                items = [s for s in data[key] if isinstance(s, str)]
                if items:
                    result[key] = items
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary using field aliases (``self`` instead of ``self_pubkey``)."""
        return self.model_dump(exclude_none=True, by_alias=True)
