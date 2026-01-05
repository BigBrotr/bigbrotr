"""
Integration tests for database operations.

Requires: Running PostgreSQL with BigBrotr schema.
Run with: pytest tests/integration/ -v -m integration

Environment variables:
- DB_PASSWORD: Required - PostgreSQL password
- DB_HOST: Optional - PostgreSQL host (default: localhost)
- DB_PORT: Optional - PostgreSQL port (default: 5432)
- DB_NAME: Optional - Database name (default: bigbrotr_test)
- DB_USER: Optional - Database user (default: admin)
"""

import os
from collections.abc import AsyncGenerator

import pytest

from core.brotr import Brotr, BrotrConfig
from core.pool import DatabaseConfig, Pool, PoolConfig
from models.metadata import Metadata
from models.relay import Relay
from models.relay_metadata import RelayMetadata


# Skip all tests in this module if DB_PASSWORD is not set
pytestmark = pytest.mark.skipif(
    os.getenv("DB_PASSWORD") is None,
    reason="DB_PASSWORD not set - skipping integration tests",
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def integration_pool() -> AsyncGenerator[Pool, None]:
    """Create real database connection pool."""
    config = PoolConfig(
        database=DatabaseConfig(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            database=os.getenv("DB_NAME", "bigbrotr_test"),
            user=os.getenv("DB_USER", "admin"),
            password=os.getenv("DB_PASSWORD"),
        )
    )
    pool = Pool(config=config)
    await pool.connect()
    yield pool
    await pool.close()


@pytest.fixture
async def integration_brotr(integration_pool: Pool) -> Brotr:
    """Create Brotr with real database connection."""
    config = BrotrConfig()
    return Brotr(pool=integration_pool, config=config)


# ============================================================================
# Relay Integration Tests
# ============================================================================


class TestRelayIntegration:
    """Integration tests for relay operations."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_insert_and_query_relay(self, integration_brotr: Brotr) -> None:
        """Test full relay insert/query cycle."""
        relay = Relay("wss://test.integration.relay.example.com")

        # Insert
        inserted = await integration_brotr.insert_relays([relay])
        assert inserted >= 0  # May already exist from previous run

        # Query
        rows = await integration_brotr.pool.fetch(
            "SELECT url, network, discovered_at FROM relays WHERE url = $1",
            relay.url,
        )
        assert len(rows) == 1
        assert rows[0]["network"] == "clearnet"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_insert_duplicate_relay(self, integration_brotr: Brotr) -> None:
        """Test inserting duplicate relay is idempotent."""
        relay = Relay("wss://duplicate.test.relay.example.com")

        # Insert twice
        await integration_brotr.insert_relays([relay])
        inserted = await integration_brotr.insert_relays([relay])

        # Second insert should succeed (idempotent)
        assert inserted >= 0

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_insert_tor_relay(self, integration_brotr: Brotr) -> None:
        """Test inserting Tor relay."""
        relay = Relay("wss://abcdefghijklmnopqrstuvwxyz234567.onion")

        await integration_brotr.insert_relays([relay])

        rows = await integration_brotr.pool.fetch(
            "SELECT network FROM relays WHERE url = $1",
            relay.url,
        )
        assert len(rows) == 1
        assert rows[0]["network"] == "tor"


# ============================================================================
# Relay Metadata Integration Tests
# ============================================================================


class TestRelayMetadataIntegration:
    """Integration tests for relay metadata operations."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_insert_relay_metadata(self, integration_brotr: Brotr) -> None:
        """Test metadata insertion with deduplication."""
        relay = Relay("wss://metadata.test.relay.example.com")

        # Insert relay first
        await integration_brotr.insert_relays([relay])

        # Insert metadata
        metadata = RelayMetadata(
            relay=relay,
            metadata_type="nip11",
            metadata=Metadata({"name": "Test Relay", "description": "Integration test"}),
        )

        inserted = await integration_brotr.insert_relay_metadata([metadata])
        assert inserted == 1

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_metadata_deduplication(self, integration_brotr: Brotr) -> None:
        """Test that identical metadata is deduplicated."""
        relay = Relay("wss://dedup.test.relay.example.com")
        await integration_brotr.insert_relays([relay])

        # Same data should produce same content hash
        data = {"name": "Dedup Test", "version": "1.0"}

        metadata1 = RelayMetadata(relay=relay, metadata_type="nip11", metadata=Metadata(data))
        metadata2 = RelayMetadata(relay=relay, metadata_type="nip11", metadata=Metadata(data))

        await integration_brotr.insert_relay_metadata([metadata1])
        await integration_brotr.insert_relay_metadata([metadata2])

        # Check only one metadata record exists with this data
        rows = await integration_brotr.pool.fetch(
            """
            SELECT COUNT(DISTINCT id) as count
            FROM metadata
            WHERE data = $1::jsonb
            """,
            '{"name": "Dedup Test", "version": "1.0"}',
        )
        assert rows[0]["count"] == 1


# ============================================================================
# Service Data Integration Tests
# ============================================================================


class TestServiceDataIntegration:
    """Integration tests for service_data operations."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_upsert_and_get_service_data(self, integration_brotr: Brotr) -> None:
        """Test service data upsert/get cycle."""
        records = [("integration_test", "cursor", "test_key", {"value": 123})]

        # Upsert
        await integration_brotr.upsert_service_data(records)

        # Get
        result = await integration_brotr.get_service_data("integration_test", "cursor", "test_key")
        assert len(result) == 1
        assert result[0]["value"]["value"] == 123

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_update_service_data(self, integration_brotr: Brotr) -> None:
        """Test updating existing service data."""
        key = "update_test_key"

        # Initial insert
        await integration_brotr.upsert_service_data(
            [("integration_test", "state", key, {"version": 1})]
        )

        # Update
        await integration_brotr.upsert_service_data(
            [("integration_test", "state", key, {"version": 2})]
        )

        # Verify update
        result = await integration_brotr.get_service_data("integration_test", "state", key)
        assert len(result) == 1
        assert result[0]["value"]["version"] == 2

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_delete_service_data(self, integration_brotr: Brotr) -> None:
        """Test service data deletion."""
        key = "delete_test_key"

        # Setup
        await integration_brotr.upsert_service_data(
            [("integration_test", "temp", key, {"temp": True})]
        )

        # Delete
        deleted = await integration_brotr.delete_service_data([("integration_test", "temp", key)])
        assert deleted == 1

        # Verify deletion
        result = await integration_brotr.get_service_data("integration_test", "temp", key)
        assert len(result) == 0


# ============================================================================
# Cleanup Functions Integration Tests
# ============================================================================


class TestCleanupIntegration:
    """Integration tests for cleanup functions."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_delete_orphan_metadata(self, integration_brotr: Brotr) -> None:
        """Test orphan metadata cleanup."""
        deleted = await integration_brotr.delete_orphan_metadata()
        assert isinstance(deleted, int)
        assert deleted >= 0

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_delete_orphan_events(self, integration_brotr: Brotr) -> None:
        """Test orphan events cleanup."""
        deleted = await integration_brotr.delete_orphan_events()
        assert isinstance(deleted, int)
        assert deleted >= 0

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_delete_failed_candidates(self, integration_brotr: Brotr) -> None:
        """Test failed candidates cleanup."""
        # Insert a candidate with high failure count
        await integration_brotr.upsert_service_data(
            [("validator", "candidate", "wss://failed.test.relay", {"failed_attempts": 15})]
        )

        # Delete with threshold 10
        deleted = await integration_brotr.delete_failed_candidates(max_attempts=10)
        assert isinstance(deleted, int)
        assert deleted >= 1

        # Verify deletion
        result = await integration_brotr.get_service_data(
            "validator", "candidate", "wss://failed.test.relay"
        )
        assert len(result) == 0


# ============================================================================
# Pool Metrics Integration Tests
# ============================================================================


class TestPoolMetricsIntegration:
    """Integration tests for pool metrics."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_pool_metrics(self, integration_pool: Pool) -> None:
        """Test pool metrics reporting."""
        metrics = integration_pool.metrics

        assert metrics["is_connected"] is True
        assert metrics["size"] >= 0
        assert metrics["idle_size"] >= 0
        assert metrics["min_size"] > 0
        assert metrics["max_size"] >= metrics["min_size"]
        assert 0.0 <= metrics["utilization"] <= 1.0
