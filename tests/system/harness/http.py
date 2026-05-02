"""Local HTTP fixture helpers for higher-band system tests."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING
from urllib import error, request


if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


DEFAULT_HTTP_FIXTURE_TIMEOUT = 5.0
DEFAULT_HTTP_FIXTURE_POLL_INTERVAL = 0.1


@dataclass(frozen=True, slots=True)
class HttpFixtureRequest:
    """One request observed by the local HTTP fixture runtime."""

    method: str
    path: str
    headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class HttpFixtureResponse:
    """One configured response served by the local HTTP fixture runtime."""

    status: int = HTTPStatus.OK
    body: object = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)


class _HttpFixtureHandler(BaseHTTPRequestHandler):
    server: ThreadingHTTPServer

    def do_GET(self) -> None:
        runtime = self.server.runtime  # type: ignore[attr-defined]
        runtime._handle_request(self)

    def log_message(self, *_args: object) -> None:
        return


@dataclass(slots=True)
class LocalHttpFixtureRuntime:
    """Host-side HTTP fixture accessible from composed Docker services."""

    runtime_dir: Path
    listen_host: str = "0.0.0.0"
    public_host: str = "127.0.0.1"
    docker_host: str = "host.docker.internal"
    timeout: float = DEFAULT_HTTP_FIXTURE_TIMEOUT
    poll_interval: float = DEFAULT_HTTP_FIXTURE_POLL_INTERVAL
    _server: ThreadingHTTPServer | None = field(init=False, default=None, repr=False)
    _thread: threading.Thread | None = field(init=False, default=None, repr=False)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock, repr=False)
    _routes: dict[str, HttpFixtureResponse] = field(init=False, default_factory=dict, repr=False)
    _requests: list[HttpFixtureRequest] = field(init=False, default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.timeout <= 0:
            raise ValueError("HTTP fixture timeout must be positive")
        if self.poll_interval <= 0:
            raise ValueError("HTTP fixture poll_interval must be positive")

        self.set_json_response("/healthz", {"status": "ok"})

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("HTTP fixture runtime has not been started yet")
        return int(self._server.server_port)

    @property
    def base_url(self) -> str:
        return f"http://{self.public_host}:{self.port}"

    def docker_url(self, path: str) -> str:
        normalized = path if path.startswith("/") else f"/{path}"
        return f"http://{self.docker_host}:{self.port}{normalized}"

    @property
    def requests_log_path(self) -> Path:
        return self.runtime_dir / "requests.jsonl"

    def set_json_response(
        self,
        path: str,
        payload: object,
        *,
        status: int = HTTPStatus.OK,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._set_response(
            path,
            HttpFixtureResponse(
                status=status,
                body=payload,
                headers={"content-type": "application/json", **dict(headers or {})},
            ),
        )

    def set_text_response(
        self,
        path: str,
        text: str,
        *,
        status: int = HTTPStatus.OK,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._set_response(
            path,
            HttpFixtureResponse(
                status=status,
                body=text,
                headers={"content-type": "text/plain; charset=utf-8", **dict(headers or {})},
            ),
        )

    def requests(self, *, path: str | None = None) -> tuple[HttpFixtureRequest, ...]:
        with self._lock:
            records = tuple(self._requests)
        if path is None:
            return records
        return tuple(record for record in records if record.path == path)

    def clear_requests(self) -> None:
        with self._lock:
            self._requests.clear()
        if self.requests_log_path.exists():
            self.requests_log_path.unlink()

    def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("HTTP fixture runtime is already running")

        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.clear_requests()
        server = ThreadingHTTPServer((self.listen_host, 0), _HttpFixtureHandler)
        server.runtime = self  # type: ignore[attr-defined]
        self._server = server

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self._thread = thread
        self.wait_until_ready()

    def stop(self) -> None:
        if self._server is None:
            return

        try:
            self._server.shutdown()
            self._server.server_close()
        finally:
            if self._thread is not None:
                self._thread.join(timeout=1.0)
            self._thread = None
            self._server = None

    def wait_until_ready(self) -> None:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                with request.urlopen(f"{self.base_url}/healthz", timeout=self.poll_interval):  # noqa: S310
                    return
            except (OSError, error.URLError):
                time.sleep(self.poll_interval)

        raise RuntimeError("Timed out waiting for local HTTP fixture to become ready")

    def _set_response(self, path: str, response: HttpFixtureResponse) -> None:
        normalized = self._normalize_path(path)
        with self._lock:
            self._routes[normalized] = response

    def _handle_request(self, handler: BaseHTTPRequestHandler) -> None:
        path = self._normalize_path(handler.path)
        record = HttpFixtureRequest(
            method=handler.command,
            path=path,
            headers={key.lower(): value for key, value in handler.headers.items()},
        )
        self._record_request(record)

        with self._lock:
            response = self._routes.get(path)

        if response is None:
            body = b"not found"
            handler.send_response(HTTPStatus.NOT_FOUND)
            handler.send_header("content-type", "text/plain; charset=utf-8")
            handler.send_header("content-length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
            return

        body = self._render_body(response.body)
        handler.send_response(response.status)
        for key, value in response.headers.items():
            handler.send_header(key, value)
        handler.send_header("content-length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _record_request(self, record: HttpFixtureRequest) -> None:
        with self._lock:
            self._requests.append(record)
        self.requests_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.requests_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")

    @staticmethod
    def _normalize_path(path: str) -> str:
        normalized = path.split("?", 1)[0].strip()
        if not normalized:
            return "/"
        return normalized if normalized.startswith("/") else f"/{normalized}"

    @staticmethod
    def _render_body(body: object) -> bytes:
        if isinstance(body, bytes):
            return body
        if isinstance(body, str):
            return body.encode("utf-8")
        return json.dumps(body, sort_keys=True).encode("utf-8")

    def __enter__(self) -> LocalHttpFixtureRuntime:
        self.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.stop()
