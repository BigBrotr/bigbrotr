"""Integration tests for transaction behavior and batch validation."""

from __future__ import annotations

import asyncio

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import EventRelay, Relay
from bigbrotr.models.event import Event
from bigbrotr.models.metadata import Metadata, MetadataType
from tests.conftest import make_mock_event


pytestmark = pytest.mark.integration


# =============================================================================
# Transaction Commit / Rollback
# =============================================================================


class TestTransactionCommit:
    async def test_insert_visible_after_commit(self, brotr: Brotr) -> None:
        async with brotr.transaction() as conn:
            await conn.execute(
                "INSERT INTO relay (url, network, discovered_at) VALUES ($1, $2, $3)",
                "wss://tx-commit.example.com",
                "clearnet",
                1700000000,
            )

        row = await brotr.fetchrow(
            "SELECT * FROM relay WHERE url = $1", "wss://tx-commit.example.com"
        )
        assert row is not None
        assert row["network"] == "clearnet"

    async def test_multiple_inserts_in_single_transaction(self, brotr: Brotr) -> None:
        async with brotr.transaction() as conn:
            for i in range(5):
                await conn.execute(
                    "INSERT INTO relay (url, network, discovered_at) VALUES ($1, $2, $3)",
                    f"wss://tx-multi{i}.example.com",
                    "clearnet",
                    1700000000,
                )

        count = await brotr.fetchval("SELECT COUNT(*) FROM relay WHERE url LIKE 'wss://tx-multi%'")
        assert count == 5

    async def test_cross_table_transaction(self, brotr: Brotr) -> None:
        await brotr.insert_relay([Relay("wss://tx-cross.example.com", discovered_at=1700000000)])
        mock = make_mock_event(event_id="f1" * 32, sig="ee" * 64)
        await brotr.insert_event([Event(mock)])

        async with brotr.transaction() as conn:
            await conn.execute(
                "INSERT INTO event_relay (event_id, relay_url, seen_at) VALUES ($1, $2, $3)",
                bytes.fromhex("f1" * 32),
                "wss://tx-cross.example.com",
                1700000001,
            )

        count = await brotr.fetchval("SELECT COUNT(*) FROM event_relay")
        assert count == 1


class TestTransactionRollback:
    async def test_exception_rolls_back(self, brotr: Brotr) -> None:
        with pytest.raises(RuntimeError, match="abort"):
            async with brotr.transaction() as conn:
                await conn.execute(
                    "INSERT INTO relay (url, network, discovered_at) VALUES ($1, $2, $3)",
                    "wss://tx-rollback.example.com",
                    "clearnet",
                    1700000000,
                )
                raise RuntimeError("abort")

        row = await brotr.fetchrow(
            "SELECT * FROM relay WHERE url = $1", "wss://tx-rollback.example.com"
        )
        assert row is None

    async def test_partial_inserts_rolled_back(self, brotr: Brotr) -> None:
        with pytest.raises(RuntimeError):
            async with brotr.transaction() as conn:
                await conn.execute(
                    "INSERT INTO relay (url, network, discovered_at) VALUES ($1, $2, $3)",
                    "wss://tx-partial1.example.com",
                    "clearnet",
                    1700000000,
                )
                await conn.execute(
                    "INSERT INTO relay (url, network, discovered_at) VALUES ($1, $2, $3)",
                    "wss://tx-partial2.example.com",
                    "clearnet",
                    1700000000,
                )
                raise RuntimeError("mid-transaction failure")

        count = await brotr.fetchval(
            "SELECT COUNT(*) FROM relay WHERE url LIKE 'wss://tx-partial%'"
        )
        assert count == 0

    async def test_constraint_violation_rolls_back(self, brotr: Brotr) -> None:
        import asyncpg

        with pytest.raises(asyncpg.ForeignKeyViolationError):
            async with brotr.transaction() as conn:
                await conn.execute(
                    "INSERT INTO event_relay (event_id, relay_url, seen_at) VALUES ($1, $2, $3)",
                    b"\x00" * 32,
                    "wss://nonexistent.example.com",
                    1700000001,
                )

        count = await brotr.fetchval("SELECT COUNT(*) FROM event_relay")
        assert count == 0


# =============================================================================
# Batch Size Validation
# =============================================================================


class TestBatchSizeValidation:
    async def test_relay_batch_exceeds_max_size(self, brotr: Brotr) -> None:
        max_size = brotr.config.batch.max_size
        oversized = [
            Relay(f"wss://batch{i}.example.com", discovered_at=1700000000)
            for i in range(max_size + 1)
        ]
        with pytest.raises(ValueError, match="batch size"):
            await brotr.insert_relay(oversized)

    async def test_event_relay_batch_exceeds_max_size(self, brotr: Brotr) -> None:
        max_size = brotr.config.batch.max_size
        relay = Relay("wss://batchev.example.com", discovered_at=1700000000)
        oversized = [
            EventRelay(
                event=Event(make_mock_event(event_id=f"{i:064x}", sig="ee" * 64)),
                relay=relay,
                seen_at=1700000001,
            )
            for i in range(max_size + 1)
        ]
        with pytest.raises(ValueError, match="batch size"):
            await brotr.insert_event_relay(oversized)

    async def test_metadata_batch_exceeds_max_size(self, brotr: Brotr) -> None:
        max_size = brotr.config.batch.max_size
        oversized = [
            Metadata(type=MetadataType.NIP11_INFO, data={"i": i}) for i in range(max_size + 1)
        ]
        with pytest.raises(ValueError, match="batch size"):
            await brotr.insert_metadata(oversized)

    async def test_batch_at_exact_max_size_accepted(self, brotr: Brotr) -> None:
        relays = [
            Relay(f"wss://exact-batch{i}.example.com", discovered_at=1700000000) for i in range(100)
        ]
        inserted = await brotr.insert_relay(relays)
        assert inserted == 100


# =============================================================================
# Concurrent Operations
# =============================================================================


class TestConcurrentOperations:
    async def test_concurrent_relay_inserts_no_error(self, brotr: Brotr) -> None:
        batch_a = [
            Relay(f"wss://conc-a{i}.example.com", discovered_at=1700000000) for i in range(20)
        ]
        batch_b = [
            Relay(f"wss://conc-b{i}.example.com", discovered_at=1700000000) for i in range(20)
        ]

        results = await asyncio.gather(
            brotr.insert_relay(batch_a),
            brotr.insert_relay(batch_b),
        )
        assert sum(results) == 40

        count = await brotr.fetchval("SELECT COUNT(*) FROM relay WHERE url LIKE 'wss://conc-%'")
        assert count == 40

    async def test_concurrent_insert_same_relay_dedup(self, brotr: Brotr) -> None:
        relay = Relay("wss://conc-same.example.com", discovered_at=1700000000)

        results = await asyncio.gather(
            brotr.insert_relay([relay]),
            brotr.insert_relay([relay]),
            brotr.insert_relay([relay]),
        )

        count = await brotr.fetchval(
            "SELECT COUNT(*) FROM relay WHERE url = $1", "wss://conc-same.example.com"
        )
        assert count == 1
        assert sum(results) >= 1

    async def test_concurrent_event_relay_cascade(self, brotr: Brotr) -> None:
        ers = []
        for i in range(10):
            mock = make_mock_event(event_id=f"{i + 100:064x}", sig="ee" * 64)
            relay = Relay(f"wss://conc-er{i}.example.com", discovered_at=1700000000)
            ers.append(EventRelay(event=Event(mock), relay=relay, seen_at=1700000001))

        batch1, batch2 = ers[:5], ers[5:]
        await asyncio.gather(
            brotr.insert_event_relay(batch1, cascade=True),
            brotr.insert_event_relay(batch2, cascade=True),
        )

        count = await brotr.fetchval("SELECT COUNT(*) FROM event_relay")
        assert count == 10
