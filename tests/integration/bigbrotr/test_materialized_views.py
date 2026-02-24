"""Integration tests for BigBrotr statistical materialized views.

Tests exercise the 10 statistics matviews (event_stats, relay_stats,
kind_counts, kind_counts_by_relay, pubkey_counts, pubkey_counts_by_relay,
network_stats, relay_software_counts, supported_nip_counts, event_daily_counts)
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


async def _insert_nip11_metadata(
    brotr: Brotr,
    relay_url: str,
    data: dict,
    generated_at: int = 1700000001,
) -> None:
    """Insert NIP-11 info metadata for a relay."""
    relay = Relay(relay_url, discovered_at=1700000000)
    metadata = Metadata(type=MetadataType.NIP11_INFO, data=data)
    rm = RelayMetadata(relay=relay, metadata=metadata, generated_at=generated_at)
    await brotr.insert_relay_metadata([rm], cascade=True)


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

    async def test_events_per_day(self, brotr: Brotr):
        ers = [
            _make_event_relay(
                event_id=f"{i:064x}",
                relay_url="wss://epd.example.com",
                created_at=1700000000 + i * 86400,  # 1 event per day
            )
            for i in range(10)
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("event_stats")

        rows = await brotr.fetch("SELECT events_per_day FROM event_stats")
        assert rows[0]["events_per_day"] is not None
        # 10 events over ~9 days ≈ 1.11 events/day
        assert float(rows[0]["events_per_day"]) > 0


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
                kind=i + 1,  # different kinds
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
        assert rows[0]["unique_kinds"] == 3

    async def test_nip11_info(self, brotr: Brotr):
        er = _make_event_relay(
            event_id="f0" * 32,
            relay_url="wss://nip11.example.com",
        )
        await brotr.insert_event_relay([er], cascade=True)
        await _insert_nip11_metadata(
            brotr,
            "wss://nip11.example.com",
            {"name": "Test Relay", "software": "strfry", "version": "1.0.0"},
        )
        await brotr.refresh_materialized_view("relay_stats")

        rows = await brotr.fetch(
            "SELECT nip11_name, nip11_software, nip11_version"
            " FROM relay_stats WHERE relay_url = $1",
            "wss://nip11.example.com",
        )
        assert len(rows) == 1
        assert rows[0]["nip11_name"] == "Test Relay"
        assert rows[0]["nip11_software"] == "strfry"
        assert rows[0]["nip11_version"] == "1.0.0"


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

    async def test_category_labels(self, brotr: Brotr):
        ers = [
            _make_event_relay(
                event_id="ca" * 32,
                relay_url="wss://cat.example.com",
                kind=1,  # regular
            ),
            _make_event_relay(
                event_id="cb" * 32,
                relay_url="wss://cat.example.com",
                kind=0,  # replaceable
            ),
            _make_event_relay(
                event_id="cc" * 32,
                relay_url="wss://cat.example.com",
                kind=20000,  # ephemeral
            ),
            _make_event_relay(
                event_id="cd" * 32,
                relay_url="wss://cat.example.com",
                kind=30000,  # addressable
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("kind_counts")

        rows = await brotr.fetch("SELECT kind, category FROM kind_counts ORDER BY kind")
        categories = {row["kind"]: row["category"] for row in rows}
        assert categories[0] == "replaceable"
        assert categories[1] == "regular"
        assert categories[20000] == "ephemeral"
        assert categories[30000] == "addressable"


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
    async def test_filters_single_event_pubkeys(self, brotr: Brotr):
        """Pubkeys with only 1 event per relay are excluded by HAVING >= 2."""
        ers = [
            # pubkey "11" has 1 event on pkr1 -> excluded
            _make_event_relay(
                event_id="d0" * 32,
                relay_url="wss://pkr1.example.com",
                pubkey="11" * 32,
            ),
            # pubkey "22" has 1 event on pkr1 -> excluded
            _make_event_relay(
                event_id="d1" * 32,
                relay_url="wss://pkr1.example.com",
                pubkey="22" * 32,
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("pubkey_counts_by_relay")

        rows = await brotr.fetch("SELECT * FROM pubkey_counts_by_relay")
        assert len(rows) == 0

    async def test_includes_multi_event_pubkeys(self, brotr: Brotr):
        """Pubkeys with 2+ events per relay are included."""
        ers = [
            # pubkey "11" has 3 events on pkr1 -> included
            _make_event_relay(
                event_id="d0" * 32,
                relay_url="wss://pkr1.example.com",
                pubkey="11" * 32,
            ),
            _make_event_relay(
                event_id="d1" * 32,
                relay_url="wss://pkr1.example.com",
                pubkey="11" * 32,
            ),
            _make_event_relay(
                event_id="d2" * 32,
                relay_url="wss://pkr1.example.com",
                pubkey="11" * 32,
            ),
            # pubkey "22" has 1 event on pkr1 -> excluded
            _make_event_relay(
                event_id="d3" * 32,
                relay_url="wss://pkr1.example.com",
                pubkey="22" * 32,
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("pubkey_counts_by_relay")

        rows = await brotr.fetch(
            "SELECT relay_url, pubkey, event_count FROM pubkey_counts_by_relay"
        )
        assert len(rows) == 1
        assert rows[0]["pubkey"] == "11" * 32
        assert rows[0]["event_count"] == 3


# ============================================================================
# network_stats
# ============================================================================


class TestNetworkStats:
    async def test_empty(self, brotr: Brotr):
        await brotr.refresh_materialized_view("network_stats")

        rows = await brotr.fetch("SELECT * FROM network_stats")
        assert len(rows) == 0

    async def test_clearnet_relay(self, brotr: Brotr):
        ers = [
            _make_event_relay(
                event_id=f"{i:064x}",
                relay_url="wss://net.example.com",
            )
            for i in range(3)
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("network_stats")

        rows = await brotr.fetch("SELECT * FROM network_stats WHERE network = $1", "clearnet")
        assert len(rows) == 1
        assert rows[0]["relay_count"] == 1
        assert rows[0]["event_count"] == 3

    async def test_multiple_networks(self, brotr: Brotr):
        ers = [
            _make_event_relay(
                event_id="e0" * 32,
                relay_url="wss://clearnet.example.com",
            ),
            _make_event_relay(
                event_id="e1" * 32,
                relay_url="ws://abc123abc123abc123abc123abc123abc123abc123abc123abcdefgh.onion",
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("network_stats")

        rows = await brotr.fetch("SELECT network, relay_count FROM network_stats ORDER BY network")
        networks = {row["network"]: row["relay_count"] for row in rows}
        assert networks["clearnet"] == 1
        assert networks["tor"] == 1


# ============================================================================
# relay_software_counts
# ============================================================================


class TestRelaySoftwareCounts:
    async def test_empty(self, brotr: Brotr):
        await brotr.refresh_materialized_view("relay_metadata_latest")
        await brotr.refresh_materialized_view("relay_software_counts")

        rows = await brotr.fetch("SELECT * FROM relay_software_counts")
        assert len(rows) == 0

    async def test_software_distribution(self, brotr: Brotr):
        # Insert relay + NIP-11 metadata for 3 relays
        for i, (url, sw, ver) in enumerate(
            [
                ("wss://sw1.example.com", "strfry", "1.0.0"),
                ("wss://sw2.example.com", "strfry", "1.0.0"),
                ("wss://sw3.example.com", "nostream", "2.0.0"),
            ]
        ):
            er = _make_event_relay(event_id=f"{0x50 + i:064x}", relay_url=url)
            await brotr.insert_event_relay([er], cascade=True)
            await _insert_nip11_metadata(brotr, url, {"software": sw, "version": ver})

        await brotr.refresh_materialized_view("relay_metadata_latest")
        await brotr.refresh_materialized_view("relay_software_counts")

        rows = await brotr.fetch(
            "SELECT software, version, relay_count"
            " FROM relay_software_counts ORDER BY relay_count DESC"
        )
        assert len(rows) == 2
        assert rows[0]["software"] == "strfry"
        assert rows[0]["relay_count"] == 2
        assert rows[1]["software"] == "nostream"
        assert rows[1]["relay_count"] == 1

    async def test_null_version_becomes_unknown(self, brotr: Brotr):
        er = _make_event_relay(event_id="51" * 32, relay_url="wss://nover.example.com")
        await brotr.insert_event_relay([er], cascade=True)
        await _insert_nip11_metadata(brotr, "wss://nover.example.com", {"software": "custom-relay"})
        await brotr.refresh_materialized_view("relay_metadata_latest")
        await brotr.refresh_materialized_view("relay_software_counts")

        rows = await brotr.fetch(
            "SELECT version FROM relay_software_counts WHERE software = $1",
            "custom-relay",
        )
        assert len(rows) == 1
        assert rows[0]["version"] == "unknown"


# ============================================================================
# supported_nip_counts
# ============================================================================


class TestSupportedNipCounts:
    async def test_empty(self, brotr: Brotr):
        await brotr.refresh_materialized_view("relay_metadata_latest")
        await brotr.refresh_materialized_view("supported_nip_counts")

        rows = await brotr.fetch("SELECT * FROM supported_nip_counts")
        assert len(rows) == 0

    async def test_nip_distribution(self, brotr: Brotr):
        for i, (url, nips) in enumerate(
            [
                ("wss://nip1.example.com", [1, 2, 4, 11]),
                ("wss://nip2.example.com", [1, 2, 9]),
            ]
        ):
            er = _make_event_relay(event_id=f"{0x60 + i:064x}", relay_url=url)
            await brotr.insert_event_relay([er], cascade=True)
            await _insert_nip11_metadata(
                brotr, url, {"supported_nips": nips}, generated_at=1700000001 + i
            )

        await brotr.refresh_materialized_view("relay_metadata_latest")
        await brotr.refresh_materialized_view("supported_nip_counts")

        rows = await brotr.fetch("SELECT nip, relay_count FROM supported_nip_counts ORDER BY nip")
        nips = {row["nip"]: row["relay_count"] for row in rows}
        assert nips[1] == 2  # both relays support NIP-1
        assert nips[2] == 2  # both relays support NIP-2
        assert nips[4] == 1  # only relay 1
        assert nips[9] == 1  # only relay 2
        assert nips[11] == 1  # only relay 1

    async def test_skips_missing_supported_nips(self, brotr: Brotr):
        er = _make_event_relay(event_id="62" * 32, relay_url="wss://nonips.example.com")
        await brotr.insert_event_relay([er], cascade=True)
        await _insert_nip11_metadata(brotr, "wss://nonips.example.com", {"name": "No NIPs listed"})
        await brotr.refresh_materialized_view("relay_metadata_latest")
        await brotr.refresh_materialized_view("supported_nip_counts")

        rows = await brotr.fetch("SELECT * FROM supported_nip_counts")
        assert len(rows) == 0


# ============================================================================
# event_daily_counts
# ============================================================================


class TestEventDailyCounts:
    async def test_empty(self, brotr: Brotr):
        await brotr.refresh_materialized_view("event_daily_counts")

        rows = await brotr.fetch("SELECT * FROM event_daily_counts")
        assert len(rows) == 0

    async def test_single_day(self, brotr: Brotr):
        ers = [
            _make_event_relay(
                event_id=f"{i:064x}",
                relay_url="wss://daily.example.com",
                created_at=1700000000 + i * 60,  # same day, minutes apart
            )
            for i in range(5)
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("event_daily_counts")

        rows = await brotr.fetch("SELECT * FROM event_daily_counts")
        assert len(rows) == 1
        assert rows[0]["event_count"] == 5

    async def test_multiple_days(self, brotr: Brotr):
        ers = [
            _make_event_relay(
                event_id=f"{i:064x}",
                relay_url="wss://multiday.example.com",
                created_at=1700000000 + i * 86400,  # 1 per day
            )
            for i in range(3)
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("event_daily_counts")

        rows = await brotr.fetch("SELECT day, event_count FROM event_daily_counts ORDER BY day")
        assert len(rows) == 3
        for row in rows:
            assert row["event_count"] == 1


# ============================================================================
# all_statistics_refresh
# ============================================================================


class TestAllStatisticsRefresh:
    async def test_refreshes_all_views(self, brotr: Brotr):
        # Insert event + relay data
        er = _make_event_relay(
            event_id="e0" * 32,
            relay_url="wss://allref.example.com",
        )
        await brotr.insert_event_relay([er], cascade=True)

        # Insert another event from same pubkey on same relay (for pubkey_counts_by_relay)
        er2 = _make_event_relay(
            event_id="e1" * 32,
            relay_url="wss://allref.example.com",
        )
        await brotr.insert_event_relay([er2], cascade=True)

        # Insert NIP-11 metadata with software and supported_nips
        await _insert_nip11_metadata(
            brotr,
            "wss://allref.example.com",
            {
                "name": "All Refresh",
                "software": "test-relay",
                "version": "0.1.0",
                "supported_nips": [1, 2, 11],
            },
        )

        await brotr.execute("SELECT all_statistics_refresh()")

        # Verify all 11 materialized views were refreshed
        es = await brotr.fetch("SELECT * FROM event_stats")
        assert es[0]["event_count"] == 2

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

        ns = await brotr.fetch("SELECT * FROM network_stats")
        assert len(ns) >= 1

        rsc = await brotr.fetch("SELECT * FROM relay_software_counts")
        assert len(rsc) >= 1

        snc = await brotr.fetch("SELECT * FROM supported_nip_counts")
        assert len(snc) >= 1

        edc = await brotr.fetch("SELECT * FROM event_daily_counts")
        assert len(edc) >= 1
