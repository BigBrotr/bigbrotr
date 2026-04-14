import asyncio
import signal
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

from bigbrotr.__main__ import run_service
from bigbrotr.core.brotr import Brotr


class TestRunService:
    async def test_oneshot_success(self, mock_brotr_for_cli: Brotr) -> None:
        from bigbrotr.services.seeder import Seeder

        service_dict = {"seed": {"file_path": "nonexistent.txt"}}

        result = await run_service(
            service_name="seeder",
            service_class=Seeder,
            brotr=mock_brotr_for_cli,
            service_dict=service_dict,
            once=True,
        )

        assert result == 0

    async def test_oneshot_empty_dict(self, mock_brotr_for_cli: Brotr) -> None:
        from bigbrotr.services.seeder import Seeder

        result = await run_service(
            service_name="seeder",
            service_class=Seeder,
            brotr=mock_brotr_for_cli,
            service_dict={},
            once=True,
        )

        assert result == 0

    async def test_oneshot_failure(self, mock_brotr_for_cli: Brotr) -> None:
        from bigbrotr.services.seeder import Seeder

        service_dict = {"seed": {"file_path": "nonexistent.txt"}}

        with patch.object(Seeder, "run", AsyncMock(side_effect=Exception("Test error"))):
            result = await run_service(
                service_name="seeder",
                service_class=Seeder,
                brotr=mock_brotr_for_cli,
                service_dict=service_dict,
                once=True,
            )

        assert result == 1

    async def test_continuous_success(self, mock_brotr_for_cli: Brotr) -> None:
        from bigbrotr.services.finder import Finder

        service_dict = {
            "interval": 60.0,
            "max_consecutive_failures": 5,
            "discovery": {"enabled_sources": []},
        }

        with patch.object(Finder, "run_forever", AsyncMock()):
            result = await run_service(
                service_name="finder",
                service_class=Finder,
                brotr=mock_brotr_for_cli,
                service_dict=service_dict,
                once=False,
            )

        assert result == 0

    async def test_continuous_failure(self, mock_brotr_for_cli: Brotr) -> None:
        from bigbrotr.services.finder import Finder

        service_dict = {
            "interval": 60.0,
            "max_consecutive_failures": 5,
            "discovery": {"enabled_sources": []},
        }

        with patch.object(Finder, "run_forever", AsyncMock(side_effect=Exception("Test error"))):
            result = await run_service(
                service_name="finder",
                service_class=Finder,
                brotr=mock_brotr_for_cli,
                service_dict=service_dict,
                once=False,
            )

        assert result == 1

    async def test_continuous_starts_and_stops_metrics_server(
        self, mock_brotr_for_cli: Brotr, mock_metrics_server: MagicMock
    ) -> None:
        from bigbrotr.services.finder import Finder

        service_dict = {
            "interval": 60.0,
            "max_consecutive_failures": 5,
            "discovery": {"enabled_sources": []},
            "metrics": {"enabled": True, "host": "127.0.0.1", "port": 9999},
        }

        with (
            patch.object(Finder, "run_forever", AsyncMock()),
            patch(
                "bigbrotr.__main__.start_metrics_server",
                AsyncMock(return_value=mock_metrics_server),
            ) as mock_start,
        ):
            await run_service(
                service_name="finder",
                service_class=Finder,
                brotr=mock_brotr_for_cli,
                service_dict=service_dict,
                once=False,
            )

            mock_start.assert_called_once()
            mock_metrics_server.stop.assert_called_once()

    async def test_continuous_stops_metrics_server_on_failure(
        self, mock_brotr_for_cli: Brotr, mock_metrics_server: MagicMock
    ) -> None:
        from bigbrotr.services.finder import Finder

        service_dict = {
            "interval": 60.0,
            "max_consecutive_failures": 5,
            "discovery": {"enabled_sources": []},
            "metrics": {"enabled": True},
        }

        with (
            patch.object(Finder, "run_forever", AsyncMock(side_effect=Exception("Test error"))),
            patch(
                "bigbrotr.__main__.start_metrics_server",
                AsyncMock(return_value=mock_metrics_server),
            ),
        ):
            await run_service(
                service_name="finder",
                service_class=Finder,
                brotr=mock_brotr_for_cli,
                service_dict=service_dict,
                once=False,
            )

            mock_metrics_server.stop.assert_called_once()

    async def test_oneshot_does_not_start_metrics_server(self, mock_brotr_for_cli: Brotr) -> None:
        from bigbrotr.services.seeder import Seeder

        service_dict = {
            "seed": {"file_path": "nonexistent.txt"},
            "metrics": {"enabled": True},
        }

        with patch("bigbrotr.__main__.start_metrics_server", AsyncMock()) as mock_start:
            await run_service(
                service_name="seeder",
                service_class=Seeder,
                brotr=mock_brotr_for_cli,
                service_dict=service_dict,
                once=True,
            )

            mock_start.assert_not_called()


class TestSignalHandling:
    async def test_signal_handlers_registered_via_loop(
        self, mock_brotr_for_cli: Brotr, mock_metrics_server: MagicMock
    ) -> None:
        from bigbrotr.services.finder import Finder

        service_dict = {
            "interval": 60.0,
            "max_consecutive_failures": 5,
            "discovery": {"enabled_sources": []},
        }

        registered_signals: list[signal.Signals] = []
        loop = asyncio.get_running_loop()

        def tracking_add(
            sig: signal.Signals,
            callback: Callable[..., object],
            *args: object,
        ) -> None:
            registered_signals.append(sig)

        with (
            patch.object(Finder, "run_forever", AsyncMock()),
            patch(
                "bigbrotr.__main__.start_metrics_server",
                AsyncMock(return_value=mock_metrics_server),
            ),
            patch.object(loop, "add_signal_handler", side_effect=tracking_add),
        ):
            await run_service(
                service_name="finder",
                service_class=Finder,
                brotr=mock_brotr_for_cli,
                service_dict=service_dict,
                once=False,
            )

        assert signal.SIGINT in registered_signals
        assert signal.SIGTERM in registered_signals

    async def test_signal_handler_calls_request_shutdown(
        self, mock_brotr_for_cli: Brotr, mock_metrics_server: MagicMock
    ) -> None:
        from bigbrotr.services.finder import Finder

        service_dict = {
            "interval": 60.0,
            "max_consecutive_failures": 5,
            "discovery": {"enabled_sources": []},
        }

        captured_callbacks: list[
            tuple[signal.Signals, Callable[..., object], tuple[object, ...]]
        ] = []

        def capture_add(
            sig: signal.Signals,
            callback: Callable[..., object],
            *args: object,
        ) -> None:
            captured_callbacks.append((sig, callback, args))

        loop = asyncio.get_running_loop()

        with (
            patch.object(Finder, "run_forever", AsyncMock()),
            patch(
                "bigbrotr.__main__.start_metrics_server",
                AsyncMock(return_value=mock_metrics_server),
            ),
            patch.object(loop, "add_signal_handler", side_effect=capture_add),
            patch.object(Finder, "request_shutdown") as mock_shutdown,
        ):
            await run_service(
                service_name="finder",
                service_class=Finder,
                brotr=mock_brotr_for_cli,
                service_dict=service_dict,
                once=False,
            )

            assert len(captured_callbacks) == 2
            _, callback, args = captured_callbacks[0]
            callback(*args)
            mock_shutdown.assert_called_once()
