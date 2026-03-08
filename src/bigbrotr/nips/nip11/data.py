"""
NIP-11 relay information data models.

Defines the typed Pydantic models that represent the fields of a
[NIP-11](https://github.com/nostr-protocol/nips/blob/master/11.md) relay
information document, including server limitations, retention policies,
and fee schedules.

Note:
    All data classes extend [BaseData][bigbrotr.nips.base.BaseData] and use
    declarative [FieldSpec][bigbrotr.nips.parsing.FieldSpec] parsing.
    Complex nested structures (limitation, retention, fees) override
    ``parse()`` with custom logic while still leveraging the base mechanism
    for flat fields.

See Also:
    [bigbrotr.nips.nip11.info.Nip11InfoMetadata][bigbrotr.nips.nip11.info.Nip11InfoMetadata]:
        Container that pairs these data models with fetch logs.
    [bigbrotr.nips.nip11.nip11.Nip11][bigbrotr.nips.nip11.nip11.Nip11]:
        Top-level model that wraps the fetch result.
    [bigbrotr.nips.base.BaseData][bigbrotr.nips.base.BaseData]: Base class
        providing the ``parse()`` / ``from_dict()`` / ``to_dict()`` interface.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import ConfigDict, Field, StrictBool, StrictInt

from bigbrotr.nips.base import BaseData
from bigbrotr.nips.parsing import FieldSpec, parse_fields


KindRange = tuple[StrictInt, StrictInt]


class Nip11InfoDataLimitation(BaseData):
    """Server-imposed limitations advertised in the NIP-11 document.

    All fields are optional; relays may omit any or all of them.

    See Also:
        [Nip11InfoData][bigbrotr.nips.nip11.data.Nip11InfoData]: Parent
            model that contains this as the ``limitation`` field.
    """

    max_message_length: StrictInt | None = Field(
        default=None, description="Maximum WebSocket message length in bytes"
    )
    max_subscriptions: StrictInt | None = Field(
        default=None, description="Maximum concurrent subscriptions"
    )
    max_limit: StrictInt | None = Field(
        default=None, description="Maximum limit value in REQ filters"
    )
    max_subid_length: StrictInt | None = Field(
        default=None, description="Maximum subscription ID length"
    )
    max_event_tags: StrictInt | None = Field(
        default=None, description="Maximum number of tags per event"
    )
    max_content_length: StrictInt | None = Field(
        default=None, description="Maximum event content length"
    )
    min_pow_difficulty: StrictInt | None = Field(
        default=None, description="Minimum proof-of-work difficulty required"
    )
    auth_required: StrictBool | None = Field(
        default=None, description="Whether NIP-42 authentication is required"
    )
    payment_required: StrictBool | None = Field(
        default=None, description="Whether payment is required"
    )
    restricted_writes: StrictBool | None = Field(
        default=None, description="Whether writes are restricted"
    )
    created_at_lower_limit: StrictInt | None = Field(
        default=None, description="Oldest allowed created_at timestamp"
    )
    created_at_upper_limit: StrictInt | None = Field(
        default=None, description="Newest allowed created_at timestamp"
    )
    default_limit: StrictInt | None = Field(
        default=None, description="Default limit when not specified in REQ"
    )

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


class Nip11InfoDataRetentionEntry(BaseData):
    """Single retention policy entry from a NIP-11 document.

    The ``kinds`` field can contain plain integers or ``[start, end]``
    range pairs, requiring custom parsing logic in ``parse()``.

    Note:
        The ``parse()`` override handles the mixed ``int | [int, int]``
        format specified by NIP-11. Lists are converted to tuples for
        immutability, and ``to_dict()`` uses ``mode="json"`` to convert
        tuples back to lists for JSON serialization.

    See Also:
        [Nip11InfoData][bigbrotr.nips.nip11.data.Nip11InfoData]: Parent
            model that contains these as the ``retention`` list.
    """

    kinds: list[StrictInt | KindRange] | None = Field(
        default=None, description="Event kinds this policy applies to"
    )
    time: StrictInt | None = Field(default=None, description="Retention time in seconds")
    count: StrictInt | None = Field(default=None, description="Maximum events to retain")

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


class Nip11InfoDataFeeEntry(BaseData):
    """Single fee entry (admission, subscription, or publication).

    See Also:
        [Nip11InfoDataFees][bigbrotr.nips.nip11.data.Nip11InfoDataFees]:
            Parent model that groups fee entries by category.
    """

    amount: StrictInt | None = Field(default=None, description="Fee amount")
    unit: str | None = Field(default=None, description="Fee currency unit")
    period: StrictInt | None = Field(default=None, description="Fee period in seconds")
    kinds: list[StrictInt] | None = Field(
        default=None, description="Event kinds this fee applies to"
    )

    _FIELD_SPEC: ClassVar[FieldSpec] = FieldSpec(
        int_fields=frozenset({"amount", "period"}),
        str_fields=frozenset({"unit"}),
        int_list_fields=frozenset({"kinds"}),
    )


class Nip11InfoDataFees(BaseData):
    """Fee schedule categories from a NIP-11 document.

    Contains nested lists of
    [Nip11InfoDataFeeEntry][bigbrotr.nips.nip11.data.Nip11InfoDataFeeEntry]
    objects for admission, subscription, and publication fees.

    See Also:
        [Nip11InfoData][bigbrotr.nips.nip11.data.Nip11InfoData]: Parent
            model that contains this as the ``fees`` field.
    """

    admission: list[Nip11InfoDataFeeEntry] | None = Field(
        default=None, description="Admission fee entries"
    )
    subscription: list[Nip11InfoDataFeeEntry] | None = Field(
        default=None, description="Subscription fee entries"
    )
    publication: list[Nip11InfoDataFeeEntry] | None = Field(
        default=None, description="Publication fee entries"
    )

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
                entries = [Nip11InfoDataFeeEntry.parse(e) for e in data[key]]
                entries = [e for e in entries if e]
                if entries:
                    result[key] = entries
        return result


class Nip11InfoData(BaseData):
    """Complete NIP-11 relay information document.

    Overrides ``parse()`` to handle nested objects (limitation, retention,
    fees) and ``to_dict()`` to use ``by_alias=True`` for the ``self``
    field, which maps to ``self_pubkey`` internally.

    Note:
        The NIP-11 ``self`` field is a reserved Python keyword, so it is
        mapped to ``self_pubkey`` with a Pydantic alias. The ``to_dict()``
        method uses ``by_alias=True`` to ensure the JSON output uses the
        correct ``self`` key name as specified by the NIP.

    See Also:
        [Nip11InfoMetadata][bigbrotr.nips.nip11.info.Nip11InfoMetadata]:
            Container that wraps this data model with fetch logs.
        [Nip11InfoDataLimitation][bigbrotr.nips.nip11.data.Nip11InfoDataLimitation]:
            Nested limitation sub-model.
        [Nip11InfoDataFees][bigbrotr.nips.nip11.data.Nip11InfoDataFees]:
            Nested fee schedule sub-model.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    name: str | None = Field(default=None, description="Relay display name")
    description: str | None = Field(default=None, description="Relay description")
    banner: str | None = Field(default=None, description="Banner image URL")
    icon: str | None = Field(default=None, description="Icon image URL")
    pubkey: str | None = Field(default=None, description="Relay operator public key (hex)")
    self_pubkey: str | None = Field(
        default=None, alias="self", description="Relay's own public key"
    )
    contact: str | None = Field(default=None, description="Relay operator contact")
    software: str | None = Field(default=None, description="Relay software identifier")
    version: str | None = Field(default=None, description="Relay software version")

    privacy_policy: str | None = Field(default=None, description="Privacy policy URL")
    terms_of_service: str | None = Field(default=None, description="Terms of service URL")
    posting_policy: str | None = Field(default=None, description="Posting policy URL")
    payments_url: str | None = Field(default=None, description="Payments URL")

    supported_nips: list[StrictInt] | None = Field(
        default=None, description="List of supported NIP numbers"
    )
    limitation: Nip11InfoDataLimitation = Field(
        default_factory=Nip11InfoDataLimitation, description="Server-imposed limitations"
    )
    retention: list[Nip11InfoDataRetentionEntry] | None = Field(
        default=None, description="Event retention policies"
    )
    fees: Nip11InfoDataFees = Field(default_factory=Nip11InfoDataFees, description="Fee schedule")

    relay_countries: list[str] | None = Field(
        default=None, description="Countries where the relay operates"
    )
    language_tags: list[str] | None = Field(default=None, description="Supported language tags")
    tags: list[str] | None = Field(default=None, description="Arbitrary relay tags")

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
            limitation = Nip11InfoDataLimitation.parse(data["limitation"])
            if limitation:
                result["limitation"] = limitation

        if "retention" in data and isinstance(data["retention"], list):
            entries = [Nip11InfoDataRetentionEntry.parse(e) for e in data["retention"]]
            entries = [e for e in entries if e]
            if entries:
                result["retention"] = entries

        if "fees" in data:
            fees = Nip11InfoDataFees.parse(data["fees"])
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
        result = parse_fields(data, cls._FIELD_SPEC)

        if "supported_nips" in data and isinstance(data["supported_nips"], list):
            nips = [
                n for n in data["supported_nips"] if isinstance(n, int) and not isinstance(n, bool)
            ]
            if nips:
                result["supported_nips"] = sorted(set(nips))

        result.update(cls._parse_sub_objects(data))
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary using field aliases (``self`` instead of ``self_pubkey``)."""
        return self.model_dump(exclude_none=True, by_alias=True, mode="json")
