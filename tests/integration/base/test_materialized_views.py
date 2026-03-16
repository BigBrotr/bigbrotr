"""Integration tests for all materialized views."""

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


class TestRelayMetadataLatest:
    async def test_empty_view(self, brotr: Brotr) -> None:
        await brotr.refresh_materialized_view("relay_metadata_latest")
        rows = await brotr.fetch("SELECT * FROM relay_metadata_latest")
        assert len(rows) == 0

    async def test_returns_latest_snapshot_by_generated_at(self, brotr: Brotr) -> None:
        rm_old = _rm("wss://latest1.example.com", {"name": "Old"}, generated_at=1700000001)
        rm_new = _rm("wss://latest1.example.com", {"name": "New"}, generated_at=1700000002)
        await brotr.insert_relay_metadata([rm_old, rm_new], cascade=True)
        await brotr.refresh_materialized_view("relay_metadata_latest")

        row = await brotr.fetchrow(
            "SELECT * FROM relay_metadata_latest WHERE relay_url = $1 AND metadata_type = $2",
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
        await brotr.refresh_materialized_view("relay_metadata_latest")

        rows = await brotr.fetch(
            "SELECT metadata_type FROM relay_metadata_latest "
            "WHERE relay_url = $1 ORDER BY metadata_type",
            "wss://multi-t.example.com",
        )
        assert len(rows) == 2
        assert {r["metadata_type"] for r in rows} == {"nip11_info", "nip66_ssl"}

    async def test_multiple_relays_same_type(self, brotr: Brotr) -> None:
        rm1 = _rm("wss://relay-a.example.com", {"name": "A"})
        rm2 = _rm("wss://relay-b.example.com", {"name": "B"})
        await brotr.insert_relay_metadata([rm1, rm2], cascade=True)
        await brotr.refresh_materialized_view("relay_metadata_latest")

        rows = await brotr.fetch("SELECT relay_url FROM relay_metadata_latest ORDER BY relay_url")
        assert len(rows) == 2

    async def test_refresh_function_callable_directly(self, brotr: Brotr) -> None:
        rm = _rm("wss://refresh-fn.example.com", {"name": "Refresh"})
        await brotr.insert_relay_metadata([rm], cascade=True)

        await brotr.execute("SELECT relay_metadata_latest_refresh()")

        count = await brotr.fetchval("SELECT COUNT(*) FROM relay_metadata_latest")
        assert count == 1

    async def test_view_updates_after_new_data_and_refresh(self, brotr: Brotr) -> None:
        rm_v1 = _rm("wss://update-v.example.com", {"version": "1"}, generated_at=100)
        await brotr.insert_relay_metadata([rm_v1], cascade=True)
        await brotr.refresh_materialized_view("relay_metadata_latest")

        row = await brotr.fetchrow(
            "SELECT data FROM relay_metadata_latest WHERE relay_url = $1",
            "wss://update-v.example.com",
        )
        assert row["data"]["version"] == "1"

        rm_v2 = _rm("wss://update-v.example.com", {"version": "2"}, generated_at=200)
        await brotr.insert_relay_metadata([rm_v2], cascade=True)
        await brotr.refresh_materialized_view("relay_metadata_latest")

        row = await brotr.fetchrow(
            "SELECT data FROM relay_metadata_latest WHERE relay_url = $1",
            "wss://update-v.example.com",
        )
        assert row["data"]["version"] == "2"

    async def test_view_contains_data_column(self, brotr: Brotr) -> None:
        rm = _rm("wss://data-col.example.com", {"name": "Test", "contact": "admin@test.com"})
        await brotr.insert_relay_metadata([rm], cascade=True)
        await brotr.refresh_materialized_view("relay_metadata_latest")

        row = await brotr.fetchrow(
            "SELECT data FROM relay_metadata_latest WHERE relay_url = $1",
            "wss://data-col.example.com",
        )
        assert row["data"]["name"] == "Test"
        assert row["data"]["contact"] == "admin@test.com"

    async def test_all_seven_metadata_types(self, brotr: Brotr) -> None:
        rms = []
        for i, mt in enumerate(MetadataType):
            rms.append(
                _rm(
                    f"wss://type{i}.example.com",
                    {"type_test": mt.value},
                    mt,
                )
            )
        await brotr.insert_relay_metadata(rms, cascade=True)
        await brotr.refresh_materialized_view("relay_metadata_latest")

        count = await brotr.fetchval("SELECT COUNT(*) FROM relay_metadata_latest")
        assert count == len(MetadataType)


# ============================================================================
# Helpers for statistical views
# ============================================================================


def _event_relay(
    event_id: str,
    relay_url: str,
    kind: int = 1,
    pubkey: str = "bb" * 32,
    created_at: int = 1700000000,
) -> EventRelay:
    mock = make_mock_event(
        event_id=event_id, pubkey=pubkey, kind=kind, created_at=created_at, sig="ee" * 64
    )
    relay = Relay(relay_url, discovered_at=1700000000)
    return EventRelay(event=Event(mock), relay=relay, seen_at=created_at + 1)


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


# ============================================================================
# event_stats
# ============================================================================


class TestEventStats:
    async def test_empty_returns_zeros(self, brotr: Brotr):
        await brotr.refresh_materialized_view("event_stats")

        rows = await brotr.fetch("SELECT * FROM event_stats")
        assert len(rows) == 1
        row = rows[0]
        assert row["event_count"] == 0
        assert row["unique_pubkeys"] == 0
        assert row["unique_kinds"] == 0
        assert row["regular_event_count"] == 0
        assert row["replaceable_event_count"] == 0
        assert row["ephemeral_event_count"] == 0
        assert row["addressable_event_count"] == 0

    async def test_with_five_events_two_pubkeys(self, brotr: Brotr):
        ers = [
            _event_relay(
                event_id=f"{i:064x}",
                relay_url="wss://es.example.com",
                kind=1,
                pubkey=f"{i % 2:064x}",
                created_at=1700000000 + i,
            )
            for i in range(5)
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("event_stats")

        rows = await brotr.fetch("SELECT * FROM event_stats")
        assert rows[0]["event_count"] == 5
        assert rows[0]["unique_pubkeys"] == 2
        assert rows[0]["unique_kinds"] == 1
        assert rows[0]["regular_event_count"] == 5

    async def test_nip01_category_counts(self, brotr: Brotr):
        ers = [
            _event_relay("ca" * 32, "wss://cat.example.com", kind=1),
            _event_relay("cb" * 32, "wss://cat.example.com", kind=0),
            _event_relay("cc" * 32, "wss://cat.example.com", kind=20000),
            _event_relay("cd" * 32, "wss://cat.example.com", kind=30000),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("event_stats")

        row = (await brotr.fetch("SELECT * FROM event_stats"))[0]
        assert row["event_count"] == 4
        assert row["regular_event_count"] == 1
        assert row["replaceable_event_count"] == 1
        assert row["ephemeral_event_count"] == 1
        assert row["addressable_event_count"] == 1

    async def test_time_window_recent_events(self, brotr: Brotr):
        now = int(time.time())
        ers = [
            _event_relay("f1" * 32, "wss://tw.example.com", created_at=now - 600),
            _event_relay("f2" * 32, "wss://tw.example.com", created_at=now - 1800),
            _event_relay("f3" * 32, "wss://tw.example.com", created_at=now - 43200),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("event_stats")

        row = (await brotr.fetch("SELECT * FROM event_stats"))[0]
        assert row["event_count"] == 3
        assert row["event_count_last_1h"] >= 1
        assert row["event_count_last_24h"] == 3
        assert row["event_count_last_7d"] == 3
        assert row["event_count_last_30d"] == 3

    async def test_events_per_day(self, brotr: Brotr):
        ers = [
            _event_relay(
                event_id=f"{i:064x}",
                relay_url="wss://epd.example.com",
                created_at=1700000000 + i * 86400,
            )
            for i in range(10)
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("event_stats")

        row = (await brotr.fetch("SELECT events_per_day FROM event_stats"))[0]
        assert row["events_per_day"] is not None
        epd = float(row["events_per_day"])
        assert 0.9 < epd < 1.5


# ============================================================================
# relay_stats
# ============================================================================


class TestRelayStats:
    async def test_empty(self, brotr: Brotr):
        await brotr.refresh_materialized_view("relay_stats")
        rows = await brotr.fetch("SELECT * FROM relay_stats")
        assert len(rows) == 0

    async def test_three_events_same_relay(self, brotr: Brotr):
        ers = [
            _event_relay(
                event_id=f"{i:064x}",
                relay_url="wss://rs.example.com",
                kind=i + 1,
                pubkey=f"{i:064x}",
            )
            for i in range(3)
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("relay_stats")

        rows = await brotr.fetch(
            "SELECT * FROM relay_stats WHERE relay_url = $1", "wss://rs.example.com"
        )
        assert len(rows) == 1
        assert rows[0]["event_count"] == 3
        assert rows[0]["unique_pubkeys"] == 3
        assert rows[0]["unique_kinds"] == 3

    async def test_nip11_info_fields(self, brotr: Brotr):
        er = _event_relay("f0" * 32, "wss://nip11.example.com")
        await brotr.insert_event_relay([er], cascade=True)
        rm = _nip11_metadata(
            "wss://nip11.example.com",
            {"name": "Test Relay", "software": "strfry", "version": "1.0.0"},
        )
        await brotr.insert_relay_metadata([rm], cascade=True)
        await brotr.refresh_materialized_view("relay_metadata_latest")
        await brotr.refresh_materialized_view("relay_stats")

        rows = await brotr.fetch(
            "SELECT nip11_name, nip11_software, nip11_version"
            " FROM relay_stats WHERE relay_url = $1",
            "wss://nip11.example.com",
        )
        assert rows[0]["nip11_name"] == "Test Relay"
        assert rows[0]["nip11_software"] == "strfry"
        assert rows[0]["nip11_version"] == "1.0.0"

    async def test_avg_rtt_from_nip66_metadata(self, brotr: Brotr):
        er = _event_relay("a0" * 32, "wss://rtt.example.com")
        await brotr.insert_event_relay([er], cascade=True)

        rtt_values = [100, 200, 300]
        for i, rtt in enumerate(rtt_values):
            rm = _nip66_metadata(
                "wss://rtt.example.com",
                MetadataType.NIP66_RTT,
                {"rtt_open": rtt, "rtt_read": rtt + 10, "rtt_write": rtt + 20},
                generated_at=1700000001 + i,
            )
            await brotr.insert_relay_metadata([rm], cascade=True)

        await brotr.refresh_materialized_view("relay_stats")

        rows = await brotr.fetch(
            "SELECT avg_rtt_open, avg_rtt_read, avg_rtt_write"
            " FROM relay_stats WHERE relay_url = $1",
            "wss://rtt.example.com",
        )
        assert len(rows) == 1
        assert float(rows[0]["avg_rtt_open"]) == 200.0
        assert float(rows[0]["avg_rtt_read"]) == 210.0
        assert float(rows[0]["avg_rtt_write"]) == 220.0

    async def test_multiple_relays_different_counts(self, brotr: Brotr):
        ers = [
            _event_relay("b0" * 32, "wss://r1.example.com"),
            _event_relay("b1" * 32, "wss://r1.example.com", pubkey="cc" * 32),
            _event_relay("b2" * 32, "wss://r2.example.com"),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("relay_stats")

        rows = await brotr.fetch(
            "SELECT relay_url, event_count FROM relay_stats ORDER BY relay_url"
        )
        counts = {row["relay_url"]: row["event_count"] for row in rows}
        assert counts["wss://r1.example.com"] == 2
        assert counts["wss://r2.example.com"] == 1


# ============================================================================
# kind_counts
# ============================================================================


class TestKindCounts:
    async def test_multiple_kinds(self, brotr: Brotr):
        ers = [
            _event_relay("a0" * 32, "wss://kc.example.com", kind=1),
            _event_relay("a1" * 32, "wss://kc.example.com", kind=1),
            _event_relay("a2" * 32, "wss://kc.example.com", kind=3),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("kind_counts")

        rows = await brotr.fetch("SELECT kind, event_count FROM kind_counts ORDER BY kind")
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
        await brotr.refresh_materialized_view("kind_counts")

        rows = await brotr.fetch("SELECT kind, category FROM kind_counts ORDER BY kind")
        categories = {row["kind"]: row["category"] for row in rows}
        assert categories[0] == "replaceable"
        assert categories[1] == "regular"
        assert categories[20000] == "ephemeral"
        assert categories[30000] == "addressable"

    async def test_unused_kind_no_row(self, brotr: Brotr):
        ers = [_event_relay("d0" * 32, "wss://unused.example.com", kind=7)]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("kind_counts")

        rows = await brotr.fetch("SELECT * FROM kind_counts WHERE kind = $1", 42)
        assert len(rows) == 0


# ============================================================================
# kind_counts_by_relay
# ============================================================================


class TestKindCountsByRelay:
    async def test_per_relay_kind_distribution(self, brotr: Brotr):
        ers = [
            _event_relay("b0" * 32, "wss://kcr1.example.com", kind=1),
            _event_relay("b1" * 32, "wss://kcr1.example.com", kind=1),
            _event_relay("b2" * 32, "wss://kcr2.example.com", kind=3),
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

    async def test_different_relays_different_kinds(self, brotr: Brotr):
        ers = [
            _event_relay("c0" * 32, "wss://kr1.example.com", kind=1),
            _event_relay("c1" * 32, "wss://kr1.example.com", kind=7),
            _event_relay("c2" * 32, "wss://kr2.example.com", kind=7),
            _event_relay("c3" * 32, "wss://kr2.example.com", kind=30000),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("kind_counts_by_relay")

        rows = await brotr.fetch(
            "SELECT relay_url, kind FROM kind_counts_by_relay ORDER BY relay_url, kind"
        )
        r1_kinds = {r["kind"] for r in rows if r["relay_url"] == "wss://kr1.example.com"}
        r2_kinds = {r["kind"] for r in rows if r["relay_url"] == "wss://kr2.example.com"}
        assert r1_kinds == {1, 7}
        assert r2_kinds == {7, 30000}


# ============================================================================
# pubkey_counts
# ============================================================================


class TestPubkeyCounts:
    async def test_multiple_pubkeys_event_counts(self, brotr: Brotr):
        ers = [
            _event_relay("c0" * 32, "wss://pk.example.com", pubkey="11" * 32),
            _event_relay("c1" * 32, "wss://pk.example.com", pubkey="11" * 32),
            _event_relay("c2" * 32, "wss://pk.example.com", pubkey="22" * 32),
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

    async def test_first_and_last_event_timestamps(self, brotr: Brotr):
        ers = [
            _event_relay("d0" * 32, "wss://ts.example.com", pubkey="33" * 32, created_at=1000000),
            _event_relay("d1" * 32, "wss://ts.example.com", pubkey="33" * 32, created_at=2000000),
            _event_relay("d2" * 32, "wss://ts.example.com", pubkey="33" * 32, created_at=3000000),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("pubkey_counts")

        rows = await brotr.fetch(
            "SELECT first_event_timestamp, last_event_timestamp"
            " FROM pubkey_counts WHERE pubkey = $1",
            "33" * 32,
        )
        assert rows[0]["first_event_timestamp"] == 1000000
        assert rows[0]["last_event_timestamp"] == 3000000

    async def test_unique_kinds_per_pubkey(self, brotr: Brotr):
        ers = [
            _event_relay("e0" * 32, "wss://uk.example.com", pubkey="44" * 32, kind=1),
            _event_relay("e1" * 32, "wss://uk.example.com", pubkey="44" * 32, kind=7),
            _event_relay("e2" * 32, "wss://uk.example.com", pubkey="44" * 32, kind=7),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("pubkey_counts")

        rows = await brotr.fetch(
            "SELECT unique_kinds FROM pubkey_counts WHERE pubkey = $1", "44" * 32
        )
        assert rows[0]["unique_kinds"] == 2


# ============================================================================
# pubkey_counts_by_relay
# ============================================================================


class TestPubkeyCountsByRelay:
    async def test_single_event_per_relay_excluded(self, brotr: Brotr):
        ers = [
            _event_relay("d0" * 32, "wss://pkr1.example.com", pubkey="11" * 32),
            _event_relay("d1" * 32, "wss://pkr1.example.com", pubkey="22" * 32),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("pubkey_counts_by_relay")

        rows = await brotr.fetch("SELECT * FROM pubkey_counts_by_relay")
        assert len(rows) == 0

    async def test_three_events_per_relay_included(self, brotr: Brotr):
        ers = [
            _event_relay("d0" * 32, "wss://pkr2.example.com", pubkey="11" * 32),
            _event_relay("d1" * 32, "wss://pkr2.example.com", pubkey="11" * 32),
            _event_relay("d2" * 32, "wss://pkr2.example.com", pubkey="11" * 32),
            _event_relay("d3" * 32, "wss://pkr2.example.com", pubkey="22" * 32),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("pubkey_counts_by_relay")

        rows = await brotr.fetch(
            "SELECT relay_url, pubkey, event_count FROM pubkey_counts_by_relay"
        )
        assert len(rows) == 1
        assert rows[0]["pubkey"] == "11" * 32
        assert rows[0]["event_count"] == 3

    async def test_mixed_relay_threshold(self, brotr: Brotr):
        ers = [
            _event_relay("e0" * 32, "wss://mix1.example.com", pubkey="55" * 32),
            _event_relay("e1" * 32, "wss://mix1.example.com", pubkey="55" * 32),
            _event_relay("e2" * 32, "wss://mix1.example.com", pubkey="55" * 32),
            _event_relay("e3" * 32, "wss://mix2.example.com", pubkey="55" * 32),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("pubkey_counts_by_relay")

        rows = await brotr.fetch(
            "SELECT relay_url, event_count FROM pubkey_counts_by_relay"
            " WHERE pubkey = $1 ORDER BY relay_url",
            "55" * 32,
        )
        assert len(rows) == 1
        assert rows[0]["relay_url"] == "wss://mix1.example.com"
        assert rows[0]["event_count"] == 3


# ============================================================================
# network_stats
# ============================================================================


class TestNetworkStats:
    async def test_empty(self, brotr: Brotr):
        await brotr.refresh_materialized_view("network_stats")
        rows = await brotr.fetch("SELECT * FROM network_stats")
        assert len(rows) == 0

    async def test_clearnet_relay_with_events(self, brotr: Brotr):
        ers = [_event_relay(f"{i:064x}", "wss://net.example.com") for i in range(3)]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("network_stats")

        rows = await brotr.fetch("SELECT * FROM network_stats WHERE network = $1", "clearnet")
        assert len(rows) == 1
        assert rows[0]["relay_count"] == 1
        assert rows[0]["event_count"] == 3

    async def test_multiple_networks(self, brotr: Brotr):
        onion_host = "a" * 56 + ".onion"
        ers = [
            _event_relay("e0" * 32, "wss://clearnet.example.com"),
            _event_relay("e1" * 32, f"ws://{onion_host}"),
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

    async def test_missing_version_becomes_unknown(self, brotr: Brotr):
        er = _event_relay("51" * 32, "wss://nover.example.com")
        await brotr.insert_event_relay([er], cascade=True)
        rm = _nip11_metadata("wss://nover.example.com", {"software": "custom-relay"})
        await brotr.insert_relay_metadata([rm], cascade=True)

        await brotr.refresh_materialized_view("relay_metadata_latest")
        await brotr.refresh_materialized_view("relay_software_counts")

        rows = await brotr.fetch(
            "SELECT version FROM relay_software_counts WHERE software = $1", "custom-relay"
        )
        assert len(rows) == 1
        assert rows[0]["version"] == "unknown"

    async def test_missing_software_field_excluded(self, brotr: Brotr):
        er = _event_relay("52" * 32, "wss://nosw.example.com")
        await brotr.insert_event_relay([er], cascade=True)
        rm = _nip11_metadata("wss://nosw.example.com", {"name": "No Software"})
        await brotr.insert_relay_metadata([rm], cascade=True)

        await brotr.refresh_materialized_view("relay_metadata_latest")
        await brotr.refresh_materialized_view("relay_software_counts")

        rows = await brotr.fetch("SELECT * FROM relay_software_counts")
        assert len(rows) == 0


# ============================================================================
# supported_nip_counts
# ============================================================================


class TestSupportedNipCounts:
    async def test_empty(self, brotr: Brotr):
        await brotr.refresh_materialized_view("relay_metadata_latest")
        await brotr.refresh_materialized_view("supported_nip_counts")

        rows = await brotr.fetch("SELECT * FROM supported_nip_counts")
        assert len(rows) == 0

    async def test_nip_distribution_across_relays(self, brotr: Brotr):
        relay_nips = [
            ("wss://nip1.example.com", [1, 2, 4, 11]),
            ("wss://nip2.example.com", [1, 2, 9]),
        ]
        for i, (url, nips) in enumerate(relay_nips):
            er = _event_relay(f"{0x60 + i:064x}", url)
            await brotr.insert_event_relay([er], cascade=True)
            rm = _nip11_metadata(url, {"supported_nips": nips}, generated_at=1700000001 + i)
            await brotr.insert_relay_metadata([rm], cascade=True)

        await brotr.refresh_materialized_view("relay_metadata_latest")
        await brotr.refresh_materialized_view("supported_nip_counts")

        rows = await brotr.fetch("SELECT nip, relay_count FROM supported_nip_counts ORDER BY nip")
        nips = {row["nip"]: row["relay_count"] for row in rows}
        assert nips[1] == 2
        assert nips[2] == 2
        assert nips[4] == 1
        assert nips[9] == 1
        assert nips[11] == 1

    async def test_missing_supported_nips_no_contribution(self, brotr: Brotr):
        er = _event_relay("62" * 32, "wss://nonips.example.com")
        await brotr.insert_event_relay([er], cascade=True)
        rm = _nip11_metadata("wss://nonips.example.com", {"name": "No NIPs"})
        await brotr.insert_relay_metadata([rm], cascade=True)

        await brotr.refresh_materialized_view("relay_metadata_latest")
        await brotr.refresh_materialized_view("supported_nip_counts")

        rows = await brotr.fetch("SELECT * FROM supported_nip_counts")
        assert len(rows) == 0

    async def test_nip_values_are_integers(self, brotr: Brotr):
        er = _event_relay("63" * 32, "wss://nipint.example.com")
        await brotr.insert_event_relay([er], cascade=True)
        rm = _nip11_metadata("wss://nipint.example.com", {"supported_nips": [1, 11, 42]})
        await brotr.insert_relay_metadata([rm], cascade=True)

        await brotr.refresh_materialized_view("relay_metadata_latest")
        await brotr.refresh_materialized_view("supported_nip_counts")

        rows = await brotr.fetch("SELECT nip FROM supported_nip_counts ORDER BY nip")
        for row in rows:
            assert isinstance(row["nip"], int)
        assert [row["nip"] for row in rows] == [1, 11, 42]


# ============================================================================
# event_daily_counts
# ============================================================================


class TestEventDailyCounts:
    async def test_empty(self, brotr: Brotr):
        await brotr.refresh_materialized_view("event_daily_counts")
        rows = await brotr.fetch("SELECT * FROM event_daily_counts")
        assert len(rows) == 0

    async def test_five_events_same_day(self, brotr: Brotr):
        ers = [
            _event_relay(
                event_id=f"{i:064x}",
                relay_url="wss://daily.example.com",
                created_at=1700000000 + i * 60,
            )
            for i in range(5)
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("event_daily_counts")

        rows = await brotr.fetch("SELECT * FROM event_daily_counts")
        assert len(rows) == 1
        assert rows[0]["event_count"] == 5

    async def test_daily_unique_pubkeys_and_kinds(self, brotr: Brotr):
        ers = [
            _event_relay(
                "a0" * 32,
                "wss://duk.example.com",
                pubkey="aa" * 32,
                kind=1,
                created_at=1700000000,
            ),
            _event_relay(
                "a1" * 32,
                "wss://duk.example.com",
                pubkey="bb" * 32,
                kind=1,
                created_at=1700000060,
            ),
            _event_relay(
                "a2" * 32,
                "wss://duk.example.com",
                pubkey="aa" * 32,
                kind=7,
                created_at=1700000120,
            ),
        ]
        await brotr.insert_event_relay(ers, cascade=True)
        await brotr.refresh_materialized_view("event_daily_counts")

        rows = await brotr.fetch("SELECT * FROM event_daily_counts")
        assert len(rows) == 1
        assert rows[0]["event_count"] == 3
        assert rows[0]["unique_pubkeys"] == 2
        assert rows[0]["unique_kinds"] == 2

    async def test_events_on_three_different_days(self, brotr: Brotr):
        ers = [
            _event_relay(
                event_id=f"{i:064x}",
                relay_url="wss://multiday.example.com",
                created_at=1700000000 + i * 86400,
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
    async def test_refreshes_all_eleven_views(self, brotr: Brotr):
        ers = [
            _event_relay("e0" * 32, "wss://allref.example.com"),
            _event_relay("e1" * 32, "wss://allref.example.com"),
        ]
        await brotr.insert_event_relay(ers, cascade=True)

        rm = _nip11_metadata(
            "wss://allref.example.com",
            {
                "name": "All Refresh",
                "software": "test-relay",
                "version": "0.1.0",
                "supported_nips": [1, 2, 11],
            },
        )
        await brotr.insert_relay_metadata([rm], cascade=True)

        await brotr.execute("SELECT all_statistics_refresh()")

        es = await brotr.fetch("SELECT * FROM event_stats")
        assert es[0]["event_count"] == 2

        rs = await brotr.fetch(
            "SELECT * FROM relay_stats WHERE relay_url = $1", "wss://allref.example.com"
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

    async def test_dependency_order_metadata_latest_before_dependents(self, brotr: Brotr):
        er = _event_relay("f0" * 32, "wss://dep.example.com")
        await brotr.insert_event_relay([er], cascade=True)

        rm = _nip11_metadata(
            "wss://dep.example.com",
            {"software": "deptest", "version": "1.0", "supported_nips": [1, 50]},
        )
        await brotr.insert_relay_metadata([rm], cascade=True)

        await brotr.execute("SELECT all_statistics_refresh()")

        rsc = await brotr.fetch(
            "SELECT * FROM relay_software_counts WHERE software = $1", "deptest"
        )
        assert len(rsc) == 1
        assert rsc[0]["relay_count"] == 1

        snc = await brotr.fetch("SELECT nip, relay_count FROM supported_nip_counts ORDER BY nip")
        nips = {row["nip"]: row["relay_count"] for row in snc}
        assert 1 in nips
        assert 50 in nips
