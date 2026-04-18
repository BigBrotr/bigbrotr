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


_MSATS_PER_SAT = 1000
_ACTIVITY_HOURS_BUCKETS = 24


def _topic_count_sort_key(item: tuple[str, Any]) -> tuple[int, str]:
    """Sort topics by descending count, then lexicographically for stability."""
    topic, raw_count = item
    return (-int(raw_count), topic)


def _coerce_topic_count_mapping(value: Any) -> dict[str, Any]:
    """Return topic counts as a mapping, preserving ``None`` as an empty mapping."""
    if value is None:
        return {}
    if not hasattr(value, "items"):
        raise TypeError("topic_counts must be a mapping of topic strings to counts")
    return dict(value)


def _normalize_tag_set(value: tuple[str, ...]) -> tuple[str, ...]:
    """Return a stable deduplicated lexical ordering for set-like tag tuples."""
    if isinstance(value, (str, bytes)):
        raise TypeError("k_tags must be a sequence of tag strings, not a scalar string")
    return tuple(sorted(set(value)))


def _coerce_tag_sequence(value: Any) -> tuple[str, ...]:
    """Return a tuple of tag strings, preserving ``None`` as an empty sequence."""
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        raise TypeError("k_tags must be a sequence of tag strings, not a scalar string")
    return tuple(str(tag) for tag in value)


def _normalize_activity_hours(value: tuple[int, ...]) -> tuple[int, ...]:
    """Validate and normalize the 24-slot UTC activity heatmap."""
    normalized = tuple(int(hour) for hour in value)
    if len(normalized) != _ACTIVITY_HOURS_BUCKETS:
        raise ValueError(
            f"activity_hours must contain exactly {_ACTIVITY_HOURS_BUCKETS} hourly buckets"
        )
    return normalized


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
        top_n = row.get("top_topics_limit", 5)

        hours_raw = row.get("activity_hours")
        hours = tuple(int(h) for h in hours_raw) if hours_raw is not None else (0,) * 24

        return cls(
            pubkey=row["pubkey"],
            score=int(row.get("score", 0)),
            post_count=int(row.get("post_count", 0)),
            reply_count=int(row.get("reply_count", 0)),
            reaction_count_recd=int(row.get("reaction_count_recd", 0)),
            reaction_count_sent=int(row.get("reaction_count_sent", 0)),
            repost_count_recd=int(row.get("repost_count_recd", 0)),
            repost_count_sent=int(row.get("repost_count_sent", 0)),
            report_count_recd=int(row.get("report_count_recd", 0)),
            report_count_sent=int(row.get("report_count_sent", 0)),
            zap_count_recd=int(row.get("zap_count_recd", 0)),
            zap_count_sent=int(row.get("zap_count_sent", 0)),
            zap_amount_recd_msats=int(row.get("zap_amount_recd", 0)),
            zap_amount_sent_msats=int(row.get("zap_amount_sent", 0)),
            first_created_at=row.get("first_created_at"),
            last_event_at=row.get("last_event_at"),
            activity_hours=hours,
            top_topics=tuple(t[0] for t in sorted_topics[:top_n]),
            follower_count=int(row.get("follower_count", 0)),
            following_count=int(row.get("following_count", 0)),
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
            score=int(row.get("score", 0)),
            comment_count=int(row.get("comment_count", 0)),
            quote_count=int(row.get("quote_count", 0)),
            repost_count=int(row.get("repost_count", 0)),
            reaction_count=int(row.get("reaction_count", 0)),
            zap_count=int(row.get("zap_count", 0)),
            zap_amount_msats=int(row.get("zap_amount", 0)),
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
            score=int(row.get("score", 0)),
            comment_count=int(row.get("comment_count", 0)),
            quote_count=int(row.get("quote_count", 0)),
            repost_count=int(row.get("repost_count", 0)),
            reaction_count=int(row.get("reaction_count", 0)),
            zap_count=int(row.get("zap_count", 0)),
            zap_amount_msats=int(row.get("zap_amount", 0)),
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
            score=int(row.get("score", 0)),
            comment_count=int(row.get("comment_count", 0)),
            reaction_count=int(row.get("reaction_count", 0)),
            k_tags=_coerce_tag_sequence(row.get("k_tags")),
        )


@dataclass(frozen=True, slots=True)
class TrustedProviderDeclaration:
    """One NIP-85 kind 10040 trusted service provider declaration tag."""

    result_kind: int
    tag_name: str
    service_pubkey: str
    relay_hint: str

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
