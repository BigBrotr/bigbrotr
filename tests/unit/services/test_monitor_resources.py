"""Unit tests for monitor-owned runtime resources."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from bigbrotr.services.monitor.resources import GeoReaders, RelayClients


class TestGeoReadersOpen:
    async def test_open_city_reader(self) -> None:
        readers = GeoReaders()
        mock_reader = MagicMock()

        with patch(
            "bigbrotr.services.monitor.resources.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=mock_reader,
        ) as mock_to_thread:
            await readers.open(city_path="/data/city.mmdb")

        mock_to_thread.assert_awaited_once()
        assert readers.city is mock_reader
        assert readers.asn is None

    async def test_open_asn_reader(self) -> None:
        readers = GeoReaders()
        mock_reader = MagicMock()

        with patch(
            "bigbrotr.services.monitor.resources.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=mock_reader,
        ) as mock_to_thread:
            await readers.open(asn_path="/data/asn.mmdb")

        mock_to_thread.assert_awaited_once()
        assert readers.asn is mock_reader
        assert readers.city is None

    async def test_open_both_readers(self) -> None:
        readers = GeoReaders()
        mock_city = MagicMock()
        mock_asn = MagicMock()

        with patch(
            "bigbrotr.services.monitor.resources.asyncio.to_thread",
            new_callable=AsyncMock,
            side_effect=[mock_city, mock_asn],
        ):
            await readers.open(city_path="/data/city.mmdb", asn_path="/data/asn.mmdb")

        assert readers.city is mock_city
        assert readers.asn is mock_asn

    async def test_open_no_paths_does_nothing(self) -> None:
        readers = GeoReaders()

        with patch(
            "bigbrotr.services.monitor.resources.asyncio.to_thread",
            new_callable=AsyncMock,
        ) as mock_to_thread:
            await readers.open()

        mock_to_thread.assert_not_awaited()
        assert readers.city is None
        assert readers.asn is None


class TestGeoReadersClose:
    def test_close_both_readers(self) -> None:
        readers = GeoReaders()
        readers.city = MagicMock()
        readers.asn = MagicMock()
        city_ref = readers.city
        asn_ref = readers.asn

        readers.close()

        city_ref.close.assert_called_once()
        asn_ref.close.assert_called_once()
        assert readers.city is None
        assert readers.asn is None

    def test_close_city_only(self) -> None:
        readers = GeoReaders()
        readers.city = MagicMock()
        city_ref = readers.city

        readers.close()

        city_ref.close.assert_called_once()
        assert readers.city is None
        assert readers.asn is None

    def test_close_asn_only(self) -> None:
        readers = GeoReaders()
        readers.asn = MagicMock()
        asn_ref = readers.asn

        readers.close()

        asn_ref.close.assert_called_once()
        assert readers.asn is None

    def test_close_no_readers_is_idempotent(self) -> None:
        readers = GeoReaders()
        readers.close()
        assert readers.city is None
        assert readers.asn is None


def _make_clients(*, allow_insecure: bool = False) -> RelayClients:
    mock_keys = MagicMock()
    mock_networks = MagicMock()
    net_cfg = MagicMock()
    net_cfg.timeout = 10.0
    mock_networks.get.return_value = net_cfg
    mock_networks.get_proxy_url.return_value = None
    return RelayClients(mock_keys, mock_networks, allow_insecure=allow_insecure)


def _make_relay(url: str = "wss://relay.example.com", network: str = "clearnet") -> MagicMock:
    relay = MagicMock()
    relay.url = url
    relay.network = network
    return relay


class TestRelayClientsGet:
    async def test_get_connects_and_caches(self) -> None:
        clients = _make_clients()
        relay = _make_relay()
        mock_client = MagicMock()

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            result = await clients.get(relay)
            assert result is mock_client

            result2 = await clients.get(relay)
            assert result2 is mock_client

    async def test_get_returns_none_on_connection_failure(self) -> None:
        clients = _make_clients()
        relay = _make_relay()

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            side_effect=OSError("connection refused"),
        ):
            result = await clients.get(relay)
            assert result is None

    async def test_get_returns_none_for_previously_failed_relay(self) -> None:
        clients = _make_clients()
        relay = _make_relay()

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            side_effect=TimeoutError("timed out"),
        ):
            await clients.get(relay)

        result = await clients.get(relay)
        assert result is None

    async def test_get_uses_proxy_url_and_timeout(self) -> None:
        clients = _make_clients(allow_insecure=True)
        relay = _make_relay()
        clients._manager._networks.get_proxy_url.return_value = "socks5://tor:9050"

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ) as mock_connect:
            await clients.get(relay)

        mock_connect.assert_awaited_once_with(
            relay,
            keys=clients._manager._keys,
            proxy_url="socks5://tor:9050",
            timeout=10.0,
            allow_insecure=True,
        )


class TestRelayClientsGetMany:
    async def test_get_many_returns_connected_clients(self) -> None:
        clients = _make_clients()
        r1 = _make_relay("wss://r1.example.com")
        r2 = _make_relay("wss://r2.example.com")
        mock_c1 = MagicMock()
        mock_c2 = MagicMock()

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            side_effect=[mock_c1, mock_c2],
        ):
            result = await clients.get_many([r1, r2])

        assert result == [mock_c1, mock_c2]

    async def test_get_many_filters_failed_connections(self) -> None:
        clients = _make_clients()
        r1 = _make_relay("wss://r1.example.com")
        r2 = _make_relay("wss://r2.example.com")
        mock_c1 = MagicMock()

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            side_effect=[mock_c1, OSError("fail")],
        ):
            result = await clients.get_many([r1, r2])

        assert result == [mock_c1]

    async def test_get_many_empty_list(self) -> None:
        clients = _make_clients()
        result = await clients.get_many([])
        assert result == []


class TestRelayClientsDisconnect:
    async def test_disconnect_shuts_down_all_clients(self) -> None:
        clients = _make_clients()
        r1 = _make_relay("wss://r1.example.com")
        r2 = _make_relay("wss://r2.example.com")
        mock_c1 = AsyncMock()
        mock_c2 = AsyncMock()

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            side_effect=[mock_c1, mock_c2],
        ):
            await clients.get(r1)
            await clients.get(r2)

        await clients.disconnect()

        mock_c1.shutdown.assert_awaited_once()
        mock_c2.shutdown.assert_awaited_once()
        assert clients._manager.relay_clients == {}
        assert clients._manager.failed_relays == set()

    async def test_disconnect_handles_shutdown_errors(self) -> None:
        clients = _make_clients()
        relay = _make_relay()
        mock_client = AsyncMock()
        mock_client.shutdown.side_effect = RuntimeError("shutdown failed")

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            await clients.get(relay)

        await clients.disconnect()

        assert clients._manager.relay_clients == {}

    async def test_disconnect_clears_failed_set(self) -> None:
        clients = _make_clients()
        relay = _make_relay()

        with patch(
            "bigbrotr.utils.protocol.connect_relay",
            new_callable=AsyncMock,
            side_effect=OSError("fail"),
        ):
            await clients.get(relay)

        assert len(clients._manager.failed_relays) == 1
        await clients.disconnect()
        assert clients._manager.failed_relays == set()
