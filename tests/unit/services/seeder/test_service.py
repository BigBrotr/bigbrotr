"""Unit tests for services.seeder service module."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.services.seeder import (
    SeedConfig,
    Seeder,
    SeederConfig,
)
from bigbrotr.services.seeder.utils import parse_seed_file


# ============================================================================
# Seeder Initialization Tests
# ============================================================================


class TestSeederInit:
    """Tests for Seeder initialization."""

    def test_init_with_defaults(self, mock_seeder_brotr: Brotr) -> None:
        """Test initialization with default config."""
        seeder = Seeder(brotr=mock_seeder_brotr)

        assert seeder._brotr is mock_seeder_brotr
        assert seeder.SERVICE_NAME == "seeder"
        assert seeder.config.seed.file_path == "static/seed_relays.txt"

    def test_init_with_custom_config(self, mock_seeder_brotr: Brotr) -> None:
        """Test initialization with custom config."""
        config = SeederConfig(
            seed=SeedConfig(file_path="custom/path.txt"),
        )
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        assert seeder.config.seed.file_path == "custom/path.txt"

    def test_from_dict(self, mock_seeder_brotr: Brotr) -> None:
        """Test factory method from_dict."""
        data = {
            "seed": {"file_path": "custom/path.txt", "to_validate": False},
        }
        seeder = Seeder.from_dict(data, brotr=mock_seeder_brotr)

        assert seeder.config.seed.file_path == "custom/path.txt"
        assert seeder.config.seed.to_validate is False

    def test_service_name_class_attribute(self, mock_seeder_brotr: Brotr) -> None:
        """Test SERVICE_NAME class attribute."""
        assert Seeder.SERVICE_NAME == "seeder"
        seeder = Seeder(brotr=mock_seeder_brotr)
        assert seeder.SERVICE_NAME == "seeder"

    def test_config_class_attribute(self, mock_seeder_brotr: Brotr) -> None:
        """Test CONFIG_CLASS class attribute."""
        assert SeederConfig == Seeder.CONFIG_CLASS

    def test_logger_initialized(self, mock_seeder_brotr: Brotr) -> None:
        """Test logger is initialized."""
        seeder = Seeder(brotr=mock_seeder_brotr)
        assert seeder._logger is not None


# ============================================================================
# Seed Relays Tests
# ============================================================================


class TestSeedRelays:
    """Tests for relay seeding."""

    async def test_seed_file_not_found(self, mock_seeder_brotr: Brotr) -> None:
        """Test seeding with non-existent file."""
        config = SeederConfig(seed=SeedConfig(file_path="nonexistent/file.txt"))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        result = await seeder.seed()
        assert result == 0

    async def test_seed_success_as_candidates(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Seed relays as validation candidates (to_validate=True)."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay1.example.com\nwss://relay2.example.com\n")

        mock_seeder_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {"url": "wss://relay1.example.com"},
                {"url": "wss://relay2.example.com"},
            ]
        )
        mock_seeder_brotr.upsert_service_state = AsyncMock(return_value=2)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file), to_validate=True))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder.seed()

        mock_seeder_brotr.upsert_service_state.assert_called()

    async def test_seed_success_as_relays(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Seed relays directly into relays table (to_validate=False)."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay1.example.com\nwss://relay2.example.com\n")

        mock_seeder_brotr.insert_relay = AsyncMock(return_value=2)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file), to_validate=False))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder.seed()

        mock_seeder_brotr.insert_relay.assert_called()

    async def test_seed_skips_comments_and_empty(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test seeding skips comments and empty lines."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("# Comment\n\nwss://relay.example.com\n# Another comment\n")

        mock_seeder_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"url": "wss://relay.example.com"}]
        )
        mock_seeder_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        result = await seeder.seed()
        assert result == 1
        mock_seeder_brotr.upsert_service_state.assert_called_once()

    async def test_seed_skips_invalid_urls(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test seeding skips invalid relay URLs."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("invalid-url\nwss://valid.relay.com\nnot-a-relay\n")

        mock_seeder_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"url": "wss://valid.relay.com"}]
        )
        mock_seeder_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        result = await seeder.seed()
        assert result == 1

    async def test_seed_empty_file(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test seeding with empty file."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("")

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        result = await seeder.seed()
        assert result == 0

    async def test_seed_all_exist(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test seeding when all relays already exist."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay.example.com\n")

        mock_seeder_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[]
        )

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        result = await seeder.seed()
        assert result == 0


# ============================================================================
# Seed As Candidates Tests
# ============================================================================


class TestSeedAsCandidates:
    """Tests for Seeder._seed_as_candidates() method."""

    async def test_seed_as_candidates_filters_existing(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test seeding filters relays that already exist in database."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("wss://new.relay.com\nwss://existing.relay.com\n")

        # Mock fetch to return only new relay (existing filtered out)
        mock_seeder_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"url": "wss://new.relay.com"}]
        )
        mock_seeder_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file), to_validate=True))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)
        relays = parse_seed_file(seed_file)

        await seeder._seed_as_candidates(relays)

        mock_seeder_brotr.upsert_service_state.assert_called()

    async def test_seed_as_candidates_includes_network_type(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test seeding includes network type in candidate data."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("wss://clearnet.relay.com\nws://example.onion\n")

        mock_seeder_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[
                {"url": "wss://clearnet.relay.com"},
                {"url": "ws://example.onion"},
            ]
        )
        mock_seeder_brotr.upsert_service_state = AsyncMock(return_value=2)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file), to_validate=True))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)
        relays = parse_seed_file(seed_file)

        await seeder._seed_as_candidates(relays)

        call_args = mock_seeder_brotr.upsert_service_state.call_args[0][0]
        networks = [record.state_value["network"] for record in call_args]
        assert "clearnet" in networks
        assert "tor" in networks


# ============================================================================
# Seed As Relays Tests
# ============================================================================


class TestSeedAsRelays:
    """Tests for Seeder._seed_as_relays() method."""

    async def test_seed_as_relays_inserts_directly(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test seeding inserts relays directly into relays table."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("wss://relay1.example.com\nwss://relay2.example.com\n")

        mock_seeder_brotr.insert_relay = AsyncMock(return_value=2)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file), to_validate=False))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)
        relays = parse_seed_file(seed_file)

        await seeder._seed_as_relays(relays)

        mock_seeder_brotr.insert_relay.assert_called()

    async def test_seed_as_relays_batching(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test seeding batches large relay lists."""
        # Create a large relay list
        seed_file = tmp_path / "seed.txt"
        relay_urls = [f"wss://relay{i}.example.com" for i in range(250)]
        seed_file.write_text("\n".join(relay_urls))

        # Set small batch size to test batching
        mock_seeder_brotr.config.batch.max_size = 100
        mock_seeder_brotr.insert_relay = AsyncMock(return_value=100)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file), to_validate=False))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)
        relays = parse_seed_file(seed_file)

        await seeder._seed_as_relays(relays)

        assert mock_seeder_brotr.insert_relay.call_count >= 2


# ============================================================================
# Run Tests
# ============================================================================


class TestSeederRun:
    """Tests for Seeder.run() method."""

    async def test_run_file_missing(self, mock_seeder_brotr: Brotr) -> None:
        """Test run with seed file missing."""
        config = SeederConfig(seed=SeedConfig(file_path="nonexistent.txt"))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        with patch.object(seeder._logger, "info") as mock_log:
            await seeder.run()
            mock_log.assert_any_call("cycle_completed", inserted=0)

    async def test_run_success(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test run completes successfully."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay.example.com\n")

        mock_seeder_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"url": "wss://relay.example.com"}]
        )
        mock_seeder_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        await seeder.run()

        mock_seeder_brotr.upsert_service_state.assert_called()

    async def test_run_logs_cycle_completion(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """Test run logs cycle completion."""
        seed_file = tmp_path / "seed_relays.txt"
        seed_file.write_text("wss://relay.example.com\n")

        mock_seeder_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            return_value=[{"url": "wss://relay.example.com"}]
        )
        mock_seeder_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        with patch.object(seeder._logger, "info") as mock_log:
            await seeder.run()
            # Check that cycle_completed was logged
            log_messages = [call[0][0] for call in mock_log.call_args_list]
            assert "cycle_completed" in log_messages


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestSeederErrorHandling:
    """Tests for error handling in Seeder."""

    async def test_database_error_handled(self, mock_seeder_brotr: Brotr, tmp_path: Path) -> None:
        """Test database errors are handled gracefully."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("wss://relay.example.com\n")

        mock_seeder_brotr._pool._mock_connection.fetch = AsyncMock(  # type: ignore[attr-defined]
            side_effect=Exception("Database error")
        )

        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file)))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        with pytest.raises(Exception, match="Database error"):
            await seeder.seed()

    async def test_postgres_error_in_seed_as_candidates(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """asyncpg.PostgresError in _seed_as_candidates returns 0."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("wss://relay.example.com\n")
        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file), to_validate=True))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        with patch(
            "bigbrotr.services.seeder.service.insert_relays_as_candidates",
            new_callable=AsyncMock,
            side_effect=asyncpg.PostgresError("connection lost"),
        ):
            result = await seeder.seed()

        assert result == 0

    async def test_postgres_error_in_seed_as_relays(
        self, mock_seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        """asyncpg.PostgresError in _seed_as_relays returns 0."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("wss://relay.example.com\n")
        config = SeederConfig(seed=SeedConfig(file_path=str(seed_file), to_validate=False))
        seeder = Seeder(brotr=mock_seeder_brotr, config=config)

        with patch(
            "bigbrotr.services.seeder.service.insert_relays",
            new_callable=AsyncMock,
            side_effect=asyncpg.PostgresError("connection lost"),
        ):
            result = await seeder.seed()

        assert result == 0

    async def test_invalid_url_logged_not_raised(self, tmp_path: Path) -> None:
        """Test invalid URLs are logged but don't raise exceptions."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("invalid://not-a-valid-relay-url\nwss://valid.relay.com\n")

        relays = parse_seed_file(seed_file)
        assert len(relays) == 1
