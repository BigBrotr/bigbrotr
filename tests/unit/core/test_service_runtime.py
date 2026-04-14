import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from bigbrotr.core.service_runtime import ServiceProcessRunner, ServiceRuntimeState


class TestServiceRuntimeState:
    async def test_wait_is_interruptible(self) -> None:
        state = ServiceRuntimeState()

        async def shutdown_later() -> None:
            await asyncio.sleep(0.01)
            state.request_shutdown()

        task = asyncio.create_task(shutdown_later())
        result = await state.wait(1.0)
        await task

        assert result is True
        assert state.is_running is False

    async def test_wait_times_out_when_running(self) -> None:
        state = ServiceRuntimeState()

        result = await state.wait(0.01)

        assert result is False
        assert state.is_running is True


class TestServiceProcessRunner:
    async def test_removes_registered_signal_handlers(self) -> None:
        service = MagicMock()
        service.service_name = "runtime_test"
        service.config.metrics.enabled = False
        service.run_forever = AsyncMock()
        service.__aenter__ = AsyncMock(return_value=service)
        service.__aexit__ = AsyncMock(return_value=None)

        metrics_server = MagicMock()
        metrics_server.stop = AsyncMock()

        loop = asyncio.get_running_loop()
        removed: list[int] = []

        with (
            patch.object(loop, "add_signal_handler"),
            patch.object(loop, "remove_signal_handler", side_effect=removed.append),
        ):
            runner = ServiceProcessRunner(
                service,
                logger=service._logger,
                start_metrics_server_fn=AsyncMock(return_value=metrics_server),
            )
            result = await runner.run_continuous()

        assert result == 0
        assert removed
        metrics_server.stop.assert_awaited_once()

    async def test_logs_warning_when_signal_handlers_are_unsupported(self) -> None:
        service = MagicMock()
        service.service_name = "runtime_test"
        service.config.metrics.enabled = False
        service.run_forever = AsyncMock()
        service.__aenter__ = AsyncMock(return_value=service)
        service.__aexit__ = AsyncMock(return_value=None)

        metrics_server = MagicMock()
        metrics_server.stop = AsyncMock()

        loop = asyncio.get_running_loop()

        with (
            patch.object(loop, "add_signal_handler", side_effect=NotImplementedError),
            patch.object(service._logger, "warning") as mock_warning,
        ):
            runner = ServiceProcessRunner(
                service,
                logger=service._logger,
                start_metrics_server_fn=AsyncMock(return_value=metrics_server),
            )
            result = await runner.run_continuous()

        assert result == 0
        mock_warning.assert_called_once_with("signal_handlers_unsupported")
        metrics_server.stop.assert_awaited_once()
