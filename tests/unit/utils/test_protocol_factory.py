"""Unit tests for the ``bigbrotr.utils.protocol_factory`` module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from nostr_sdk import ConnectionTarget

from bigbrotr.utils.protocol_factory import build_client


class TestBuildClientProxyTarget:
    async def test_proxy_mode_targets_all_overlay_families(self) -> None:
        """Proxy-enabled clients use the shared ALL target, not onion-only mode."""
        builder = MagicMock()
        builder.opts.return_value = builder
        built_client = object()
        builder.build.return_value = built_client

        connection = MagicMock()
        connection.mode.return_value = connection
        connection.target.return_value = connection

        client_options = MagicMock()
        client_options.connection.return_value = "proxy-options"

        with (
            patch("bigbrotr.utils.protocol_factory.ClientBuilder", return_value=builder),
            patch("bigbrotr.utils.protocol_factory.Connection", return_value=connection),
            patch(
                "bigbrotr.utils.protocol_factory.ConnectionMode.PROXY",
                return_value="proxy-mode",
            ) as mock_proxy_mode,
            patch("bigbrotr.utils.protocol_factory.ClientOptions", return_value=client_options),
        ):
            result = await build_client(proxy_url="socks5://127.0.0.1:9050")

        assert result is built_client
        mock_proxy_mode.assert_called_once_with("127.0.0.1", 9050)
        connection.mode.assert_called_once_with("proxy-mode")
        connection.target.assert_called_once_with(ConnectionTarget.ALL)
        client_options.connection.assert_called_once_with(connection)
        builder.opts.assert_called_once_with("proxy-options")
