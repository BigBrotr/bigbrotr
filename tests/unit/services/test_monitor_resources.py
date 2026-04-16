"""Unit tests for monitor-owned runtime resources."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from bigbrotr.services.monitor.resources import GeoReaders


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
