"""Integration tests for base materialized views.

Tests exercise relay_metadata_latest, the only materialized view in the base
schema. Pattern: insert data -> refresh -> query view -> verify.
"""

from __future__ import annotations

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import Relay, RelayMetadata
from bigbrotr.models.metadata import Metadata, MetadataType


pytestmark = pytest.mark.integration


class TestRelayMetadataLatest:
    async def test_empty(self, brotr: Brotr):
        await brotr.refresh_materialized_view("relay_metadata_latest")

        rows = await brotr.fetch("SELECT * FROM relay_metadata_latest")
        assert len(rows) == 0

    async def test_returns_latest_snapshot(self, brotr: Brotr):
        relay = Relay("wss://latest.example.com", discovered_at=1700000000)
        old_meta = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Old"})
        new_meta = Metadata(type=MetadataType.NIP11_INFO, data={"name": "New"})

        rm_old = RelayMetadata(relay=relay, metadata=old_meta, generated_at=1700000001)
        rm_new = RelayMetadata(relay=relay, metadata=new_meta, generated_at=1700000002)
        await brotr.insert_relay_metadata([rm_old, rm_new], cascade=True)
        await brotr.refresh_materialized_view("relay_metadata_latest")

        rows = await brotr.fetch(
            "SELECT * FROM relay_metadata_latest WHERE relay_url = $1 AND metadata_type = $2",
            "wss://latest.example.com",
            "nip11_info",
        )
        assert len(rows) == 1
        assert rows[0]["generated_at"] == 1700000002
        assert rows[0]["data"]["name"] == "New"

    async def test_multiple_types_per_relay(self, brotr: Brotr):
        relay = Relay("wss://multi-type.example.com", discovered_at=1700000000)
        info = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Multi"})
        ssl = Metadata(type=MetadataType.NIP66_SSL, data={"valid": True})

        rm_info = RelayMetadata(relay=relay, metadata=info, generated_at=1700000001)
        rm_ssl = RelayMetadata(relay=relay, metadata=ssl, generated_at=1700000001)
        await brotr.insert_relay_metadata([rm_info, rm_ssl], cascade=True)
        await brotr.refresh_materialized_view("relay_metadata_latest")

        rows = await brotr.fetch(
            "SELECT * FROM relay_metadata_latest WHERE relay_url = $1 ORDER BY metadata_type",
            "wss://multi-type.example.com",
        )
        assert len(rows) == 2
        types = {row["metadata_type"] for row in rows}
        assert types == {"nip11_info", "nip66_ssl"}

    async def test_refresh_function(self, brotr: Brotr):
        relay = Relay("wss://refresh-fn.example.com", discovered_at=1700000000)
        meta = Metadata(type=MetadataType.NIP11_INFO, data={"name": "Refresh"})
        rm = RelayMetadata(relay=relay, metadata=meta, generated_at=1700000001)
        await brotr.insert_relay_metadata([rm], cascade=True)

        await brotr.execute("SELECT relay_metadata_latest_refresh()")

        rows = await brotr.fetch("SELECT * FROM relay_metadata_latest")
        assert len(rows) == 1
