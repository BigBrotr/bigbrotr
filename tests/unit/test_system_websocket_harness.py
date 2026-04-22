from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from websockets.sync.client import connect

from tests.system.harness.websocket import LocalTlsWebSocketRuntime


if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class TestLocalTlsWebSocketRuntime:
    def test_proxy_mode_requires_backend_url(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="requires a backend_url"):
            LocalTlsWebSocketRuntime(tmp_path / "proxy-runtime", mode="proxy")

    def test_public_url_requires_started_runtime(self, tmp_path: Path) -> None:
        runtime = LocalTlsWebSocketRuntime(tmp_path / "blackhole-runtime")

        with pytest.raises(RuntimeError, match="has not been started yet"):
            runtime.public_url("/")

    def test_blackhole_runtime_records_client_messages(self, tmp_path: Path) -> None:
        runtime = LocalTlsWebSocketRuntime(tmp_path / "blackhole-runtime")

        with runtime:
            with connect(
                runtime.public_url("/validator"),
                ssl=runtime.client_ssl_context(),
                open_timeout=runtime.timeout,
                close_timeout=runtime.timeout,
            ) as websocket:
                websocket.send('["REQ","validator",{"kinds":[1]}]')

            sessions = self._wait_until(
                lambda: runtime.sessions(path="/validator"),
                is_ready=lambda records: len(records) == 1,
            )

        assert len(sessions) == 1
        assert sessions[0].path == "/validator"
        assert sessions[0].mode == "blackhole"
        assert sessions[0].received_messages == ('["REQ","validator",{"kinds":[1]}]',)

    def test_invalid_text_runtime_replies_with_non_nostr_frame(self, tmp_path: Path) -> None:
        runtime = LocalTlsWebSocketRuntime(tmp_path / "invalid-text-runtime", mode="invalid-text")

        with runtime:
            with connect(
                runtime.public_url("/validator"),
                ssl=runtime.client_ssl_context(),
                open_timeout=runtime.timeout,
                close_timeout=runtime.timeout,
            ) as websocket:
                websocket.send('["REQ","validator",{"kinds":[1]}]')
                assert websocket.recv() == "not nostr"

            sessions = self._wait_until(
                lambda: runtime.sessions(path="/validator"),
                is_ready=lambda records: len(records) == 1,
            )

        assert len(sessions) == 1
        assert sessions[0].mode == "invalid-text"
        assert sessions[0].received_messages == ('["REQ","validator",{"kinds":[1]}]',)

    @staticmethod
    def _wait_until(
        fetch_snapshot: Callable[[], object],
        *,
        is_ready: Callable[[object], bool],
        timeout: float = 2.0,
        poll_interval: float = 0.05,
    ) -> object:
        import time

        deadline = time.monotonic() + timeout
        last_snapshot = fetch_snapshot()
        while time.monotonic() < deadline:
            last_snapshot = fetch_snapshot()
            if is_ready(last_snapshot):
                return last_snapshot
            time.sleep(poll_interval)
        raise RuntimeError(f"Timed out waiting for websocket harness state: {last_snapshot!r}")
