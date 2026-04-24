from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from websockets.exceptions import ConnectionClosedOK
from websockets.sync.client import connect

from tests.system.harness.websocket import LocalTlsWebSocketRuntime


if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@dataclass(slots=True)
class _ProxySession:
    received_messages: list[str] = field(default_factory=list)


class _BlockingProxyConnection:
    def __init__(
        self,
        *,
        queued_messages: tuple[str, ...] = (),
        close_after_messages: bool = False,
        ignore_close_without_timeout: bool = False,
    ) -> None:
        self._messages = list(queued_messages)
        self._close_after_messages = close_after_messages
        self._ignore_close_without_timeout = ignore_close_without_timeout
        self._closed = False
        self._release = threading.Event()
        self.sent_messages: list[str] = []

    def recv(self, timeout: float | None = None) -> str:
        if self._messages:
            message = self._messages.pop(0)
            if not self._messages and self._close_after_messages:
                self._closed = True
            return message
        if self._closed and not self._ignore_close_without_timeout:
            raise ConnectionClosedOK(None, None)
        if timeout is None and self._ignore_close_without_timeout:
            self._release.wait()
            raise ConnectionClosedOK(None, None)
        if timeout is not None:
            self._release.wait(timeout)
            if self._closed:
                raise ConnectionClosedOK(None, None)
            raise TimeoutError
        raise ConnectionClosedOK(None, None)

    def send(self, message: str) -> None:
        if self._closed:
            raise ConnectionClosedOK(None, None)
        self.sent_messages.append(message)

    def close(self) -> None:
        self._closed = True

    def release(self) -> None:
        self._release.set()


class TestLocalTlsWebSocketRuntime:
    def test_proxy_mode_requires_backend_url(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="requires a backend_url"):
            LocalTlsWebSocketRuntime(tmp_path / "proxy-runtime", mode="proxy")

    def test_http_backend_url_requires_proxy_mode(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="requires proxy mode"):
            LocalTlsWebSocketRuntime(
                tmp_path / "blackhole-runtime",
                http_backend_url="http://backend.example.test",
            )

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

    def test_http_backend_request_url_uses_backend_origin(self, tmp_path: Path) -> None:
        runtime = LocalTlsWebSocketRuntime(
            tmp_path / "proxy-runtime",
            mode="proxy",
            backend_url="ws://relay.example.test:8080",
            http_backend_url="http://relay.example.test:8080/base",
        )

        assert runtime._http_backend_request_url("/nip11?ignored=true") == (
            "http://relay.example.test:8080/nip11"
        )

    def test_proxy_connection_stops_idle_peer_threads_with_polling_recv(
        self,
        tmp_path: Path,
    ) -> None:
        runtime = LocalTlsWebSocketRuntime(
            tmp_path / "proxy-runtime",
            mode="proxy",
            backend_url="ws://relay.example.test:8080",
            timeout=0.2,
            poll_interval=0.01,
        )
        client = _BlockingProxyConnection(
            queued_messages=('["REQ","validator",{"kinds":[1]}]',),
            close_after_messages=True,
        )
        backend = _BlockingProxyConnection(ignore_close_without_timeout=True)
        session = _ProxySession()

        thread = threading.Thread(
            target=runtime._proxy_connection,
            args=(client, backend, session),
            daemon=True,
        )
        thread.start()
        thread.join(timeout=1.0)
        if thread.is_alive():
            backend.release()
            pytest.fail("proxy connection did not stop after the source side closed")

        assert backend.sent_messages == ['["REQ","validator",{"kinds":[1]}]']
        assert session.received_messages == ['["REQ","validator",{"kinds":[1]}]']

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
