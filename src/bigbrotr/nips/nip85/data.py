"""NIP-85 Trusted Assertion data models.

Frozen dataclasses representing NIP-85 trusted-provider declarations (kind
10040) and all four trusted-assertion subject types: per-pubkey social metrics
(kind 30382), per-event engagement metrics (kind 30383), per-addressable
engagement metrics (kind 30384), and per-NIP-73 identifier engagement metrics
(kind 30385). Assertion models convert from database row format (millisats,
heatmap arrays, JSONB topics) to NIP-85 tag format (sats, active_hours
start/end, top-N topics).

See Also:
    [bigbrotr.nips.event_builders][]: Consumes these models to build
        NIP-85 Nostr events with the correct tags.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from bigbrotr.models.constants import EventKind
from bigbrotr.models.relay import Relay


_MSATS_PER_SAT = 1000
_ACTIVITY_HOURS_BUCKETS = 24
_MAX_NIP85_SCORE = 100
_HEX_32_TEXT_LENGTH = 64
_MISSING = object()
_SUPPORTED_TRUSTED_PROVIDER_RESULT_KINDS = frozenset(
    {
        int(EventKind.NIP85_USER_ASSERTION),
        int(EventKind.NIP85_EVENT_ASSERTION),
        int(EventKind.NIP85_ADDRESSABLE_ASSERTION),
        int(EventKind.NIP85_IDENTIFIER_ASSERTION),
    }
)
_USER_ASSERTION_INT_FIELDS = (
    "score",
    "post_count",
    "reply_count",
    "reaction_count_recd",
    "reaction_count_sent",
    "repost_count_recd",
    "repost_count_sent",
    "report_count_recd",
    "report_count_sent",
    "zap_count_recd",
    "zap_count_sent",
    "zap_amount_recd_msats",
    "zap_amount_sent_msats",
    "follower_count",
    "following_count",
)
_EVENT_ASSERTION_INT_FIELDS = (
    "score",
    "comment_count",
    "quote_count",
    "repost_count",
    "reaction_count",
    "zap_count",
    "zap_amount_msats",
)
_ADDRESSABLE_ASSERTION_INT_FIELDS = _EVENT_ASSERTION_INT_FIELDS
_IDENTIFIER_ASSERTION_INT_FIELDS = (
    "score",
    "comment_count",
    "reaction_count",
)


def _topic_count_sort_key(item: tuple[str, int]) -> tuple[int, str]:
    """Sort topics by descending count, then lexicographically for stability."""
    topic, raw_count = item
    return (-raw_count, topic)


def _normalize_topic_count(value: Any) -> int:
    """Return a non-negative topic count, accepting integer JSONB strings."""
    if isinstance(value, bool):
        raise TypeError("topic_counts values must be non-negative integers")
    if isinstance(value, int):
        if value < 0:
            raise ValueError("topic_counts values must be >= 0")
        return value
    if isinstance(value, str):
        try:
            normalized = int(value)
        except ValueError as exc:
            raise TypeError("topic_counts values must be non-negative integers") from exc
        if normalized < 0 or value.strip() != str(normalized):
            raise TypeError("topic_counts values must be non-negative integers")
        return normalized
    raise TypeError("topic_counts values must be non-negative integers")


def _coerce_topic_count_mapping(value: Any) -> dict[str, int]:
    """Return topic counts as a mapping, preserving ``None`` as an empty mapping."""
    if value is None:
        return {}
    if not hasattr(value, "items"):
        raise TypeError("topic_counts must be a mapping of topic strings to counts")
    topic_counts: dict[str, int] = {}
    for key, raw_count in value.items():
        if not isinstance(key, str):
            raise TypeError("topic_counts keys must be strings")
        topic_counts[key] = _normalize_topic_count(raw_count)
    return topic_counts


def _normalize_tag_set(value: tuple[str, ...]) -> tuple[str, ...]:
    """Return a stable deduplicated lexical ordering for set-like tag tuples."""
    return tuple(
        sorted(
            set(
                _require_text_sequence(
                    value,
                    "k_tags",
                    noun="tag strings",
                )
            )
        )
    )


def _coerce_tag_sequence(value: Any) -> tuple[str, ...]:
    """Return a tuple of tag strings, preserving ``None`` as an empty sequence."""
    if value is None:
        return ()
    return _require_text_sequence(value, "k_tags", noun="tag strings")


def _require_text(value: Any, field_name: str) -> str:
    """Return ``value`` when it is a string, otherwise raise a typed boundary error."""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    return value


def _require_non_empty_text(value: Any, field_name: str) -> str:
    """Return ``value`` as a non-empty string."""
    text = _require_text(value, field_name)
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _require_hex32_text(value: Any, field_name: str) -> str:
    """Return ``value`` as a canonical 32-byte hex string."""
    text = _require_non_empty_text(value, field_name)
    if len(text) != _HEX_32_TEXT_LENGTH:
        raise ValueError(f"{field_name} must be a 64-character hex string")
    try:
        bytes.fromhex(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a 64-character hex string") from exc
    return text.lower()


def _require_optional_hex32_text(value: Any, field_name: str) -> str:
    """Return ``value`` as an optional canonical 32-byte hex string."""
    text = _require_text(value, field_name)
    if not text:
        return ""
    return _require_hex32_text(text, field_name)


def _normalize_tag_name(value: Any) -> str:
    """Return the canonical declaration tag name."""
    tag_name = _require_text(value, "tag_name").strip()
    if not tag_name:
        raise ValueError("tag_name must not be empty")
    if ":" in tag_name:
        raise ValueError("tag_name must not contain ':'")
    return tag_name


def _normalize_relay_hint(value: Any) -> str:
    """Return a canonical relay URL for Kind 10040 provider declarations."""
    relay_hint = _require_non_empty_text(value, "relay_hint")
    try:
        return Relay.parse(relay_hint).url
    except ValueError as exc:
        raise ValueError("relay_hint must be a valid relay URL") from exc


def _require_supported_trusted_provider_kind(value: Any) -> int:
    """Return one of the supported NIP-85 assertion kinds for Kind 10040 tags."""
    result_kind = _require_non_negative_int(value, "result_kind")
    if result_kind not in _SUPPORTED_TRUSTED_PROVIDER_RESULT_KINDS:
        raise ValueError("result_kind must be a supported NIP-85 assertion kind")
    return result_kind


def _require_text_sequence(value: Any, field_name: str, *, noun: str) -> tuple[str, ...]:
    """Return ``value`` as a tuple of strings, rejecting scalar or mixed-type inputs."""
    if value is None:
        raise TypeError(f"{field_name} must be a sequence of {noun}")
    if isinstance(value, (str, bytes)):
        raise TypeError(f"{field_name} must be a sequence of {noun}, not a scalar string")
    items = tuple(value)
    if any(not isinstance(item, str) for item in items):
        raise TypeError(f"{field_name} must contain only strings")
    return items


def _require_non_negative_int(value: Any, field_name: str) -> int:
    """Return ``value`` when it is a non-negative int, otherwise raise a typed error."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be a non-negative integer")
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return int(value)


def _require_score(value: Any, field_name: str = "score") -> int:
    """Return a normalized NIP-85 score constrained to the inclusive range 0-100."""
    score = _require_non_negative_int(value, field_name)
    if score > _MAX_NIP85_SCORE:
        raise ValueError(f"{field_name} must be <= {_MAX_NIP85_SCORE}")
    return score


def _require_optional_non_negative_int(value: Any, field_name: str) -> int | None:
    """Return ``None`` or a real non-negative integer timestamp-like value."""
    if value is None:
        return None
    return _require_non_negative_int(value, field_name)


def _normalize_activity_hours(value: tuple[int, ...]) -> tuple[int, ...]:
    """Validate and normalize the 24-slot UTC activity heatmap."""
    normalized = tuple(_require_non_negative_int(hour, "activity_hours entries") for hour in value)
    if len(normalized) != _ACTIVITY_HOURS_BUCKETS:
        raise ValueError(
            f"activity_hours must contain exactly {_ACTIVITY_HOURS_BUCKETS} hourly buckets"
        )
    return normalized


def _normalize_non_negative_int_fields(instance: object, field_names: tuple[str, ...]) -> None:
    """Validate named dataclass integer fields as real non-negative integers."""
    for field_name in field_names:
        normalizer = _require_score if field_name == "score" else _require_non_negative_int
        object.__setattr__(
            instance,
            field_name,
            normalizer(getattr(instance, field_name), field_name),
        )


def _metric_from_row(row: dict[str, Any], key: str, *, field_name: str | None = None) -> int:
    """Read one integer metric from a DB row without permissive coercion."""
    resolved_field_name = field_name or key
    normalizer = _require_score if resolved_field_name == "score" else _require_non_negative_int
    return normalizer(row.get(key, 0), resolved_field_name)


@dataclass(frozen=True, slots=True)
class UserAssertion:
    """NIP-85 kind 30382: per-pubkey social metrics.

    All zap amounts stored in millisats internally. Use ``zap_*_sats``
    properties for NIP-85 output (integer sats). ``active_hours_start``
    and ``active_hours_end`` are derived from the 24-slot heatmap using
    a weighted-center approach.

    Attributes:
        pubkey: Hex-encoded pubkey (64 chars) -- the assertion subject.
        score: Normalized provider score in the range 0-100.
        post_count: Total kind=1 events authored.
        reply_count: Kind=1 events with an ``e`` tag (replies).
        reaction_count_recd: Kind=7 events with tag ``p=pubkey``.
        reaction_count_sent: Kind=7 events authored.
        repost_count_recd: Kind=6 events targeting this pubkey's events.
        repost_count_sent: Kind=6 events authored.
        report_count_recd: Kind=1984 events with tag ``p=pubkey``.
        report_count_sent: Kind=1984 events authored.
        zap_count_recd: Bolt11-verified kind=9735 zap receipts received.
        zap_count_sent: Bolt11-verified kind=9735 zap receipts sent.
        zap_amount_recd_msats: Total verified zap amount received (millisats).
        zap_amount_sent_msats: Total verified zap amount sent (millisats).
        first_created_at: Unix timestamp of earliest event.
        last_event_at: Unix timestamp of most recent event (from pubkey_stats).
        activity_hours: 24-element list, index 0 = UTC hour 0 event count.
        top_topics: Most frequent ``t``-tag topics, descending by count with
            lexical tie-breaking for stable output.
        follower_count: Pubkeys whose latest kind=3 contains tag ``p=pubkey``.
        following_count: Number of ``p`` tags in this pubkey's latest kind=3.
    """

    pubkey: str
    score: int = 0
    post_count: int = 0
    reply_count: int = 0
    reaction_count_recd: int = 0
    reaction_count_sent: int = 0
    repost_count_recd: int = 0
    repost_count_sent: int = 0
    report_count_recd: int = 0
    report_count_sent: int = 0
    zap_count_recd: int = 0
    zap_count_sent: int = 0
    zap_amount_recd_msats: int = 0
    zap_amount_sent_msats: int = 0
    first_created_at: int | None = None
    last_event_at: int | None = None
    activity_hours: tuple[int, ...] = field(default_factory=lambda: (0,) * 24)
    top_topics: tuple[str, ...] = ()
    follower_count: int = 0
    following_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "pubkey", _require_hex32_text(self.pubkey, "pubkey"))
        object.__setattr__(
            self,
            "top_topics",
            _require_text_sequence(self.top_topics, "top_topics", noun="topic strings"),
        )
        _normalize_non_negative_int_fields(self, _USER_ASSERTION_INT_FIELDS)
        object.__setattr__(
            self,
            "first_created_at",
            _require_optional_non_negative_int(self.first_created_at, "first_created_at"),
        )
        object.__setattr__(
            self,
            "last_event_at",
            _require_optional_non_negative_int(self.last_event_at, "last_event_at"),
        )
        if (
            self.first_created_at is not None
            and self.last_event_at is not None
            and self.last_event_at < self.first_created_at
        ):
            raise ValueError("last_event_at must be >= first_created_at")
        object.__setattr__(self, "activity_hours", _normalize_activity_hours(self.activity_hours))

    @property
    def zap_amount_recd_sats(self) -> int:
        return self.zap_amount_recd_msats // _MSATS_PER_SAT

    @property
    def zap_amount_sent_sats(self) -> int:
        return self.zap_amount_sent_msats // _MSATS_PER_SAT

    @property
    def days_active(self) -> int:
        if self.first_created_at is None or self.last_event_at is None:
            return 0
        return max((self.last_event_at - self.first_created_at) // 86400 + 1, 1)

    @property
    def zap_avg_amt_day_recd_sats(self) -> int:
        if self.days_active == 0:
            return 0
        return self.zap_amount_recd_sats // self.days_active

    @property
    def zap_avg_amt_day_sent_sats(self) -> int:
        if self.days_active == 0:
            return 0
        return self.zap_amount_sent_sats // self.days_active

    @property
    def active_hours_start(self) -> int:
        return _heatmap_window_start(self.activity_hours)

    @property
    def active_hours_end(self) -> int:
        return _heatmap_window_end(self.activity_hours)

    def tags_hash(self) -> str:
        """SHA-256 hex digest of all tag values for change detection."""
        values = [
            str(self.score),
            str(self.follower_count),
            str(self.first_created_at or 0),
            str(self.post_count),
            str(self.reply_count),
            str(self.reaction_count_recd),
            str(self.zap_amount_recd_sats),
            str(self.zap_amount_sent_sats),
            str(self.zap_count_recd),
            str(self.zap_count_sent),
            str(self.zap_avg_amt_day_recd_sats),
            str(self.zap_avg_amt_day_sent_sats),
            str(self.report_count_recd),
            str(self.report_count_sent),
            ",".join(self.top_topics),
            str(self.active_hours_start),
            str(self.active_hours_end),
        ]
        return hashlib.sha256("|".join(values).encode()).hexdigest()

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> UserAssertion:
        """Construct from a joined nip85_pubkey_stats + pubkey_stats row."""
        raw_topics = _coerce_topic_count_mapping(row.get("topic_counts"))
        sorted_topics = sorted(raw_topics.items(), key=_topic_count_sort_key)
        raw_top_n = row.get("top_topics_limit", _MISSING)
        top_n = (
            5 if raw_top_n is _MISSING else _require_non_negative_int(raw_top_n, "top_topics_limit")
        )

        hours_raw = row.get("activity_hours")
        hours = tuple(hours_raw) if hours_raw is not None else (0,) * 24

        return cls(
            pubkey=row["pubkey"],
            score=_metric_from_row(row, "score"),
            post_count=_metric_from_row(row, "post_count"),
            reply_count=_metric_from_row(row, "reply_count"),
            reaction_count_recd=_metric_from_row(row, "reaction_count_recd"),
            reaction_count_sent=_metric_from_row(row, "reaction_count_sent"),
            repost_count_recd=_metric_from_row(row, "repost_count_recd"),
            repost_count_sent=_metric_from_row(row, "repost_count_sent"),
            report_count_recd=_metric_from_row(row, "report_count_recd"),
            report_count_sent=_metric_from_row(row, "report_count_sent"),
            zap_count_recd=_metric_from_row(row, "zap_count_recd"),
            zap_count_sent=_metric_from_row(row, "zap_count_sent"),
            zap_amount_recd_msats=_metric_from_row(
                row,
                "zap_amount_recd",
                field_name="zap_amount_recd_msats",
            ),
            zap_amount_sent_msats=_metric_from_row(
                row,
                "zap_amount_sent",
                field_name="zap_amount_sent_msats",
            ),
            first_created_at=row.get("first_created_at"),
            last_event_at=row.get("last_event_at"),
            activity_hours=hours,
            top_topics=tuple(t[0] for t in sorted_topics[:top_n]),
            follower_count=_metric_from_row(row, "follower_count"),
            following_count=_metric_from_row(row, "following_count"),
        )


@dataclass(frozen=True, slots=True)
class EventAssertion:
    """NIP-85 kind 30383: per-event engagement metrics.

    Zap amounts stored in millisats internally; use ``zap_amount_sats``
    property for NIP-85 output.

    Attributes:
        event_id: Hex-encoded event id (64 chars) -- the assertion subject.
        author_pubkey: Hex-encoded pubkey of the event's author.
        score: Normalized provider score in the range 0-100.
        comment_count: Kind=1 events with tag ``e=event_id``.
        quote_count: Events with tag ``q=event_id``.
        repost_count: Kind=6 events with tag ``e=event_id``.
        reaction_count: Kind=7 events with tag ``e=event_id``.
        zap_count: Bolt11-verified kind=9735 with tag ``e=event_id``.
        zap_amount_msats: Total verified zap amount (millisats).
    """

    event_id: str
    author_pubkey: str = ""
    score: int = 0
    comment_count: int = 0
    quote_count: int = 0
    repost_count: int = 0
    reaction_count: int = 0
    zap_count: int = 0
    zap_amount_msats: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _require_hex32_text(self.event_id, "event_id"))
        object.__setattr__(
            self,
            "author_pubkey",
            _require_optional_hex32_text(self.author_pubkey, "author_pubkey"),
        )
        _normalize_non_negative_int_fields(self, _EVENT_ASSERTION_INT_FIELDS)

    @property
    def zap_amount_sats(self) -> int:
        return self.zap_amount_msats // _MSATS_PER_SAT

    def tags_hash(self) -> str:
        """SHA-256 hex digest of all tag values for change detection."""
        values = [
            self.author_pubkey,
            str(self.score),
            str(self.comment_count),
            str(self.quote_count),
            str(self.repost_count),
            str(self.reaction_count),
            str(self.zap_count),
            str(self.zap_amount_sats),
        ]
        return hashlib.sha256("|".join(values).encode()).hexdigest()

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> EventAssertion:
        """Construct from a nip85_event_stats row."""
        return cls(
            event_id=row["event_id"],
            author_pubkey=row.get("author_pubkey", ""),
            score=_metric_from_row(row, "score"),
            comment_count=_metric_from_row(row, "comment_count"),
            quote_count=_metric_from_row(row, "quote_count"),
            repost_count=_metric_from_row(row, "repost_count"),
            reaction_count=_metric_from_row(row, "reaction_count"),
            zap_count=_metric_from_row(row, "zap_count"),
            zap_amount_msats=_metric_from_row(row, "zap_amount", field_name="zap_amount_msats"),
        )


@dataclass(frozen=True, slots=True)
class AddressableAssertion:
    """NIP-85 kind 30384: per-addressable-event engagement metrics."""

    event_address: str
    author_pubkey: str = ""
    score: int = 0
    comment_count: int = 0
    quote_count: int = 0
    repost_count: int = 0
    reaction_count: int = 0
    zap_count: int = 0
    zap_amount_msats: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "event_address",
            _require_non_empty_text(self.event_address, "event_address"),
        )
        object.__setattr__(
            self,
            "author_pubkey",
            _require_optional_hex32_text(self.author_pubkey, "author_pubkey"),
        )
        _normalize_non_negative_int_fields(self, _ADDRESSABLE_ASSERTION_INT_FIELDS)

    @property
    def zap_amount_sats(self) -> int:
        return self.zap_amount_msats // _MSATS_PER_SAT

    def tags_hash(self) -> str:
        """SHA-256 hex digest of all tag values for change detection."""
        values = [
            self.author_pubkey,
            str(self.score),
            str(self.comment_count),
            str(self.quote_count),
            str(self.repost_count),
            str(self.reaction_count),
            str(self.zap_count),
            str(self.zap_amount_sats),
        ]
        return hashlib.sha256("|".join(values).encode()).hexdigest()

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> AddressableAssertion:
        """Construct from a joined nip85_addressable_stats + score row."""
        return cls(
            event_address=row["event_address"],
            author_pubkey=row.get("author_pubkey", ""),
            score=_metric_from_row(row, "score"),
            comment_count=_metric_from_row(row, "comment_count"),
            quote_count=_metric_from_row(row, "quote_count"),
            repost_count=_metric_from_row(row, "repost_count"),
            reaction_count=_metric_from_row(row, "reaction_count"),
            zap_count=_metric_from_row(row, "zap_count"),
            zap_amount_msats=_metric_from_row(row, "zap_amount", field_name="zap_amount_msats"),
        )


@dataclass(frozen=True, slots=True)
class IdentifierAssertion:
    """NIP-85 kind 30385: per-NIP-73 identifier engagement metrics."""

    identifier: str
    score: int = 0
    comment_count: int = 0
    reaction_count: int = 0
    k_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identifier",
            _require_non_empty_text(self.identifier, "identifier"),
        )
        _normalize_non_negative_int_fields(self, _IDENTIFIER_ASSERTION_INT_FIELDS)
        object.__setattr__(self, "k_tags", _normalize_tag_set(self.k_tags))

    def tags_hash(self) -> str:
        """SHA-256 hex digest of all tag values for change detection."""
        values = [
            str(self.score),
            str(self.comment_count),
            str(self.reaction_count),
            ",".join(self.k_tags),
        ]
        return hashlib.sha256("|".join(values).encode()).hexdigest()

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> IdentifierAssertion:
        """Construct from a joined nip85_identifier_stats + score row."""
        return cls(
            identifier=row["identifier"],
            score=_metric_from_row(row, "score"),
            comment_count=_metric_from_row(row, "comment_count"),
            reaction_count=_metric_from_row(row, "reaction_count"),
            k_tags=_coerce_tag_sequence(row.get("k_tags")),
        )


@dataclass(frozen=True, slots=True)
class TrustedProviderDeclaration:
    """One NIP-85 kind 10040 trusted service provider declaration tag."""

    result_kind: int
    tag_name: str
    service_pubkey: str
    relay_hint: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "result_kind",
            _require_supported_trusted_provider_kind(self.result_kind),
        )
        object.__setattr__(self, "tag_name", _normalize_tag_name(self.tag_name))
        object.__setattr__(
            self,
            "service_pubkey",
            _require_hex32_text(self.service_pubkey, "service_pubkey"),
        )
        object.__setattr__(
            self,
            "relay_hint",
            _normalize_relay_hint(self.relay_hint),
        )

    @property
    def kind_tag(self) -> str:
        """Return the NIP-85 ``<kind:tag>`` declaration selector."""
        return f"{int(self.result_kind)}:{self.tag_name}"

    def as_tag(self) -> list[str]:
        """Return the kind 10040 tag vector for this provider declaration."""
        return [self.kind_tag, self.service_pubkey, self.relay_hint]


def _heatmap_window_start(hours: tuple[int, ...]) -> int:
    """Find the start hour of the most active contiguous 8-hour window."""
    if not hours or sum(hours) == 0:
        return 0
    best_start = 0
    best_sum = 0
    for start in range(24):
        window_sum = sum(hours[(start + i) % 24] for i in range(8))
        if window_sum > best_sum:
            best_sum = window_sum
            best_start = start
    return best_start


def _heatmap_window_end(hours: tuple[int, ...]) -> int:
    """Find the end hour of the most active contiguous 8-hour window."""
    return (_heatmap_window_start(hours) + 8) % 24
