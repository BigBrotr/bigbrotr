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
from bigbrotr.nips.parsing import (
    FieldSpec,
    ParseIssue,
    ParseReport,
    join_parse_path,
    parse_fields_report,
)


KindRange = tuple[StrictInt, StrictInt]


def _invalid_input_report(path: str, fallback: str) -> ParseReport:
    return ParseReport(
        parsed={},
        issues=(
            ParseIssue(
                kind="invalid_input",
                path=path or fallback,
                detail="expected dict",
            ),
        ),
    )


def _unknown_field_issues(
    data: dict[str, Any],
    known_fields: set[str],
    *,
    path: str,
) -> list[ParseIssue]:
    return [
        ParseIssue(
            kind="unknown_field",
            path=join_parse_path(path, key),
            detail="field not declared in parsing spec",
        )
        for key in data
        if key not in known_fields
    ]


def _parse_strict_int_fields(
    data: dict[str, Any],
    field_names: tuple[str, ...],
    *,
    path: str,
) -> tuple[dict[str, int], list[ParseIssue]]:
    result: dict[str, int] = {}
    issues: list[ParseIssue] = []

    for key in field_names:
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, int) and not isinstance(value, bool):
            result[key] = value
        else:
            issues.append(
                ParseIssue(
                    kind="invalid_value",
                    path=join_parse_path(path, key),
                    detail="expected int",
                )
            )

    return result, issues


def _parse_supported_nips(raw_nips: Any, *, path: str) -> tuple[list[int] | None, list[ParseIssue]]:
    issues: list[ParseIssue] = []
    if not isinstance(raw_nips, list):
        return None, [
            ParseIssue(
                kind="invalid_value",
                path=path,
                detail="expected list[int]",
            )
        ]

    nips: list[int] = []
    for index, value in enumerate(raw_nips):
        if isinstance(value, int) and not isinstance(value, bool):
            nips.append(value)
        else:
            issues.append(
                ParseIssue(
                    kind="invalid_value",
                    path=join_parse_path(path, f"[{index}]"),
                    detail="expected int",
                )
            )

    if nips:
        return sorted(set(nips)), issues
    if not raw_nips:
        issues.append(
            ParseIssue(
                kind="invalid_value",
                path=path,
                detail="expected non-empty list[int]",
            )
        )
    return None, issues


def _parse_retention_kinds(
    raw_kinds: Any,
    *,
    path: str,
) -> tuple[list[int | tuple[int, int]] | None, list[ParseIssue]]:
    if not isinstance(raw_kinds, list):
        return None, [
            ParseIssue(
                kind="invalid_value",
                path=path,
                detail="expected list[int | [int, int]]",
            )
        ]

    kinds: list[int | tuple[int, int]] = []
    issues: list[ParseIssue] = []
    for index, item in enumerate(raw_kinds):
        item_path = join_parse_path(path, f"[{index}]")
        if isinstance(item, int) and not isinstance(item, bool):
            kinds.append(item)
            continue
        if (
            isinstance(item, list)
            and len(item) == 2  # noqa: PLR2004 - [min, max] range pair
            and isinstance(item[0], int)
            and not isinstance(item[0], bool)
            and isinstance(item[1], int)
            and not isinstance(item[1], bool)
        ):
            kinds.append((item[0], item[1]))
            continue
        issues.append(
            ParseIssue(
                kind="invalid_value",
                path=item_path,
                detail="expected int or [int, int] range",
            )
        )

    if kinds:
        return kinds, issues
    if not raw_kinds:
        issues.append(
            ParseIssue(
                kind="invalid_value",
                path=path,
                detail="expected non-empty list[int | [int, int]]",
            )
        )
    return None, issues


def _parse_retention_entries(
    raw_entries: Any,
    *,
    path: str,
) -> tuple[list[dict[str, Any]] | None, list[ParseIssue]]:
    if not isinstance(raw_entries, list):
        return None, [
            ParseIssue(
                kind="invalid_value",
                path=path,
                detail="expected list[retention_entry]",
            )
        ]

    entries: list[dict[str, Any]] = []
    issues: list[ParseIssue] = []
    for index, entry in enumerate(raw_entries):
        entry_report = Nip11InfoDataRetentionEntry.parse_report(
            entry,
            path=join_parse_path(path, f"[{index}]"),
        )
        issues.extend(entry_report.issues)
        if entry_report.parsed:
            entries.append(entry_report.parsed)

    if entries:
        return entries, issues
    if not raw_entries:
        issues.append(
            ParseIssue(
                kind="invalid_value",
                path=path,
                detail="expected non-empty list[retention_entry]",
            )
        )
    return None, issues


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
    def parse_report(cls, data: Any, *, path: str = "") -> ParseReport:
        """Parse a retention entry, handling mixed int/range kinds lists.

        Args:
            data: Raw dictionary for a single retention entry.

        Returns:
            Validated dictionary with ``kinds``, ``time``, and ``count``.
        """
        if not isinstance(data, dict):
            return _invalid_input_report(path, cls.__name__)
        result: dict[str, Any] = {}
        issues = _unknown_field_issues(data, {"kinds", "time", "count"}, path=path)

        if "kinds" in data:
            kinds, kinds_issues = _parse_retention_kinds(
                data["kinds"],
                path=join_parse_path(path, "kinds"),
            )
            issues.extend(kinds_issues)
            if kinds is not None:
                result["kinds"] = kinds

        int_fields, int_issues = _parse_strict_int_fields(data, ("time", "count"), path=path)
        result.update(int_fields)
        issues.extend(int_issues)
        return ParseReport(parsed=result, issues=tuple(issues))

    @classmethod
    def parse(cls, data: Any) -> dict[str, Any]:
        """Parse a retention entry, handling mixed int/range kinds lists."""
        return cls.parse_report(data).parsed

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
    def parse_report(cls, data: Any, *, path: str = "") -> ParseReport:
        """Parse fee schedule data with nested fee entry objects.

        Args:
            data: Raw dictionary containing fee category lists.

        Returns:
            Validated dictionary with non-empty fee entry lists.
        """
        if not isinstance(data, dict):
            return _invalid_input_report(path, cls.__name__)
        result: dict[str, Any] = {}
        issues = _unknown_field_issues(
            data,
            {"admission", "subscription", "publication"},
            path=path,
        )

        for key in ("admission", "subscription", "publication"):
            if key not in data:
                continue

            raw_entries = data[key]
            field_path = join_parse_path(path, key)
            if not isinstance(raw_entries, list):
                issues.append(
                    ParseIssue(
                        kind="invalid_value",
                        path=field_path,
                        detail="expected list[fee_entry]",
                    )
                )
                continue

            entries: list[dict[str, Any]] = []
            for index, entry in enumerate(raw_entries):
                entry_report = Nip11InfoDataFeeEntry.parse_report(
                    entry,
                    path=join_parse_path(field_path, f"[{index}]"),
                )
                issues.extend(entry_report.issues)
                if entry_report.parsed:
                    entries.append(entry_report.parsed)

            if entries:
                result[key] = entries
            elif not raw_entries:
                issues.append(
                    ParseIssue(
                        kind="invalid_value",
                        path=field_path,
                        detail="expected non-empty list[fee_entry]",
                    )
                )

        return ParseReport(parsed=result, issues=tuple(issues))

    @classmethod
    def parse(cls, data: Any) -> dict[str, Any]:
        """Parse fee schedule data with nested fee entry objects."""
        return cls.parse_report(data).parsed


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
    attributes: list[str] | None = Field(
        default=None, description="Self-describing relay attributes in PascalCase (NIP-11)"
    )

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
                "attributes",
            }
        ),
    )

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
        return cls.parse_report(data).parsed

    @classmethod
    def parse_report(cls, data: Any, *, path: str = "") -> ParseReport:
        """Parse a complete NIP-11 document and record dropped fields."""
        if not isinstance(data, dict):
            return _invalid_input_report(path, cls.__name__)

        report = parse_fields_report(
            data,
            cls._FIELD_SPEC,
            path=path,
            extra_known_fields=frozenset({"supported_nips", "limitation", "retention", "fees"}),
        )
        result = dict(report.parsed)
        issues = list(report.issues)

        if "supported_nips" in data:
            supported_nips, supported_nips_issues = _parse_supported_nips(
                data["supported_nips"],
                path=join_parse_path(path, "supported_nips"),
            )
            issues.extend(supported_nips_issues)
            if supported_nips is not None:
                result["supported_nips"] = supported_nips

        if "limitation" in data:
            limitation_report = Nip11InfoDataLimitation.parse_report(
                data["limitation"],
                path=join_parse_path(path, "limitation"),
            )
            issues.extend(limitation_report.issues)
            if limitation_report.parsed:
                result["limitation"] = limitation_report.parsed

        if "retention" in data:
            retention_entries, retention_issues = _parse_retention_entries(
                data["retention"],
                path=join_parse_path(path, "retention"),
            )
            issues.extend(retention_issues)
            if retention_entries is not None:
                result["retention"] = retention_entries

        if "fees" in data:
            fees_report = Nip11InfoDataFees.parse_report(
                data["fees"],
                path=join_parse_path(path, "fees"),
            )
            issues.extend(fees_report.issues)
            if fees_report.parsed:
                result["fees"] = fees_report.parsed

        return ParseReport(parsed=result, issues=tuple(issues))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary using field aliases (``self`` instead of ``self_pubkey``)."""
        return self.model_dump(exclude_none=True, by_alias=True, mode="json")
