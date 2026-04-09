"""Integration tests for current-state and analytics tables."""

from __future__ import annotations

import time

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import EventRelay, Relay, RelayMetadata
from bigbrotr.models.event import Event
from bigbrotr.models.metadata import Metadata, MetadataType
from tests.conftest import make_mock_event


pytestmark = pytest.mark.integration


def _rm(
    relay_url: str,
    data: dict,
    meta_type: MetadataType = MetadataType.NIP11_INFO,
    generated_at: int = 1700000001,
) -> RelayMetadata:
    relay = Relay(relay_url, discovered_at=1700000000)
    metadata = Metadata(type=meta_type, data=data)
    return RelayMetadata(relay=relay, metadata=metadata, generated_at=generated_at)


async def _refresh_metadata_current(
    brotr: Brotr, after: int = 0, until: int = 2_000_000_000
) -> None:
    """Refresh relay metadata current-state facts with the given range."""
    await brotr.fetchval(
        "SELECT relay_metadata_current_refresh($1::BIGINT, $2::BIGINT)", after, until
    )


class TestRelayMetadataCurrent:
    async def test_empty_view(self, brotr: Brotr) -> None:
        await _refresh_metadata_current(brotr)
        rows = await brotr.fetch("SELECT * FROM relay_metadata_current")
        assert len(rows) == 0

    async def test_returns_latest_snapshot_by_generated_at(self, brotr: Brotr) -> None:
        rm_old = _rm("wss://latest1.example.com", {"name": "Old"}, generated_at=1700000001)
        rm_new = _rm("wss://latest1.example.com", {"name": "New"}, generated_at=1700000002)
        await brotr.insert_relay_metadata([rm_old, rm_new], cascade=True)
        await _refresh_metadata_current(brotr)

        row = await brotr.fetchrow(
            "SELECT * FROM relay_metadata_current WHERE relay_url = $1 AND metadata_type = $2",
            "wss://latest1.example.com",
            "nip11_info",
        )
        assert row is not None
        assert row["generated_at"] == 1700000002
        assert row["data"]["name"] == "New"

    async def test_multiple_types_per_relay(self, brotr: Brotr) -> None:
        rm_info = _rm("wss://multi-t.example.com", {"name": "Multi"})
        rm_ssl = _rm(
            "wss://multi-t.example.com",
            {"ssl_valid": True},
            MetadataType.NIP66_SSL,
        )
        await brotr.insert_relay_metadata([rm_info, rm_ssl], cascade=True)
        await _refresh_metadata_current(brotr)

        rows = await brotr.fetch(
            "SELECT metadata_type FROM relay_metadata_current "
            "WHERE relay_url = $1 ORDER BY metadata_type",
            "wss://multi-t.example.com",
        )
        assert len(rows) == 2
        assert {r["metadata_type"] for r in rows} == {"nip11_info", "nip66_ssl"}


# ============================================================================
# Helpers for current-state and analytics tables
# ============================================================================


def _event_relay(
    event_id: str,
    relay_url: str,
    kind: int = 1,
    pubkey: str = "bb" * 32,
    created_at: int = 1700000000,
    seen_at: int | None = None,
    tags: list[list[str]] | None = None,
) -> EventRelay:
    mock = make_mock_event(
        event_id=event_id,
        pubkey=pubkey,
        kind=kind,
        created_at=created_at,
        sig="ee" * 64,
        tags=tags,
    )
    relay = Relay(relay_url, discovered_at=1700000000)
    return EventRelay(event=Event(mock), relay=relay, seen_at=seen_at or created_at + 1)


def _nip11_metadata(relay_url: str, data: dict, generated_at: int = 1700000001) -> RelayMetadata:
    relay = Relay(relay_url, discovered_at=1700000000)
    envelope = {"data": data, "logs": {"success": True}}
    metadata = Metadata(type=MetadataType.NIP11_INFO, data=envelope)
    return RelayMetadata(relay=relay, metadata=metadata, generated_at=generated_at)


def _nip66_metadata(
    relay_url: str, meta_type: MetadataType, data: dict, generated_at: int = 1700000001
) -> RelayMetadata:
    relay = Relay(relay_url, discovered_at=1700000000)
    envelope = {"data": data, "logs": {"success": True}}
    metadata = Metadata(type=meta_type, data=envelope)
    return RelayMetadata(relay=relay, metadata=metadata, generated_at=generated_at)


async def _refresh_summaries(brotr: Brotr, after: int = 0, until: int = 2000000000) -> None:
    """Refresh all summary tables with the given range."""
    for table in [
        "pubkey_kind_stats",
        "pubkey_relay_stats",
        "relay_kind_stats",
        "pubkey_stats",
        "kind_stats",
        "relay_stats",
    ]:
        await brotr.fetchval(f"SELECT {table}_refresh($1::BIGINT, $2::BIGINT)", after, until)


async def _refresh_nip85(brotr: Brotr, after: int = 0, until: int = 2000000000) -> None:
    """Refresh NIP-85 summary tables with the given range."""
    for table in ["nip85_pubkey_stats", "nip85_event_stats"]:
        await brotr.fetchval(f"SELECT {table}_refresh($1::BIGINT, $2::BIGINT)", after, until)


async def _refresh_current_events(brotr: Brotr, after: int = 0, until: int = 2000000000) -> None:
    """Refresh current-state replaceable/addressable tables with the given range."""
    for table in ["events_replaceable_current", "events_addressable_current"]:
        await brotr.fetchval(f"SELECT {table}_refresh($1::BIGINT, $2::BIGINT)", after, until)


async def _refresh_contact_graph(brotr: Brotr, after: int = 0, until: int = 2000000000) -> None:
    """Refresh canonical contact-list facts after refreshing replaceable current state."""
    await brotr.fetchval(
        "SELECT events_replaceable_current_refresh($1::BIGINT, $2::BIGINT)", after, until
    )
    for table in ["contact_lists_current", "contact_list_edges_current"]:
        await brotr.fetchval(f"SELECT {table}_refresh($1::BIGINT, $2::BIGINT)", after, until)


# ============================================================================
# Summary tables: cross-tabulations
# ============================================================================


class TestPubkeyKindStats:
    async def test_pubkey_with_multiple_kinds(self, brotr: Brotr):
        ers = [
            _event_relay("a0" * 32, "wss://pks.example.com", pubkey="11" * 32, kind=1),
            _event_relay("a1" * 32, "wss://pks.example.com", pubkey="11" * 32, kind=1),
            _event_relay("a2" * 32, "wss://pks.example.com", pubkey="11" * 32, kind=7),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_summaries(brotr)

        rows = await brotr.fetch(
            "SELECT kind, event_count FROM pubkey_kind_stats WHERE pubkey = $1 ORDER BY kind",
            "11" * 32,
        )
        assert len(rows) == 2
        assert rows[0]["kind"] == 1
        assert rows[0]["event_count"] == 2
        assert rows[1]["kind"] == 7
        assert rows[1]["event_count"] == 1

    async def test_incremental_accumulates(self, brotr: Brotr):
        er1 = _event_relay(
            "b0" * 32, "wss://pks2.example.com", pubkey="22" * 32, kind=1, seen_at=100
        )
        await brotr.insert_event_relay([er1], cascade=True)
        await brotr.fetchval("SELECT pubkey_kind_stats_refresh($1::BIGINT, $2::BIGINT)", 0, 200)

        er2 = _event_relay(
            "b1" * 32, "wss://pks2.example.com", pubkey="22" * 32, kind=1, seen_at=300
        )
        await brotr.insert_event_relay([er2], cascade=True)
        await brotr.fetchval("SELECT pubkey_kind_stats_refresh($1::BIGINT, $2::BIGINT)", 200, 400)

        rows = await brotr.fetch(
            "SELECT event_count FROM pubkey_kind_stats WHERE pubkey = $1 AND kind = $2",
            "22" * 32,
            1,
        )
        assert rows[0]["event_count"] == 2

    async def test_deduplicates_cross_relay(self, brotr: Brotr):
        er1 = _event_relay("c0" * 32, "wss://pks3a.example.com", pubkey="33" * 32, seen_at=100)
        er2 = _event_relay("c0" * 32, "wss://pks3b.example.com", pubkey="33" * 32, seen_at=200)
        await brotr.insert_event_relay([er1], cascade=True)
        await brotr.fetchval("SELECT pubkey_kind_stats_refresh($1::BIGINT, $2::BIGINT)", 0, 150)

        await brotr.insert_event_relay([er2], cascade=True)
        await brotr.fetchval("SELECT pubkey_kind_stats_refresh($1::BIGINT, $2::BIGINT)", 150, 300)

        rows = await brotr.fetch(
            "SELECT event_count FROM pubkey_kind_stats WHERE pubkey = $1",
            "33" * 32,
        )
        assert rows[0]["event_count"] == 1


class TestPubkeyRelayStats:
    async def test_pubkey_on_multiple_relays(self, brotr: Brotr):
        ers = [
            _event_relay("d0" * 32, "wss://prs1.example.com", pubkey="11" * 32),
            _event_relay("d1" * 32, "wss://prs1.example.com", pubkey="11" * 32),
            _event_relay("d2" * 32, "wss://prs2.example.com", pubkey="11" * 32),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_summaries(brotr)

        rows = await brotr.fetch(
            "SELECT relay_url, event_count FROM pubkey_relay_stats"
            " WHERE pubkey = $1 ORDER BY relay_url",
            "11" * 32,
        )
        assert len(rows) == 2
        counts = {r["relay_url"]: r["event_count"] for r in rows}
        assert counts["wss://prs1.example.com"] == 2
        assert counts["wss://prs2.example.com"] == 1

    async def test_same_event_new_relay_counted(self, brotr: Brotr):
        er1 = _event_relay("e0" * 32, "wss://prs3a.example.com", pubkey="22" * 32, seen_at=100)
        await brotr.insert_event_relay([er1], cascade=True)
        await brotr.fetchval("SELECT pubkey_relay_stats_refresh($1::BIGINT, $2::BIGINT)", 0, 150)

        er2 = _event_relay("e0" * 32, "wss://prs3b.example.com", pubkey="22" * 32, seen_at=200)
        await brotr.insert_event_relay([er2], cascade=True)
        await brotr.fetchval("SELECT pubkey_relay_stats_refresh($1::BIGINT, $2::BIGINT)", 150, 300)

        rows = await brotr.fetch(
            "SELECT relay_url FROM pubkey_relay_stats WHERE pubkey = $1 ORDER BY relay_url",
            "22" * 32,
        )
        assert len(rows) == 2


class TestRelayKindStats:
    async def test_per_relay_kind_distribution(self, brotr: Brotr):
        ers = [
            _event_relay("b0" * 32, "wss://rks1.example.com", kind=1),
            _event_relay("b1" * 32, "wss://rks1.example.com", kind=1),
            _event_relay("b2" * 32, "wss://rks2.example.com", kind=3),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_summaries(brotr)

        rows = await brotr.fetch(
            "SELECT relay_url, kind, event_count FROM relay_kind_stats ORDER BY relay_url, kind"
        )
        assert len(rows) == 2
        assert rows[0]["relay_url"] == "wss://rks1.example.com"
        assert rows[0]["kind"] == 1
        assert rows[0]["event_count"] == 2


# ============================================================================
# Summary tables: entity views
# ============================================================================


class TestPubkeyStats:
    async def test_event_counts_per_pubkey(self, brotr: Brotr):
        ers = [
            _event_relay("c0" * 32, "wss://ps.example.com", pubkey="11" * 32),
            _event_relay("c1" * 32, "wss://ps.example.com", pubkey="11" * 32),
            _event_relay("c2" * 32, "wss://ps.example.com", pubkey="22" * 32),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_summaries(brotr)

        rows = await brotr.fetch(
            "SELECT pubkey, event_count FROM pubkey_stats ORDER BY event_count DESC"
        )
        assert len(rows) == 2
        assert rows[0]["pubkey"] == "11" * 32
        assert rows[0]["event_count"] == 2

    async def test_unique_kinds_from_crosstab(self, brotr: Brotr):
        ers = [
            _event_relay("e0" * 32, "wss://uk.example.com", pubkey="44" * 32, kind=1),
            _event_relay("e1" * 32, "wss://uk.example.com", pubkey="44" * 32, kind=7),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_summaries(brotr)

        rows = await brotr.fetch(
            "SELECT unique_kinds FROM pubkey_stats WHERE pubkey = $1", "44" * 32
        )
        assert rows[0]["unique_kinds"] == 2

    async def test_unique_relays_from_crosstab(self, brotr: Brotr):
        ers = [
            _event_relay("f0" * 32, "wss://r1.example.com", pubkey="55" * 32),
            _event_relay("f1" * 32, "wss://r2.example.com", pubkey="55" * 32),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_summaries(brotr)

        rows = await brotr.fetch(
            "SELECT unique_relays FROM pubkey_stats WHERE pubkey = $1", "55" * 32
        )
        assert rows[0]["unique_relays"] == 2

    async def test_unique_relays_updates_on_new_relay_for_existing_event(self, brotr: Brotr):
        event_id = "f2" * 32
        er1 = _event_relay(
            event_id,
            "wss://r3a.example.com",
            pubkey="56" * 32,
            seen_at=100,
        )
        await brotr.insert_event_relay([er1], cascade=True)
        await _refresh_summaries(brotr, after=0, until=150)

        er2 = _event_relay(
            event_id,
            "wss://r3b.example.com",
            pubkey="56" * 32,
            seen_at=200,
        )
        await brotr.insert_event_relay([er2], cascade=True)
        await _refresh_summaries(brotr, after=150, until=250)

        row = await brotr.fetchrow(
            "SELECT event_count, unique_relays FROM pubkey_stats WHERE pubkey = $1",
            "56" * 32,
        )
        assert row is not None
        assert row["event_count"] == 1
        assert row["unique_relays"] == 2

    async def test_nip01_category_breakdown(self, brotr: Brotr):
        ers = [
            _event_relay("ca" * 32, "wss://cat.example.com", pubkey="66" * 32, kind=1),
            _event_relay("cb" * 32, "wss://cat.example.com", pubkey="66" * 32, kind=0),
            _event_relay("cc" * 32, "wss://cat.example.com", pubkey="66" * 32, kind=20000),
            _event_relay("cd" * 32, "wss://cat.example.com", pubkey="66" * 32, kind=30000),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_summaries(brotr)

        row = await brotr.fetchrow(
            "SELECT regular_count, replaceable_count, ephemeral_count, addressable_count"
            " FROM pubkey_stats WHERE pubkey = $1",
            "66" * 32,
        )
        assert row["regular_count"] == 1
        assert row["replaceable_count"] == 1
        assert row["ephemeral_count"] == 1
        assert row["addressable_count"] == 1


class TestKindStats:
    async def test_multiple_kinds(self, brotr: Brotr):
        ers = [
            _event_relay("a0" * 32, "wss://ks.example.com", kind=1),
            _event_relay("a1" * 32, "wss://ks.example.com", kind=1),
            _event_relay("a2" * 32, "wss://ks.example.com", kind=3),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_summaries(brotr)

        rows = await brotr.fetch("SELECT kind, event_count FROM kind_stats ORDER BY kind")
        counts = {row["kind"]: row["event_count"] for row in rows}
        assert counts[1] == 2
        assert counts[3] == 1

    async def test_category_labels(self, brotr: Brotr):
        ers = [
            _event_relay("ca" * 32, "wss://kcat.example.com", kind=1),
            _event_relay("cb" * 32, "wss://kcat.example.com", kind=0),
            _event_relay("cc" * 32, "wss://kcat.example.com", kind=20000),
            _event_relay("cd" * 32, "wss://kcat.example.com", kind=30000),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_summaries(brotr)

        rows = await brotr.fetch("SELECT kind, category FROM kind_stats ORDER BY kind")
        categories = {row["kind"]: row["category"] for row in rows}
        assert categories[0] == "replaceable"
        assert categories[1] == "regular"
        assert categories[20000] == "ephemeral"
        assert categories[30000] == "addressable"

    async def test_unique_relays_from_crosstab(self, brotr: Brotr):
        ers = [
            _event_relay("d0" * 32, "wss://kr1.example.com", kind=1),
            _event_relay("d1" * 32, "wss://kr2.example.com", kind=1),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_summaries(brotr)

        rows = await brotr.fetch("SELECT unique_relays FROM kind_stats WHERE kind = $1", 1)
        assert rows[0]["unique_relays"] == 2

    async def test_unique_relays_updates_on_new_relay_for_existing_event(self, brotr: Brotr):
        event_id = "d2" * 32
        er1 = _event_relay(event_id, "wss://kr3a.example.com", kind=7, seen_at=100)
        await brotr.insert_event_relay([er1], cascade=True)
        await _refresh_summaries(brotr, after=0, until=150)

        er2 = _event_relay(event_id, "wss://kr3b.example.com", kind=7, seen_at=200)
        await brotr.insert_event_relay([er2], cascade=True)
        await _refresh_summaries(brotr, after=150, until=250)

        row = await brotr.fetchrow(
            "SELECT event_count, unique_relays FROM kind_stats WHERE kind = $1",
            7,
        )
        assert row is not None
        assert row["event_count"] == 1
        assert row["unique_relays"] == 2

    async def test_unique_pubkeys_from_crosstab(self, brotr: Brotr):
        ers = [
            _event_relay("e0" * 32, "wss://kup.example.com", kind=7, pubkey="11" * 32),
            _event_relay("e1" * 32, "wss://kup.example.com", kind=7, pubkey="22" * 32),
            _event_relay("e2" * 32, "wss://kup.example.com", kind=7, pubkey="22" * 32),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_summaries(brotr)

        rows = await brotr.fetch("SELECT unique_pubkeys FROM kind_stats WHERE kind = $1", 7)
        assert rows[0]["unique_pubkeys"] == 2


class TestRelayStats:
    async def test_event_counts_per_relay(self, brotr: Brotr):
        ers = [
            _event_relay("b0" * 32, "wss://r1.example.com"),
            _event_relay("b1" * 32, "wss://r1.example.com", pubkey="cc" * 32),
            _event_relay("b2" * 32, "wss://r2.example.com"),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_summaries(brotr)

        rows = await brotr.fetch(
            "SELECT relay_url, event_count FROM relay_stats ORDER BY relay_url"
        )
        counts = {row["relay_url"]: row["event_count"] for row in rows}
        assert counts["wss://r1.example.com"] == 2
        assert counts["wss://r2.example.com"] == 1

    async def test_nip01_category_breakdown(self, brotr: Brotr):
        ers = [
            _event_relay("ca" * 32, "wss://rscat.example.com", kind=1),
            _event_relay("cb" * 32, "wss://rscat.example.com", kind=0),
            _event_relay("cc" * 32, "wss://rscat.example.com", kind=20000),
            _event_relay("cd" * 32, "wss://rscat.example.com", kind=30000),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_summaries(brotr)

        row = await brotr.fetchrow(
            "SELECT regular_count, replaceable_count, ephemeral_count, addressable_count"
            " FROM relay_stats WHERE relay_url = $1",
            "wss://rscat.example.com",
        )
        assert row["regular_count"] == 1
        assert row["replaceable_count"] == 1
        assert row["ephemeral_count"] == 1
        assert row["addressable_count"] == 1

    async def test_unique_pubkeys_from_crosstab(self, brotr: Brotr):
        ers = [
            _event_relay("e0" * 32, "wss://rup.example.com", pubkey="11" * 32),
            _event_relay("e1" * 32, "wss://rup.example.com", pubkey="22" * 32),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_summaries(brotr)

        row = await brotr.fetchrow(
            "SELECT unique_pubkeys, unique_kinds FROM relay_stats WHERE relay_url = $1",
            "wss://rup.example.com",
        )
        assert row["unique_pubkeys"] == 2
        assert row["unique_kinds"] == 1

    async def test_metadata_refresh_seeds_new_relay(self, brotr: Brotr):
        er = _event_relay("f0" * 32, "wss://meta.example.com")
        await brotr.insert_event_relay([er], cascade=True)

        rm = _nip11_metadata(
            "wss://meta.example.com",
            {"name": "Test", "software": "strfry", "version": "2.0"},
        )
        await brotr.insert_relay_metadata([rm], cascade=True)
        await _refresh_metadata_current(brotr)
        await brotr.execute("SELECT relay_stats_metadata_refresh()")

        row = await brotr.fetchrow(
            "SELECT nip11_name, nip11_software FROM relay_stats WHERE relay_url = $1",
            "wss://meta.example.com",
        )
        assert row is not None
        assert row["nip11_name"] == "Test"
        assert row["nip11_software"] == "strfry"

    async def test_avg_rtt(self, brotr: Brotr):
        er = _event_relay("a0" * 32, "wss://rtt.example.com")
        await brotr.insert_event_relay([er], cascade=True)

        for i, rtt in enumerate([100, 200, 300]):
            rm = _nip66_metadata(
                "wss://rtt.example.com",
                MetadataType.NIP66_RTT,
                {"rtt_open": rtt, "rtt_read": rtt + 10, "rtt_write": rtt + 20},
                generated_at=1700000001 + i,
            )
            await brotr.insert_relay_metadata([rm], cascade=True)

        await brotr.execute("SELECT relay_stats_metadata_refresh()")

        row = await brotr.fetchrow(
            "SELECT avg_rtt_open, avg_rtt_read, avg_rtt_write"
            " FROM relay_stats WHERE relay_url = $1",
            "wss://rtt.example.com",
        )
        assert float(row["avg_rtt_open"]) == 200.0
        assert float(row["avg_rtt_read"]) == 210.0
        assert float(row["avg_rtt_write"]) == 220.0

    async def test_metadata_refresh_deletes_removed_relay_rows(self, brotr: Brotr):
        er = _event_relay("a1" * 32, "wss://deleted-relay.example.com")
        await brotr.insert_event_relay([er], cascade=True)
        await _refresh_summaries(brotr)

        assert (
            await brotr.fetchval(
                "SELECT count(*) FROM relay_stats WHERE relay_url = $1",
                "wss://deleted-relay.example.com",
            )
            == 1
        )

        await brotr.execute("DELETE FROM relay WHERE url = $1", "wss://deleted-relay.example.com")
        await brotr.execute("SELECT relay_stats_metadata_refresh()")

        assert (
            await brotr.fetchval(
                "SELECT count(*) FROM relay_stats WHERE relay_url = $1",
                "wss://deleted-relay.example.com",
            )
            == 0
        )


# ============================================================================
# Rolling windows
# ============================================================================


class TestRollingWindows:
    async def test_pubkey_stats_windows(self, brotr: Brotr):
        now = int(time.time())
        ers = [
            _event_relay("f1" * 32, "wss://tw.example.com", pubkey="77" * 32, created_at=now - 600),
            _event_relay(
                "f2" * 32, "wss://tw.example.com", pubkey="77" * 32, created_at=now - 1800
            ),
            _event_relay(
                "f3" * 32, "wss://tw.example.com", pubkey="77" * 32, created_at=now - 43200
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_summaries(brotr)
        await brotr.execute("SELECT rolling_windows_refresh()")

        row = await brotr.fetchrow(
            "SELECT events_last_24h, events_last_7d, events_last_30d"
            " FROM pubkey_stats WHERE pubkey = $1",
            "77" * 32,
        )
        assert row["events_last_24h"] == 3
        assert row["events_last_7d"] == 3
        assert row["events_last_30d"] == 3

    async def test_kind_stats_windows(self, brotr: Brotr):
        now = int(time.time())
        ers = [
            _event_relay("a1" * 32, "wss://tw2.example.com", kind=7, created_at=now - 600),
            _event_relay("a2" * 32, "wss://tw2.example.com", kind=7, created_at=now - 1800),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_summaries(brotr)
        await brotr.execute("SELECT rolling_windows_refresh()")

        row = await brotr.fetchrow(
            "SELECT events_last_24h, events_last_7d FROM kind_stats WHERE kind = $1", 7
        )
        assert row["events_last_24h"] == 2
        assert row["events_last_7d"] == 2

    async def test_relay_stats_windows(self, brotr: Brotr):
        now = int(time.time())
        ers = [
            _event_relay("b1" * 32, "wss://tw3.example.com", created_at=now - 600),
            _event_relay("b2" * 32, "wss://tw3.example.com", created_at=now - 43200),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_summaries(brotr)
        await brotr.execute("SELECT rolling_windows_refresh()")

        row = await brotr.fetchrow(
            "SELECT events_last_24h, events_last_30d FROM relay_stats WHERE relay_url = $1",
            "wss://tw3.example.com",
        )
        assert row["events_last_24h"] == 2
        assert row["events_last_30d"] == 2

    async def test_relay_stats_windows_use_seen_at_not_created_at(self, brotr: Brotr):
        now = int(time.time())
        er = _event_relay(
            "b3" * 32,
            "wss://tw4.example.com",
            pubkey="78" * 32,
            created_at=now - 40 * 86400,
            seen_at=now - 60,
        )
        await brotr.insert_event_relay([er], cascade=True)
        await _refresh_summaries(brotr, after=0, until=now)
        await brotr.execute("SELECT rolling_windows_refresh()")

        relay_row = await brotr.fetchrow(
            "SELECT events_last_24h, events_last_30d FROM relay_stats WHERE relay_url = $1",
            "wss://tw4.example.com",
        )
        assert relay_row is not None
        assert relay_row["events_last_24h"] == 1
        assert relay_row["events_last_30d"] == 1

        pubkey_row = await brotr.fetchrow(
            "SELECT events_last_24h, events_last_30d FROM pubkey_stats WHERE pubkey = $1",
            "78" * 32,
        )
        assert pubkey_row is not None
        assert pubkey_row["events_last_24h"] == 0
        assert pubkey_row["events_last_30d"] == 0


# -- relay_software_counts --


class TestRelaySoftwareCounts:
    async def test_software_distribution(self, brotr: Brotr):
        relays = [
            ("wss://sw1.example.com", "strfry", "1.0.0"),
            ("wss://sw2.example.com", "strfry", "1.0.0"),
            ("wss://sw3.example.com", "nostream", "2.0.0"),
        ]
        for i, (url, sw, ver) in enumerate(relays):
            er = _event_relay(f"{0x50 + i:064x}", url)
            await brotr.insert_event_relay([er], cascade=True)
            rm = _nip11_metadata(url, {"software": sw, "version": ver})
            await brotr.insert_relay_metadata([rm], cascade=True)

        await _refresh_metadata_current(brotr)
        await brotr.fetchval(
            "SELECT relay_software_counts_refresh($1::BIGINT, $2::BIGINT)", 0, 2_000_000_000
        )

        rows = await brotr.fetch(
            "SELECT software, relay_count FROM relay_software_counts ORDER BY relay_count DESC"
        )
        assert rows[0]["software"] == "strfry"
        assert rows[0]["relay_count"] == 2


# -- supported_nip_counts --


class TestSupportedNipCounts:
    async def test_nip_distribution(self, brotr: Brotr):
        relay_nips = [
            ("wss://nip1.example.com", [1, 2, 4, 11]),
            ("wss://nip2.example.com", [1, 2, 9]),
        ]
        for i, (url, nips) in enumerate(relay_nips):
            er = _event_relay(f"{0x60 + i:064x}", url)
            await brotr.insert_event_relay([er], cascade=True)
            rm = _nip11_metadata(url, {"supported_nips": nips}, generated_at=1700000001 + i)
            await brotr.insert_relay_metadata([rm], cascade=True)

        await _refresh_metadata_current(brotr)
        await brotr.fetchval(
            "SELECT supported_nip_counts_refresh($1::BIGINT, $2::BIGINT)", 0, 2_000_000_000
        )

        rows = await brotr.fetch("SELECT nip, relay_count FROM supported_nip_counts ORDER BY nip")
        nips = {row["nip"]: row["relay_count"] for row in rows}
        assert nips[1] == 2
        assert nips[2] == 2


# -- daily_counts --


class TestEventDailyCounts:
    async def test_events_on_different_days(self, brotr: Brotr):
        ers = [
            _event_relay(
                event_id=f"{i:064x}",
                relay_url="wss://daily.example.com",
                created_at=1700000000 + i * 86400,
            )
            for i in range(3)
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.fetchval(
            "SELECT daily_counts_refresh($1::BIGINT, $2::BIGINT)", 0, 2_000_000_000
        )

        rows = await brotr.fetch("SELECT day, event_count FROM daily_counts ORDER BY day")
        assert len(rows) == 3
        for row in rows:
            assert row["event_count"] == 1


# -- events_replaceable_current --


class TestEventsReplaceableCurrent:
    async def test_current_profile_per_pubkey(self, brotr: Brotr) -> None:
        pubkey = "aa" * 32
        ers = [
            _event_relay(
                "a0" * 32, "wss://repl.example.com", kind=0, pubkey=pubkey, created_at=1000
            ),
            _event_relay(
                "a1" * 32, "wss://repl.example.com", kind=0, pubkey=pubkey, created_at=2000
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.fetchval(
            "SELECT events_replaceable_current_refresh($1::BIGINT, $2::BIGINT)", 0, 5000
        )

        rows = await brotr.fetch(
            "SELECT created_at FROM events_replaceable_current WHERE kind = 0 AND pubkey = $1",
            bytes.fromhex(pubkey),
        )
        assert len(rows) == 1
        assert rows[0]["created_at"] == 2000

    async def test_excludes_non_replaceable_kinds(self, brotr: Brotr) -> None:
        ers = [
            _event_relay("f0" * 32, "wss://repl.example.com", kind=1, created_at=1000),
            _event_relay("f1" * 32, "wss://repl.example.com", kind=20000, created_at=1001),
            _event_relay("f2" * 32, "wss://repl.example.com", kind=30000, created_at=1002),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.fetchval(
            "SELECT events_replaceable_current_refresh($1::BIGINT, $2::BIGINT)", 0, 5000
        )

        rows = await brotr.fetch("SELECT * FROM events_replaceable_current")
        assert len(rows) == 0


# -- events_addressable_current --


class TestEventsAddressableCurrent:
    async def test_current_per_pubkey_kind_dtag(self, brotr: Brotr) -> None:
        pubkey = "aa" * 32
        d_tags = [["d", "my-article"]]
        ers = [
            _event_relay(
                "a0" * 32,
                "wss://addr.example.com",
                kind=30023,
                pubkey=pubkey,
                created_at=1000,
                tags=d_tags,
            ),
            _event_relay(
                "a1" * 32,
                "wss://addr.example.com",
                kind=30023,
                pubkey=pubkey,
                created_at=2000,
                tags=d_tags,
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.fetchval(
            "SELECT events_addressable_current_refresh($1::BIGINT, $2::BIGINT)", 0, 5000
        )

        rows = await brotr.fetch(
            "SELECT created_at, d_tag FROM events_addressable_current"
            " WHERE kind = 30023 AND pubkey = $1",
            bytes.fromhex(pubkey),
        )
        assert len(rows) == 1
        assert rows[0]["created_at"] == 2000
        assert rows[0]["d_tag"] == "my-article"

    async def test_event_without_dtag_uses_empty_string(self, brotr: Brotr) -> None:
        er = _event_relay(
            "d0" * 32,
            "wss://addr2.example.com",
            kind=30078,
            pubkey="dd" * 32,
            created_at=1000,
        )
        await brotr.insert_event_relay([er], cascade=True)
        await brotr.fetchval(
            "SELECT events_addressable_current_refresh($1::BIGINT, $2::BIGINT)", 0, 5000
        )

        rows = await brotr.fetch("SELECT d_tag FROM events_addressable_current WHERE kind = 30078")
        assert len(rows) == 1
        assert rows[0]["d_tag"] == ""

    async def test_first_dtag_wins_when_multiple_d_tags_present(self, brotr: Brotr) -> None:
        er = _event_relay(
            "d1" * 32,
            "wss://addr2.example.com",
            kind=30023,
            pubkey="de" * 32,
            created_at=1000,
            tags=[["d", "first"], ["d", "second"]],
        )
        await brotr.insert_event_relay([er], cascade=True)
        await brotr.fetchval(
            "SELECT events_addressable_current_refresh($1::BIGINT, $2::BIGINT)", 0, 5000
        )

        row = await brotr.fetchrow(
            "SELECT d_tag FROM events_addressable_current WHERE id = $1",
            bytes.fromhex("d1" * 32),
        )
        assert row is not None
        assert row["d_tag"] == "first"

    async def test_excludes_non_addressable_kinds(self, brotr: Brotr) -> None:
        ers = [
            _event_relay("c0" * 32, "wss://addr.example.com", kind=1, created_at=1000),
            _event_relay("c1" * 32, "wss://addr.example.com", kind=0, created_at=1001),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.fetchval(
            "SELECT events_addressable_current_refresh($1::BIGINT, $2::BIGINT)", 0, 5000
        )

        rows = await brotr.fetch("SELECT * FROM events_addressable_current")
        assert len(rows) == 0


# ============================================================================
# NIP-85 summary tables
# ============================================================================


class TestBolt11AmountMsats:
    async def test_supports_mainnet_and_case_insensitive_prefix(self, brotr: Brotr) -> None:
        assert await brotr.fetchval("SELECT bolt11_amount_msats($1)", "lnbc21000n1qqq") == 2_100_000
        assert await brotr.fetchval("SELECT bolt11_amount_msats($1)", "LNBC21000N1qqq") == 2_100_000

    async def test_supports_testnet_signet_and_regtest_prefixes(self, brotr: Brotr) -> None:
        assert await brotr.fetchval("SELECT bolt11_amount_msats($1)", "lntb21000n1qqq") == 2_100_000
        assert (
            await brotr.fetchval("SELECT bolt11_amount_msats($1)", "lntbs21000n1qqq") == 2_100_000
        )
        assert (
            await brotr.fetchval("SELECT bolt11_amount_msats($1)", "lnbcrt21000n1qqq") == 2_100_000
        )

    async def test_returns_null_for_any_amount_or_malformed_values(self, brotr: Brotr) -> None:
        assert await brotr.fetchval("SELECT bolt11_amount_msats($1)", "lnbc1qqq") is None
        assert await brotr.fetchval("SELECT bolt11_amount_msats($1)", "not-a-bolt11") is None
        assert await brotr.fetchval("SELECT bolt11_amount_msats($1)", "lnxx21000n1qqq") is None

    async def test_returns_null_for_overflow_amounts(self, brotr: Brotr) -> None:
        assert (
            await brotr.fetchval(
                "SELECT bolt11_amount_msats($1)",
                "lnbc9999999999999999999999999999999991qqq",
            )
            is None
        )


class TestNip85PubkeyStats:
    async def test_post_and_reply_counts(self, brotr: Brotr) -> None:
        pubkey = "c1" * 32
        ers = [
            _event_relay("b0" * 32, "wss://n85.example.com", kind=1, pubkey=pubkey, tags=[]),
            _event_relay(
                "b1" * 32,
                "wss://n85.example.com",
                kind=1,
                pubkey=pubkey,
                tags=[["e", "aa" * 32]],
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_nip85(brotr)

        row = await brotr.fetchrow(
            "SELECT post_count, reply_count FROM nip85_pubkey_stats WHERE pubkey = $1",
            pubkey,
        )
        assert row is not None
        assert row["post_count"] == 2
        assert row["reply_count"] == 1

    async def test_reaction_counts(self, brotr: Brotr) -> None:
        author = "c2" * 32
        target = "c3" * 32
        ers = [
            _event_relay(
                "b2" * 32,
                "wss://n85.example.com",
                kind=7,
                pubkey=author,
                tags=[["p", target]],
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_nip85(brotr)

        author_row = await brotr.fetchrow(
            "SELECT reaction_count_sent FROM nip85_pubkey_stats WHERE pubkey = $1",
            author,
        )
        assert author_row is not None
        assert author_row["reaction_count_sent"] == 1

        target_row = await brotr.fetchrow(
            "SELECT reaction_count_recd FROM nip85_pubkey_stats WHERE pubkey = $1",
            target,
        )
        assert target_row is not None
        assert target_row["reaction_count_recd"] == 1

    async def test_reaction_received_uses_first_p_when_tags_present(self, brotr: Brotr) -> None:
        first_target = "c3" * 32
        second_target = "c4" * 32
        er = _event_relay(
            "b20" * 32,
            "wss://n85.example.com",
            kind=7,
            pubkey="c2" * 32,
            tags=[["p", first_target], ["p", second_target]],
        )
        await brotr.insert_event_relay([er], cascade=True)
        await _refresh_nip85(brotr)

        first_row = await brotr.fetchrow(
            "SELECT reaction_count_recd FROM nip85_pubkey_stats WHERE pubkey = $1",
            first_target,
        )
        second_row = await brotr.fetchrow(
            "SELECT reaction_count_recd FROM nip85_pubkey_stats WHERE pubkey = $1",
            second_target,
        )
        assert first_row is not None
        assert first_row["reaction_count_recd"] == 1
        assert second_row is None or second_row["reaction_count_recd"] == 0

    async def test_report_counts(self, brotr: Brotr) -> None:
        reporter = "c4" * 32
        reported = "c5" * 32
        ers = [
            _event_relay(
                "b3" * 32,
                "wss://n85.example.com",
                kind=1984,
                pubkey=reporter,
                tags=[["p", reported]],
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_nip85(brotr)

        row_sent = await brotr.fetchrow(
            "SELECT report_count_sent FROM nip85_pubkey_stats WHERE pubkey = $1",
            reporter,
        )
        assert row_sent is not None
        assert row_sent["report_count_sent"] == 1

        row_recd = await brotr.fetchrow(
            "SELECT report_count_recd FROM nip85_pubkey_stats WHERE pubkey = $1",
            reported,
        )
        assert row_recd is not None
        assert row_recd["report_count_recd"] == 1

    async def test_report_received_uses_first_p_when_tags_present(self, brotr: Brotr) -> None:
        first_target = "c5" * 32
        second_target = "c6" * 32
        er = _event_relay(
            "b21" * 32,
            "wss://n85.example.com",
            kind=1984,
            pubkey="c4" * 32,
            tags=[["p", first_target], ["p", second_target]],
        )
        await brotr.insert_event_relay([er], cascade=True)
        await _refresh_nip85(brotr)

        first_row = await brotr.fetchrow(
            "SELECT report_count_recd FROM nip85_pubkey_stats WHERE pubkey = $1",
            first_target,
        )
        second_row = await brotr.fetchrow(
            "SELECT report_count_recd FROM nip85_pubkey_stats WHERE pubkey = $1",
            second_target,
        )
        assert first_row is not None
        assert first_row["report_count_recd"] == 1
        assert second_row is None or second_row["report_count_recd"] == 0

    async def test_repost_counts(self, brotr: Brotr) -> None:
        reposter = "c6" * 32
        original_author = "c7" * 32
        original_event_id = "b4" * 32
        # First create the original event so the lookup works
        ers = [
            _event_relay(
                original_event_id,
                "wss://n85.example.com",
                kind=1,
                pubkey=original_author,
            ),
            _event_relay(
                "b5" * 32,
                "wss://n85.example.com",
                kind=6,
                pubkey=reposter,
                tags=[["e", original_event_id]],
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_nip85(brotr)

        sent_row = await brotr.fetchrow(
            "SELECT repost_count_sent FROM nip85_pubkey_stats WHERE pubkey = $1",
            reposter,
        )
        assert sent_row is not None
        assert sent_row["repost_count_sent"] == 1

        recd_row = await brotr.fetchrow(
            "SELECT repost_count_recd FROM nip85_pubkey_stats WHERE pubkey = $1",
            original_author,
        )
        assert recd_row is not None
        assert recd_row["repost_count_recd"] == 1

    async def test_activity_hours_heatmap(self, brotr: Brotr) -> None:
        pubkey = "c8" * 32
        # created_at at 14:00 UTC (14 * 3600 = 50400 seconds into day)
        created_at = 1700000000 - (1700000000 % 86400) + 50400
        er = _event_relay(
            "b6" * 32,
            "wss://n85.example.com",
            kind=1,
            pubkey=pubkey,
            created_at=created_at,
            tags=[],
        )
        await brotr.insert_event_relay([er], cascade=True)
        await _refresh_nip85(brotr)

        row = await brotr.fetchrow(
            "SELECT activity_hours FROM nip85_pubkey_stats WHERE pubkey = $1",
            pubkey,
        )
        assert row is not None
        hours = row["activity_hours"]
        assert (
            hours[14] == 1
        )  # 0-indexed, hour 14 (PostgreSQL arrays are 1-indexed in SQL but 0-indexed in Python asyncpg)

    async def test_topic_counts(self, brotr: Brotr) -> None:
        pubkey = "c9" * 32
        ers = [
            _event_relay(
                "b7" * 32,
                "wss://n85.example.com",
                kind=1,
                pubkey=pubkey,
                tags=[["t", "bitcoin"]],
            ),
            _event_relay(
                "b8" * 32,
                "wss://n85.example.com",
                kind=1,
                pubkey=pubkey,
                tags=[["t", "bitcoin"], ["t", "nostr"]],
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_nip85(brotr)

        row = await brotr.fetchrow(
            "SELECT topic_counts FROM nip85_pubkey_stats WHERE pubkey = $1",
            pubkey,
        )
        assert row is not None
        topics = row["topic_counts"]
        assert int(topics["bitcoin"]) == 2
        assert int(topics["nostr"]) == 1

    async def test_topic_counts_tolerate_legacy_non_numeric_values(self, brotr: Brotr) -> None:
        pubkey = "ca" * 32
        await brotr.execute(
            "INSERT INTO nip85_pubkey_stats (pubkey, topic_counts) VALUES ($1, $2::jsonb)",
            pubkey,
            '{"bitcoin":"oops","nostr":"2"}',
        )
        er = _event_relay(
            "bc" * 32,
            "wss://n85.example.com",
            kind=1,
            pubkey=pubkey,
            tags=[["t", "bitcoin"]],
        )
        await brotr.insert_event_relay([er], cascade=True)
        await _refresh_nip85(brotr)

        row = await brotr.fetchrow(
            "SELECT topic_counts FROM nip85_pubkey_stats WHERE pubkey = $1",
            pubkey,
        )
        assert row is not None
        topics = row["topic_counts"]
        assert int(topics["bitcoin"]) == 1
        assert int(topics["nostr"]) == 2

    async def test_invalid_zap_amount_is_ignored_without_crashing(self, brotr: Brotr) -> None:
        recipient = "cb" * 32
        er = _event_relay(
            "bd" * 32,
            "wss://n85.example.com",
            kind=9735,
            pubkey="cc" * 32,
            tags=[
                ["p", recipient],
                ["amount", "not-a-number"],
                ["bolt11", "lnbc21000n1qqq"],
            ],
        )
        await brotr.insert_event_relay([er], cascade=True)
        await _refresh_nip85(brotr)

        row = await brotr.fetchrow(
            "SELECT zap_count_recd, zap_amount_recd FROM nip85_pubkey_stats WHERE pubkey = $1",
            recipient,
        )
        assert row is None or (row["zap_count_recd"] == 0 and row["zap_amount_recd"] == 0)

    async def test_incremental_accumulation(self, brotr: Brotr) -> None:
        pubkey = "d0" * 32
        er1 = _event_relay("b9" * 32, "wss://n85.example.com", kind=1, pubkey=pubkey, seen_at=100)
        await brotr.insert_event_relay([er1], cascade=True)
        await _refresh_nip85(brotr, after=0, until=200)

        er2 = _event_relay("ba" * 32, "wss://n85.example.com", kind=1, pubkey=pubkey, seen_at=300)
        await brotr.insert_event_relay([er2], cascade=True)
        await _refresh_nip85(brotr, after=200, until=400)

        row = await brotr.fetchrow(
            "SELECT post_count FROM nip85_pubkey_stats WHERE pubkey = $1",
            pubkey,
        )
        assert row is not None
        assert row["post_count"] == 2

    async def test_cross_relay_deduplication(self, brotr: Brotr) -> None:
        pubkey = "d1" * 32
        event_id = "bb" * 32
        ers = [
            _event_relay(event_id, "wss://r1.example.com", kind=1, pubkey=pubkey, seen_at=100),
            _event_relay(event_id, "wss://r2.example.com", kind=1, pubkey=pubkey, seen_at=100),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_nip85(brotr)

        row = await brotr.fetchrow(
            "SELECT post_count FROM nip85_pubkey_stats WHERE pubkey = $1",
            pubkey,
        )
        assert row is not None
        assert row["post_count"] == 1


class TestNip85EventStats:
    async def test_comment_count(self, brotr: Brotr) -> None:
        target_event = "e0" * 32
        target_author = "d2" * 32
        # Create the target event
        er_target = _event_relay(
            target_event, "wss://n85e.example.com", kind=1, pubkey=target_author
        )
        # Create a comment on it
        er_comment = _event_relay(
            "e1" * 32,
            "wss://n85e.example.com",
            kind=1,
            pubkey="d3" * 32,
            tags=[["e", target_event]],
        )
        await brotr.insert_event_relay([er_target, er_comment], cascade=True)
        await _refresh_nip85(brotr)

        row = await brotr.fetchrow(
            "SELECT comment_count, author_pubkey FROM nip85_event_stats WHERE event_id = $1",
            target_event,
        )
        assert row is not None
        assert row["comment_count"] == 1
        assert row["author_pubkey"] == target_author

    async def test_comment_prefers_reply_marker_when_tags_present(self, brotr: Brotr) -> None:
        root_event = "e8" * 32
        reply_target = "e9" * 32
        ers = [
            _event_relay(root_event, "wss://n85e.example.com", kind=1, pubkey="d2" * 32),
            _event_relay(reply_target, "wss://n85e.example.com", kind=1, pubkey="d3" * 32),
            _event_relay(
                "ea" * 32,
                "wss://n85e.example.com",
                kind=1,
                pubkey="d4" * 32,
                tags=[["e", root_event], ["e", reply_target, "", "reply"]],
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_nip85(brotr)

        root_row = await brotr.fetchrow(
            "SELECT comment_count FROM nip85_event_stats WHERE event_id = $1",
            root_event,
        )
        reply_row = await brotr.fetchrow(
            "SELECT comment_count FROM nip85_event_stats WHERE event_id = $1",
            reply_target,
        )
        assert root_row is None or root_row["comment_count"] == 0
        assert reply_row is not None
        assert reply_row["comment_count"] == 1

    async def test_comment_uses_last_e_without_reply_marker_when_tags_present(
        self, brotr: Brotr
    ) -> None:
        first_target = "10" * 32
        last_target = "11" * 32
        ers = [
            _event_relay(first_target, "wss://n85e.example.com", kind=1, pubkey="d2" * 32),
            _event_relay(last_target, "wss://n85e.example.com", kind=1, pubkey="d3" * 32),
            _event_relay(
                "12" * 32,
                "wss://n85e.example.com",
                kind=1,
                pubkey="d4" * 32,
                tags=[["e", first_target], ["e", last_target]],
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_nip85(brotr)

        first_row = await brotr.fetchrow(
            "SELECT comment_count FROM nip85_event_stats WHERE event_id = $1",
            first_target,
        )
        last_row = await brotr.fetchrow(
            "SELECT comment_count FROM nip85_event_stats WHERE event_id = $1",
            last_target,
        )
        assert first_row is None or first_row["comment_count"] == 0
        assert last_row is not None
        assert last_row["comment_count"] == 1

    async def test_reaction_count(self, brotr: Brotr) -> None:
        target_event = "e2" * 32
        er_target = _event_relay(target_event, "wss://n85e.example.com", kind=1, pubkey="d4" * 32)
        er_reaction = _event_relay(
            "e3" * 32,
            "wss://n85e.example.com",
            kind=7,
            pubkey="d5" * 32,
            tags=[["e", target_event]],
        )
        await brotr.insert_event_relay([er_target, er_reaction], cascade=True)
        await _refresh_nip85(brotr)

        row = await brotr.fetchrow(
            "SELECT reaction_count FROM nip85_event_stats WHERE event_id = $1",
            target_event,
        )
        assert row is not None
        assert row["reaction_count"] == 1

    async def test_reaction_uses_last_e_when_tags_present(self, brotr: Brotr) -> None:
        first_target = "eb" * 32
        last_target = "ec" * 32
        ers = [
            _event_relay(first_target, "wss://n85e.example.com", kind=1, pubkey="d4" * 32),
            _event_relay(last_target, "wss://n85e.example.com", kind=1, pubkey="d5" * 32),
            _event_relay(
                "ed" * 32,
                "wss://n85e.example.com",
                kind=7,
                pubkey="d6" * 32,
                tags=[["e", first_target], ["e", last_target]],
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_nip85(brotr)

        first_row = await brotr.fetchrow(
            "SELECT reaction_count FROM nip85_event_stats WHERE event_id = $1",
            first_target,
        )
        last_row = await brotr.fetchrow(
            "SELECT reaction_count FROM nip85_event_stats WHERE event_id = $1",
            last_target,
        )
        assert first_row is None or first_row["reaction_count"] == 0
        assert last_row is not None
        assert last_row["reaction_count"] == 1

    async def test_repost_count(self, brotr: Brotr) -> None:
        target_event = "e4" * 32
        er_target = _event_relay(target_event, "wss://n85e.example.com", kind=1, pubkey="d6" * 32)
        er_repost = _event_relay(
            "e5" * 32,
            "wss://n85e.example.com",
            kind=6,
            pubkey="d7" * 32,
            tags=[["e", target_event]],
        )
        await brotr.insert_event_relay([er_target, er_repost], cascade=True)
        await _refresh_nip85(brotr)

        row = await brotr.fetchrow(
            "SELECT repost_count FROM nip85_event_stats WHERE event_id = $1",
            target_event,
        )
        assert row is not None
        assert row["repost_count"] == 1

    async def test_repost_uses_first_e_when_tags_present(self, brotr: Brotr) -> None:
        first_target = "ee" * 32
        second_target = "ef" * 32
        ers = [
            _event_relay(first_target, "wss://n85e.example.com", kind=1, pubkey="d7" * 32),
            _event_relay(second_target, "wss://n85e.example.com", kind=1, pubkey="d8" * 32),
            _event_relay(
                "f0" * 32,
                "wss://n85e.example.com",
                kind=6,
                pubkey="d9" * 32,
                tags=[["e", first_target], ["e", second_target]],
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_nip85(brotr)

        first_row = await brotr.fetchrow(
            "SELECT repost_count FROM nip85_event_stats WHERE event_id = $1",
            first_target,
        )
        second_row = await brotr.fetchrow(
            "SELECT repost_count FROM nip85_event_stats WHERE event_id = $1",
            second_target,
        )
        assert first_row is not None
        assert first_row["repost_count"] == 1
        assert second_row is None or second_row["repost_count"] == 0

    async def test_quote_count(self, brotr: Brotr) -> None:
        target_event = "e6" * 32
        er_target = _event_relay(target_event, "wss://n85e.example.com", kind=1, pubkey="d8" * 32)
        er_quote = _event_relay(
            "e7" * 32,
            "wss://n85e.example.com",
            kind=1,
            pubkey="d9" * 32,
            tags=[["q", target_event]],
        )
        await brotr.insert_event_relay([er_target, er_quote], cascade=True)
        await _refresh_nip85(brotr)

        row = await brotr.fetchrow(
            "SELECT quote_count FROM nip85_event_stats WHERE event_id = $1",
            target_event,
        )
        assert row is not None
        assert row["quote_count"] == 1

    async def test_incremental_accumulation(self, brotr: Brotr) -> None:
        target_event = "e8" * 32
        er_target = _event_relay(
            target_event, "wss://n85e.example.com", kind=1, pubkey="da" * 32, seen_at=100
        )
        er_react1 = _event_relay(
            "e9" * 32,
            "wss://n85e.example.com",
            kind=7,
            pubkey="db" * 32,
            tags=[["e", target_event]],
            seen_at=100,
        )
        await brotr.insert_event_relay([er_target, er_react1], cascade=True)
        await _refresh_nip85(brotr, after=0, until=200)

        er_react2 = _event_relay(
            "ea" * 32,
            "wss://n85e.example.com",
            kind=7,
            pubkey="dc" * 32,
            tags=[["e", target_event]],
            seen_at=300,
        )
        await brotr.insert_event_relay([er_react2], cascade=True)
        await _refresh_nip85(brotr, after=200, until=400)

        row = await brotr.fetchrow(
            "SELECT reaction_count FROM nip85_event_stats WHERE event_id = $1",
            target_event,
        )
        assert row is not None
        assert row["reaction_count"] == 2


class TestContactListFacts:
    async def test_contact_lists_current_tracks_deduplicated_latest_contacts(
        self, brotr: Brotr
    ) -> None:
        follower = "c0" * 32
        followed1 = "c1" * 32
        followed2 = "c2" * 32
        er = _event_relay(
            "c3" * 32,
            "wss://contacts.example.com",
            kind=3,
            pubkey=follower,
            seen_at=100,
            tags=[
                ["p", followed1],
                ["p", followed2],
                ["p", followed1],
                ["p", "not-a-valid-pubkey"],
            ],
        )
        await brotr.insert_event_relay([er], cascade=True)
        await _refresh_contact_graph(brotr, after=0, until=200)

        row = await brotr.fetchrow(
            "SELECT source_event_id, follow_count "
            "FROM contact_lists_current WHERE follower_pubkey = $1",
            follower,
        )
        edges = await brotr.fetch(
            "SELECT followed_pubkey FROM contact_list_edges_current "
            "WHERE follower_pubkey = $1 ORDER BY followed_pubkey",
            follower,
        )

        assert row is not None
        assert row["source_event_id"] == "c3" * 32
        assert row["follow_count"] == 2
        assert [edge["followed_pubkey"] for edge in edges] == [followed1, followed2]

    async def test_contact_list_edges_replace_previous_latest_list(self, brotr: Brotr) -> None:
        follower = "c4" * 32
        old_friend = "c5" * 32
        shared_friend = "c6" * 32
        new_friend = "c7" * 32
        ers = [
            _event_relay(
                "c8" * 32,
                "wss://contacts.example.com",
                kind=3,
                pubkey=follower,
                created_at=100,
                seen_at=101,
                tags=[["p", old_friend], ["p", shared_friend]],
            ),
            _event_relay(
                "c9" * 32,
                "wss://contacts.example.com",
                kind=3,
                pubkey=follower,
                created_at=200,
                seen_at=201,
                tags=[["p", shared_friend], ["p", new_friend]],
            ),
        ]
        await brotr.insert_event_relay([ers[0]], cascade=True)
        await _refresh_contact_graph(brotr, after=0, until=150)

        await brotr.insert_event_relay([ers[1]], cascade=True)
        await _refresh_contact_graph(brotr, after=150, until=300)

        row = await brotr.fetchrow(
            "SELECT source_event_id, follow_count "
            "FROM contact_lists_current WHERE follower_pubkey = $1",
            follower,
        )
        edges = await brotr.fetch(
            "SELECT followed_pubkey, source_event_id "
            "FROM contact_list_edges_current "
            "WHERE follower_pubkey = $1 ORDER BY followed_pubkey",
            follower,
        )

        assert row is not None
        assert row["source_event_id"] == "c9" * 32
        assert row["follow_count"] == 2
        assert [edge["followed_pubkey"] for edge in edges] == [shared_friend, new_friend]
        assert all(edge["source_event_id"] == "c9" * 32 for edge in edges)

    async def test_empty_latest_contact_list_removes_current_edges(self, brotr: Brotr) -> None:
        follower = "ca" * 32
        followed1 = "cb" * 32
        followed2 = "cc" * 32
        first = _event_relay(
            "cd" * 32,
            "wss://contacts.example.com",
            kind=3,
            pubkey=follower,
            created_at=100,
            seen_at=101,
            tags=[["p", followed1], ["p", followed2]],
        )
        second = _event_relay(
            "ce" * 32,
            "wss://contacts.example.com",
            kind=3,
            pubkey=follower,
            created_at=200,
            seen_at=201,
            tags=[],
        )
        await brotr.insert_event_relay([first], cascade=True)
        await _refresh_contact_graph(brotr, after=0, until=150)

        await brotr.insert_event_relay([second], cascade=True)
        await _refresh_contact_graph(brotr, after=150, until=300)

        row = await brotr.fetchrow(
            "SELECT source_event_id, follow_count "
            "FROM contact_lists_current WHERE follower_pubkey = $1",
            follower,
        )
        edges = await brotr.fetch(
            "SELECT followed_pubkey FROM contact_list_edges_current WHERE follower_pubkey = $1",
            follower,
        )

        assert row is not None
        assert row["source_event_id"] == "ce" * 32
        assert row["follow_count"] == 0
        assert edges == []


class TestNip85FollowerCount:
    async def test_follower_count_from_contacts(self, brotr: Brotr) -> None:
        followed = "f0" * 32
        follower1 = "f1" * 32
        follower2 = "f2" * 32
        # Create kind=3 contact lists that follow 'followed'
        ers = [
            _event_relay(
                "fc" * 32,
                "wss://n85f.example.com",
                kind=3,
                pubkey=follower1,
                tags=[["p", followed]],
            ),
            _event_relay(
                "fd" * 32,
                "wss://n85f.example.com",
                kind=3,
                pubkey=follower2,
                tags=[["p", followed]],
            ),
            # The followed pubkey needs at least one event for nip85 row to exist
            _event_relay("fe" * 32, "wss://n85f.example.com", kind=1, pubkey=followed),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_nip85(brotr)
        await _refresh_contact_graph(brotr)
        await brotr.execute("SELECT nip85_follower_count_refresh()")

        row = await brotr.fetchrow(
            "SELECT follower_count, following_count FROM nip85_pubkey_stats WHERE pubkey = $1",
            followed,
        )
        assert row is not None
        assert row["follower_count"] == 2

    async def test_following_count_from_own_contacts(self, brotr: Brotr) -> None:
        user = "f3" * 32
        friend1 = "f4" * 32
        friend2 = "f5" * 32
        ers = [
            _event_relay(
                "ff" * 32,
                "wss://n85f.example.com",
                kind=3,
                pubkey=user,
                tags=[["p", friend1], ["p", friend2]],
            ),
            # User needs an event for the nip85 row
            _event_relay("f6" * 32, "wss://n85f.example.com", kind=1, pubkey=user),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await _refresh_nip85(brotr)
        await _refresh_contact_graph(brotr)
        await brotr.execute("SELECT nip85_follower_count_refresh()")

        row = await brotr.fetchrow(
            "SELECT following_count FROM nip85_pubkey_stats WHERE pubkey = $1",
            user,
        )
        assert row is not None
        assert row["following_count"] == 2
