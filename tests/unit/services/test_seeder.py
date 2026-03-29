"""Unit tests for the seeder service package."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from bigbrotr.core.brotr import Brotr, BrotrConfig
from bigbrotr.models import Relay
from bigbrotr.services.seeder import SeedConfig, Seeder, SeederConfig
from bigbrotr.services.seeder.queries import insert_relays
from bigbrotr.services.seeder.utils import parse_seed_file


if TYPE_CHECKING:
    from pathlib import Path


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def seeder_brotr(mock_brotr: Brotr) -> Brotr:
    mock_brotr._pool._mock_connection.fetch = AsyncMock(return_value=[])  # type: ignore[attr-defined]
    mock_brotr._pool._mock_connection.execute = AsyncMock()  # type: ignore[attr-defined]

    mock_batch_config = MagicMock()
    mock_batch_config.max_size = 100
    mock_config = MagicMock(spec=BrotrConfig)
    mock_config.batch = mock_batch_config
    mock_config.timeouts = MagicMock()
    mock_config.timeouts.query = 30.0
    mock_brotr._config = mock_config

    return mock_brotr


# ============================================================================
# Configs
# ============================================================================


class TestSeedConfig:
    def test_defaults(self) -> None:
        config = SeedConfig()
        assert config.file_path == "static/seed_relays.txt"
        assert config.to_validate is True

    def test_custom(self) -> None:
        config = SeedConfig(file_path="custom.txt", to_validate=False)
        assert config.file_path == "custom.txt"
        assert config.to_validate is False

    def test_empty_path_rejected(self) -> None:
        with pytest.raises(ValueError):
            SeedConfig(file_path="")


class TestSeederConfig:
    def test_defaults(self) -> None:
        config = SeederConfig()
        assert config.seed.file_path == "static/seed_relays.txt"
        assert config.seed.to_validate is True
        assert config.interval == 300.0
        assert config.max_consecutive_failures == 5

    def test_custom_nested(self) -> None:
        config = SeederConfig(seed=SeedConfig(file_path="x.txt", to_validate=False))
        assert config.seed.file_path == "x.txt"
        assert config.seed.to_validate is False

    def test_from_dict(self) -> None:
        config = SeederConfig(seed=SeedConfig(file_path="t.txt"), interval=120.0)
        assert config.seed.file_path == "t.txt"
        assert config.interval == 120.0


# ============================================================================
# Utils — parse_seed_file
# ============================================================================


class TestParseSeedFile:
    def test_valid_relays(self, tmp_path: Path) -> None:
        f = tmp_path / "seed.txt"
        f.write_text("wss://relay1.example.com\nwss://relay2.example.com\n")
        relays = parse_seed_file(f)
        assert len(relays) == 2
        assert {r.url for r in relays} == {"wss://relay1.example.com", "wss://relay2.example.com"}

    def test_skips_comments_and_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "seed.txt"
        f.write_text("# comment\n\nwss://relay.example.com\n# another\n")
        relays = parse_seed_file(f)
        assert len(relays) == 1
        assert relays[0].url == "wss://relay.example.com"

    def test_skips_invalid_urls(self, tmp_path: Path) -> None:
        f = tmp_path / "seed.txt"
        f.write_text("invalid\nwss://valid.relay.com\nnot-a-relay\n")
        relays = parse_seed_file(f)
        assert len(relays) == 1
        assert relays[0].url == "wss://valid.relay.com"

    def test_strips_whitespace(self, tmp_path: Path) -> None:
        f = tmp_path / "seed.txt"
        f.write_text("  wss://relay.example.com  \n")
        assert parse_seed_file(f)[0].url == "wss://relay.example.com"

    def test_tor_and_i2p(self, tmp_path: Path) -> None:
        from tests.fixtures.relays import ONION_HOST

        f = tmp_path / "seed.txt"
        f.write_text(f"ws://{ONION_HOST}.onion\nws://example.i2p\n")
        assert len(parse_seed_file(f)) == 2

    @pytest.mark.parametrize(
        "setup",
        [
            pytest.param("missing", id="file_not_found"),
            pytest.param("directory", id="directory_path"),
        ],
    )
    def test_returns_empty_on_path_errors(self, tmp_path: Path, setup: str) -> None:
        path = tmp_path / "missing.txt" if setup == "missing" else tmp_path
        assert parse_seed_file(path) == []

    def test_permission_error(self, tmp_path: Path) -> None:
        f = tmp_path / "seed.txt"
        f.write_text("wss://relay.example.com")
        f.chmod(0o000)
        assert parse_seed_file(f) == []
        f.chmod(0o644)

    def test_unicode_decode_error(self, tmp_path: Path) -> None:
        f = tmp_path / "seed.txt"
        f.write_bytes(b"\xff\xfe" + b"\x00" * 50)
        assert parse_seed_file(f) == []


# ============================================================================
# Queries — insert_relays
# ============================================================================


class TestInsertRelays:
    async def test_delegates_to_brotr(self) -> None:
        brotr = MagicMock()
        brotr.insert_relay = AsyncMock(return_value=2)
        brotr.config.batch.max_size = 1

        relays = [Relay("wss://a.example.com"), Relay("wss://b.example.com")]
        result = await insert_relays(brotr, relays)

        assert result == 4  # 2 batches x 2 each
        assert brotr.insert_relay.await_count == 2

    async def test_empty_returns_zero(self) -> None:
        brotr = MagicMock()
        brotr.insert_relay = AsyncMock(return_value=0)
        brotr.config.batch.max_size = 1000

        assert await insert_relays(brotr, []) == 0
        brotr.insert_relay.assert_not_awaited()

    async def test_single_batch(self) -> None:
        brotr = MagicMock()
        brotr.insert_relay = AsyncMock(return_value=3)
        brotr.config.batch.max_size = 1000

        relays = [
            Relay("wss://a.example.com"),
            Relay("wss://b.example.com"),
            Relay("wss://c.example.com"),
        ]
        assert await insert_relays(brotr, relays) == 3
        brotr.insert_relay.assert_awaited_once()


# ============================================================================
# Service — Seeder
# ============================================================================


class TestSeederInit:
    def test_defaults(self, seeder_brotr: Brotr) -> None:
        seeder = Seeder(brotr=seeder_brotr)
        assert seeder.SERVICE_NAME == "seeder"
        assert seeder.CONFIG_CLASS is SeederConfig
        assert seeder.config.seed.file_path == "static/seed_relays.txt"
        assert seeder._logger is not None

    def test_custom_config(self, seeder_brotr: Brotr) -> None:
        config = SeederConfig(seed=SeedConfig(file_path="custom.txt"))
        seeder = Seeder(brotr=seeder_brotr, config=config)
        assert seeder.config.seed.file_path == "custom.txt"

    def test_from_dict(self, seeder_brotr: Brotr) -> None:
        seeder = Seeder.from_dict(
            {"seed": {"file_path": "x.txt", "to_validate": False}},
            brotr=seeder_brotr,
        )
        assert seeder.config.seed.file_path == "x.txt"
        assert seeder.config.seed.to_validate is False


class TestSeed:
    async def test_file_not_found_returns_zero(self, seeder_brotr: Brotr) -> None:
        config = SeederConfig(seed=SeedConfig(file_path="nonexistent.txt"))
        seeder = Seeder(brotr=seeder_brotr, config=config)
        assert await seeder.seed() == 0

    async def test_empty_file_returns_zero(self, seeder_brotr: Brotr, tmp_path: Path) -> None:
        f = tmp_path / "seed.txt"
        f.write_text("")
        config = SeederConfig(seed=SeedConfig(file_path=str(f)))
        seeder = Seeder(brotr=seeder_brotr, config=config)
        assert await seeder.seed() == 0

    async def test_as_candidates(self, seeder_brotr: Brotr, tmp_path: Path) -> None:
        f = tmp_path / "seed.txt"
        f.write_text("wss://r1.example.com\nwss://r2.example.com\n")

        config = SeederConfig(seed=SeedConfig(file_path=str(f), to_validate=True))
        seeder = Seeder(brotr=seeder_brotr, config=config)

        with patch(
            "bigbrotr.services.seeder.service.insert_relays_as_candidates",
            new_callable=AsyncMock,
            return_value=2,
        ) as mock_insert:
            assert await seeder.seed() == 2
            mock_insert.assert_awaited_once()
            relays = mock_insert.call_args[0][1]
            assert len(relays) == 2

    async def test_as_relays(self, seeder_brotr: Brotr, tmp_path: Path) -> None:
        f = tmp_path / "seed.txt"
        f.write_text("wss://r1.example.com\nwss://r2.example.com\n")

        config = SeederConfig(seed=SeedConfig(file_path=str(f), to_validate=False))
        seeder = Seeder(brotr=seeder_brotr, config=config)

        with patch(
            "bigbrotr.services.seeder.service.insert_relays",
            new_callable=AsyncMock,
            return_value=2,
        ) as mock_insert:
            assert await seeder.seed() == 2
            mock_insert.assert_awaited_once()
            relays = mock_insert.call_args[0][1]
            assert len(relays) == 2

    async def test_only_valid_urls_passed_to_insert(
        self, seeder_brotr: Brotr, tmp_path: Path
    ) -> None:
        f = tmp_path / "seed.txt"
        f.write_text("# Comment\n\ninvalid\nwss://relay.example.com\n")

        config = SeederConfig(seed=SeedConfig(file_path=str(f)))
        seeder = Seeder(brotr=seeder_brotr, config=config)

        with patch(
            "bigbrotr.services.seeder.service.insert_relays_as_candidates",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_insert:
            assert await seeder.seed() == 1
            relays = mock_insert.call_args[0][1]
            assert len(relays) == 1
            assert relays[0].url == "wss://relay.example.com"


class TestSeederRun:
    async def test_run_delegates_to_seed(self, seeder_brotr: Brotr) -> None:
        seeder = Seeder(brotr=seeder_brotr)

        with patch.object(seeder, "seed", new_callable=AsyncMock, return_value=5) as mock_seed:
            await seeder.run()
            mock_seed.assert_awaited_once()


class TestSeederCleanup:
    async def test_cleanup_returns_zero(self, seeder_brotr: Brotr) -> None:
        seeder = Seeder(brotr=seeder_brotr)
        assert await seeder.cleanup() == 0


# ============================================================================
# Error propagation
# ============================================================================


class TestSeederErrors:
    @pytest.mark.parametrize(
        ("to_validate", "patch_target"),
        [
            (True, "bigbrotr.services.seeder.service.insert_relays_as_candidates"),
            (False, "bigbrotr.services.seeder.service.insert_relays"),
        ],
        ids=["candidates_path", "relays_path"],
    )
    async def test_postgres_error_propagates(
        self,
        seeder_brotr: Brotr,
        tmp_path: Path,
        to_validate: bool,
        patch_target: str,
    ) -> None:
        f = tmp_path / "seed.txt"
        f.write_text("wss://relay.example.com\n")

        config = SeederConfig(seed=SeedConfig(file_path=str(f), to_validate=to_validate))
        seeder = Seeder(brotr=seeder_brotr, config=config)

        with (
            patch(
                patch_target,
                new_callable=AsyncMock,
                side_effect=asyncpg.PostgresError("connection lost"),
            ),
            pytest.raises(asyncpg.PostgresError),
        ):
            await seeder.seed()
