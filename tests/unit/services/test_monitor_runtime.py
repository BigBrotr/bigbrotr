"""Unit tests for monitor runtime helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from bigbrotr.services.common.configs import ClearnetConfig, NetworksConfig
from bigbrotr.services.monitor import (
    AnnouncementConfig,
    DiscoveryConfig,
    GeoConfig,
    MetadataFlags,
    MonitorConfig,
    ProcessingConfig,
)
from bigbrotr.services.monitor.resources import GeoReaders
from bigbrotr.services.monitor.runtime import (
    build_monitor_cycle_plan,
    close_cycle_resources,
    open_cycle_resources,
)


_NO_CHECKS = MetadataFlags(
    nip11_info=False,
    nip66_rtt=False,
    nip66_ssl=False,
    nip66_geo=False,
    nip66_net=False,
    nip66_dns=False,
    nip66_http=False,
)


def _make_config(**overrides: object) -> MonitorConfig:
    defaults: dict[str, object] = {
        "processing": ProcessingConfig(compute=_NO_CHECKS, store=_NO_CHECKS),
        "discovery": DiscoveryConfig(include=_NO_CHECKS),
        "announcement": AnnouncementConfig(include=_NO_CHECKS),
    }
    defaults.update(overrides)
    return MonitorConfig(**defaults)


class TestBuildMonitorCyclePlan:
    async def test_returns_none_without_enabled_networks(self) -> None:
        config = _make_config(networks=NetworksConfig(clearnet=ClearnetConfig(enabled=False)))
        network_semaphores = MagicMock()
        count_relays = AsyncMock()

        plan = await build_monitor_cycle_plan(
            brotr=AsyncMock(),
            config=config,
            network_semaphores=network_semaphores,
            now=1000,
            count_relays_fn=count_relays,
        )

        assert plan is None
        count_relays.assert_not_awaited()
        network_semaphores.max_concurrency.assert_not_called()

    async def test_caps_total_to_max_relays(self) -> None:
        config = _make_config(
            discovery=DiscoveryConfig(interval=300, include=_NO_CHECKS),
            processing=ProcessingConfig(
                chunk_size=25,
                max_relays=5,
                compute=_NO_CHECKS,
                store=_NO_CHECKS,
            ),
        )
        network_semaphores = MagicMock()
        network_semaphores.max_concurrency.return_value = 7
        count_relays = AsyncMock(return_value=9)
        brotr = AsyncMock()

        plan = await build_monitor_cycle_plan(
            brotr=brotr,
            config=config,
            network_semaphores=network_semaphores,
            now=1000,
            count_relays_fn=count_relays,
        )

        assert plan is not None
        assert plan.networks == (config.networks.get_enabled_networks()[0],)
        assert plan.monitored_before == 700
        assert plan.max_relays == 5
        assert plan.total == 5
        assert plan.max_concurrency == 7
        assert plan.chunk_size == 25
        count_relays.assert_awaited_once_with(
            brotr,
            700,
            config.networks.get_enabled_networks(),
        )
        network_semaphores.max_concurrency.assert_called_once_with(
            config.networks.get_enabled_networks()
        )


class TestCycleResources:
    async def test_open_cycle_resources_uses_enabled_geo_readers(self, tmp_path) -> None:
        config = _make_config(
            processing=ProcessingConfig(
                compute=MetadataFlags(nip66_geo=True, nip66_net=False),
                store=MetadataFlags(nip66_geo=True, nip66_net=False),
            ),
            geo=GeoConfig(
                city_database_path=str(tmp_path / "city.mmdb"),
                asn_database_path=str(tmp_path / "asn.mmdb"),
                city_download_url="https://example.com/city.mmdb",
                asn_download_url="https://example.com/asn.mmdb",
            ),
        )
        update_geo_databases = AsyncMock()
        open_geo_readers = AsyncMock()

        await open_cycle_resources(
            config=config,
            geo_readers=GeoReaders(),
            update_geo_databases_fn=update_geo_databases,
            open_geo_readers_fn=open_geo_readers,
        )

        update_geo_databases.assert_awaited_once()
        open_geo_readers.assert_awaited_once_with(
            city_path=str(tmp_path / "city.mmdb"),
            asn_path=None,
        )

    async def test_close_cycle_resources_disconnects_then_closes(self) -> None:
        operations: list[str] = []

        async def disconnect() -> None:
            operations.append("disconnect")

        def close() -> None:
            operations.append("close")

        await close_cycle_resources(
            clients_disconnect_fn=disconnect,
            geo_readers=GeoReaders(),
            close_geo_readers_fn=close,
        )

        assert operations == ["disconnect", "close"]
