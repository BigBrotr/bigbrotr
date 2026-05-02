"""Unit tests for the ``bigbrotr.utils.protocol_factory`` module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from nostr_sdk import ConnectionTarget

from bigbrotr.utils.protocol_factory import build_client


class TestBuildClientValidation:
    async def test_rejects_non_bool_allow_insecure_before_builder(self) -> None:
        """Non-bool insecure-policy aliases fail before builder setup starts."""
        with (
            patch("bigbrotr.utils.protocol_factory.ClientBuilder") as mock_builder,
            pytest.raises(ValueError, match="allow_insecure must be a bool"),
        ):
            await build_client(allow_insecure=1)  # type: ignore[arg-type]

        mock_builder.assert_not_called()

    @pytest.mark.parametrize(
        "proxy_url",
        [True, "", "   ", "garbage", "socks5://:9050", "socks5://127.0.0.1:0"],
    )
    async def test_rejects_invalid_proxy_url_before_builder(self, proxy_url: object) -> None:
        """Malformed proxy URLs fail before builder setup starts."""
        with (
            patch("bigbrotr.utils.protocol_factory.ClientBuilder") as mock_builder,
            pytest.raises(
                ValueError,
                match="proxy_url must be a valid proxy URL with scheme and hostname",
            ),
        ):
            await build_client(proxy_url=proxy_url)  # type: ignore[arg-type]

        mock_builder.assert_not_called()


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
