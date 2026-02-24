"""Integration tests for BigBrotr statistical materialized views.

Tests exercise the 6 statistics matviews (event_stats, relay_stats,
kind_counts, kind_counts_by_relay, pubkey_counts, pubkey_counts_by_relay)
and the all_statistics_refresh meta-function. These views exist only in
the bigbrotr deployment, not in the base schema.

Pattern: insert data -> refresh -> query view -> verify.
"""

from __future__ import annotations

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import EventRelay, Relay, RelayMetadata
from bigbrotr.models.event import Event
from bigbrotr.models.metadata import Metadata, MetadataType
from tests.conftest import make_mock_event


pytestmark = pytest.mark.integration


# ============================================================================
# Helpers
# ============================================================================


def _make_event_relay(
    event_id: str,
    relay_url: str,
    kind: int = 1,
    pubkey: str = "bb" * 32,
    created_at: int = 1700000000,
) -> EventRelay:
    """Create an EventRelay with the given parameters."""
    mock = make_mock_event(
        event_id=event_id,
        pubkey=pubkey,
        created_at=created_at,
        kind=kind,
        sig="ee" * 64,
    )
    relay = Relay(relay_url, discovered_at=1700000000)
    return EventRelay(event=Event(mock), relay=relay, seen_at=1700000001)


# ============================================================================
# event_stats
# ============================================================================


class TestEventStats:
    async def test_empty_returns_zeros(self, brotr: Brotr):
        await brotr.refresh_materialized_view("event_stats")

        rows = await brotr.fetch("SELECT * FROM event_stats")
        assert len(rows) == 1
        assert rows[0]["event_count"] == 0
        assert rows[0]["unique_pubkeys"] == 0
        assert rows[0]["unique_kinds"] == 0

    async def test_with_data(self, brotr: Brotr):
        ers = [
            _make_event_relay(
                event_id=f"{i:064x}",
                relay_url="wss://stats.example.com",
                kind=1,
                pubkey=f"{i % 2:064x}",  # 2 unique pubkeys
                created_at=1700000000 + i,
            )
            for i in range(5)
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("event_stats")

        rows = await brotr.fetch("SELECT * FROM event_stats")
        assert len(rows) == 1
        assert rows[0]["event_count"] == 5
        assert rows[0]["unique_pubkeys"] == 2
        assert rows[0]["unique_kinds"] == 1
        assert rows[0]["regular_event_count"] == 5


# ============================================================================
# relay_stats
# ============================================================================


class TestRelayStats:
    async def test_empty(self, brotr: Brotr):
        await brotr.refresh_materialized_view("relay_stats")

        rows = await brotr.fetch("SELECT * FROM relay_stats")
        assert len(rows) == 0

    async def test_with_events(self, brotr: Brotr):
        ers = [
            _make_event_relay(
                event_id=f"{i:064x}",
                relay_url="wss://rstats.example.com",
            )
            for i in range(3)
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("relay_stats")

        rows = await brotr.fetch(
            "SELECT * FROM relay_stats WHERE relay_url = $1",
            "wss://rstats.example.com",
        )
        assert len(rows) == 1
        assert rows[0]["event_count"] == 3
        assert rows[0]["network"] == "clearnet"


# ============================================================================
# kind_counts
# ============================================================================


class TestKindCounts:
    async def test_multiple_kinds(self, brotr: Brotr):
        ers = [
            _make_event_relay(
                event_id="a0" * 32,
                relay_url="wss://kinds.example.com",
                kind=1,
            ),
            _make_event_relay(
                event_id="a1" * 32,
                relay_url="wss://kinds.example.com",
                kind=1,
            ),
            _make_event_relay(
                event_id="a2" * 32,
                relay_url="wss://kinds.example.com",
                kind=3,
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("kind_counts")

        rows = await brotr.fetch("SELECT kind, event_count FROM kind_counts ORDER BY kind")
        counts = {row["kind"]: row["event_count"] for row in rows}
        assert counts[1] == 2
        assert counts[3] == 1


# ============================================================================
# kind_counts_by_relay
# ============================================================================


class TestKindCountsByRelay:
    async def test_per_relay_kinds(self, brotr: Brotr):
        ers = [
            _make_event_relay(
                event_id="b0" * 32,
                relay_url="wss://kcr1.example.com",
                kind=1,
            ),
            _make_event_relay(
                event_id="b1" * 32,
                relay_url="wss://kcr1.example.com",
                kind=1,
            ),
            _make_event_relay(
                event_id="b2" * 32,
                relay_url="wss://kcr2.example.com",
                kind=3,
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("kind_counts_by_relay")

        rows = await brotr.fetch(
            "SELECT relay_url, kind, event_count FROM kind_counts_by_relay ORDER BY relay_url, kind"
        )
        assert len(rows) == 2
        assert rows[0]["relay_url"] == "wss://kcr1.example.com"
        assert rows[0]["kind"] == 1
        assert rows[0]["event_count"] == 2
        assert rows[1]["relay_url"] == "wss://kcr2.example.com"
        assert rows[1]["kind"] == 3
        assert rows[1]["event_count"] == 1


# ============================================================================
# pubkey_counts
# ============================================================================


class TestPubkeyCounts:
    async def test_multiple_pubkeys(self, brotr: Brotr):
        ers = [
            _make_event_relay(
                event_id="c0" * 32,
                relay_url="wss://pkcnt.example.com",
                pubkey="11" * 32,
            ),
            _make_event_relay(
                event_id="c1" * 32,
                relay_url="wss://pkcnt.example.com",
                pubkey="11" * 32,
            ),
            _make_event_relay(
                event_id="c2" * 32,
                relay_url="wss://pkcnt.example.com",
                pubkey="22" * 32,
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("pubkey_counts")

        rows = await brotr.fetch(
            "SELECT pubkey, event_count FROM pubkey_counts ORDER BY event_count DESC"
        )
        assert len(rows) == 2
        assert rows[0]["pubkey"] == "11" * 32
        assert rows[0]["event_count"] == 2
        assert rows[1]["pubkey"] == "22" * 32
        assert rows[1]["event_count"] == 1


# ============================================================================
# pubkey_counts_by_relay
# ============================================================================


class TestPubkeyCountsByRelay:
    async def test_per_relay_pubkeys(self, brotr: Brotr):
        ers = [
            _make_event_relay(
                event_id="d0" * 32,
                relay_url="wss://pkr1.example.com",
                pubkey="11" * 32,
            ),
            _make_event_relay(
                event_id="d1" * 32,
                relay_url="wss://pkr1.example.com",
                pubkey="22" * 32,
            ),
            _make_event_relay(
                event_id="d2" * 32,
                relay_url="wss://pkr2.example.com",
                pubkey="11" * 32,
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("pubkey_counts_by_relay")

        rows = await brotr.fetch(
            "SELECT relay_url, pubkey, event_count"
            " FROM pubkey_counts_by_relay"
            " ORDER BY relay_url, pubkey"
        )
        assert len(rows) == 3
        r1_rows = [r for r in rows if r["relay_url"] == "wss://pkr1.example.com"]
        assert len(r1_rows) == 2


# ============================================================================
# all_statistics_refresh
# ============================================================================


class TestAllStatisticsRefresh:
    async def test_refreshes_all_views(self, brotr: Brotr):
        er = _make_event_relay(
            event_id="e0" * 32,
            relay_url="wss://allref.example.com",
        )
        await brotr.insert_event_relay([er], cascade=True)

        relay = Relay("wss://allref.example.com", discovered_at=1700000000)
        metadata = Metadata(
            type=MetadataType.NIP11_INFO,
            data={"name": "All Refresh"},
        )
        rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=1700000001)
        await brotr.insert_relay_metadata([rm], cascade=True)

        await brotr.execute("SELECT all_statistics_refresh()")

        es = await brotr.fetch("SELECT * FROM event_stats")
        assert es[0]["event_count"] == 1

        rs = await brotr.fetch(
            "SELECT * FROM relay_stats WHERE relay_url = $1",
            "wss://allref.example.com",
        )
        assert len(rs) == 1

        rml = await brotr.fetch("SELECT * FROM relay_metadata_latest")
        assert len(rml) >= 1

        kc = await brotr.fetch("SELECT * FROM kind_counts")
        assert len(kc) >= 1

        kcr = await brotr.fetch("SELECT * FROM kind_counts_by_relay")
        assert len(kcr) >= 1

        pc = await brotr.fetch("SELECT * FROM pubkey_counts")
        assert len(pc) >= 1

        pcr = await brotr.fetch("SELECT * FROM pubkey_counts_by_relay")
        assert len(pcr) >= 1
