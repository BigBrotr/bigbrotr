"""NIP-11 data models."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import ConfigDict, Field, StrictBool, StrictInt

from models.nips.base import BaseData


# StrictInt: rejects bool (bool is subclass of int in Python)
# tuple[StrictInt, StrictInt]: enforces exactly 2 elements for ranges
KindRange = tuple[StrictInt, StrictInt]  # [start, end] range for event kinds


class Nip11FetchDataLimitation(BaseData):
    """Server limitations per NIP-11."""

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

    _INT_FIELDS: ClassVar[set[str]] = {
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
    _BOOL_FIELDS: ClassVar[set[str]] = {
        "auth_required",
        "payment_required",
        "restricted_writes",
    }


class Nip11FetchDataRetentionEntry(BaseData):
    """Single retention policy entry per NIP-11.

    NOTE: This class overrides parse() because 'kinds' can be a list of
    ints or [int, int] ranges (tuples), which requires special handling.
    """

    kinds: list[StrictInt | KindRange] | None = None
    time: StrictInt | None = None
    count: StrictInt | None = None

    @classmethod
    def parse(cls, data: Any) -> dict[str, Any]:
        """Parse arbitrary data into a valid dict for this model.

        Special handling for 'kinds' which can be int or [int, int] ranges.
        """
        if not isinstance(data, dict):
            return {}
        result: dict[str, Any] = {}
        # Parse kinds: list of int or [int, int] ranges
        if "kinds" in data and isinstance(data["kinds"], list):
            kinds: list[int | tuple[int, int]] = []
            for item in data["kinds"]:
                if isinstance(item, int) and not isinstance(item, bool):
                    kinds.append(item)
                elif isinstance(item, list) and len(item) == 2:
                    if (
                        isinstance(item[0], int)
                        and not isinstance(item[0], bool)
                        and isinstance(item[1], int)
                        and not isinstance(item[1], bool)
                    ):
                        kinds.append((item[0], item[1]))
            if kinds:
                result["kinds"] = kinds
        # Parse time and count
        for key in ("time", "count"):
            if key in data:
                value = data[key]
                if isinstance(value, int) and not isinstance(value, bool):
                    result[key] = value
        return result

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict. Uses mode='json' to convert tuples to lists."""
        return self.model_dump(exclude_none=True, mode="json")


class Nip11FetchDataFeeEntry(BaseData):
    """Single fee entry per NIP-11."""

    amount: StrictInt | None = None
    unit: str | None = None
    period: StrictInt | None = None
    kinds: list[StrictInt] | None = None

    _INT_FIELDS: ClassVar[set[str]] = {"amount", "period"}
    _STR_FIELDS: ClassVar[set[str]] = {"unit"}
    _INT_LIST_FIELDS: ClassVar[set[str]] = {"kinds"}


class Nip11FetchDataFees(BaseData):
    """Fee schedules per NIP-11.

    NOTE: This class overrides parse() because it contains nested
    Nip11FetchDataFeeEntry objects that need custom parsing.
    """

    admission: list[Nip11FetchDataFeeEntry] | None = None
    subscription: list[Nip11FetchDataFeeEntry] | None = None
    publication: list[Nip11FetchDataFeeEntry] | None = None

    @classmethod
    def parse(cls, data: Any) -> dict[str, Any]:
        """Parse arbitrary data with nested fee entries."""
        if not isinstance(data, dict):
            return {}
        result: dict[str, Any] = {}
        for key in ("admission", "subscription", "publication"):
            if key in data and isinstance(data[key], list):
                entries = [Nip11FetchDataFeeEntry.parse(e) for e in data[key]]
                entries = [e for e in entries if e]  # Remove empty dicts
                if entries:
                    result[key] = entries
        return result


class Nip11FetchData(BaseData):
    """Complete NIP-11 data structure.

    NOTE: This class overrides parse() because it contains nested objects
    (limitation, retention, fees) that need custom parsing. It also overrides
    to_dict() to use by_alias=True for the 'self' field serialization.
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
        """Relay's own pubkey (from NIP-11 'self' field)."""
        return self.self_pubkey

    _STR_FIELDS: ClassVar[set[str]] = {
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
    _STR_LIST_FIELDS: ClassVar[set[str]] = {
        "relay_countries",
        "language_tags",
        "tags",
    }

    @classmethod
    def parse(cls, data: Any) -> dict[str, Any]:
        """Parse arbitrary data into a valid dict for this model."""
        if not isinstance(data, dict):
            return {}
        result: dict[str, Any] = {}
        # Parse string fields
        for key in cls._STR_FIELDS:
            if key in data and isinstance(data[key], str):
                result[key] = data[key]
        # Parse supported_nips (list of int)
        if "supported_nips" in data and isinstance(data["supported_nips"], list):
            nips = [
                n for n in data["supported_nips"] if isinstance(n, int) and not isinstance(n, bool)
            ]
            if nips:
                result["supported_nips"] = nips
        # Parse limitation (object)
        if "limitation" in data:
            limitation = Nip11FetchDataLimitation.parse(data["limitation"])
            if limitation:
                result["limitation"] = limitation
        # Parse retention (list of objects)
        if "retention" in data and isinstance(data["retention"], list):
            entries = [Nip11FetchDataRetentionEntry.parse(e) for e in data["retention"]]
            entries = [e for e in entries if e]
            if entries:
                result["retention"] = entries
        # Parse fees (object)
        if "fees" in data:
            fees = Nip11FetchDataFees.parse(data["fees"])
            if fees:
                result["fees"] = fees
        # Parse string list fields
        for key in cls._STR_LIST_FIELDS:
            if key in data and isinstance(data[key], list):
                items = [s for s in data[key] if isinstance(s, str)]
                if items:
                    result[key] = items
        return result

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict. Uses by_alias for 'self' field serialization."""
        return self.model_dump(exclude_none=True, by_alias=True)
