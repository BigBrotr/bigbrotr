"""Integration tests for base materialized views (relay_metadata_latest)."""

from __future__ import annotations

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import Relay, RelayMetadata
from bigbrotr.models.metadata import Metadata, MetadataType


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
