"""Local TLS WebSocket fixture helpers for higher-band system tests."""

from __future__ import annotations

import contextlib
import json
import ssl
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from ipaddress import ip_address
from typing import TYPE_CHECKING, Literal
from urllib import error, parse
from urllib import request as urlrequest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response
from websockets.sync.client import connect
from websockets.sync.server import serve


if TYPE_CHECKING:
    from pathlib import Path

    from websockets.sync.client import ClientConnection
    from websockets.sync.server import Server, ServerConnection


DEFAULT_TLS_WEBSOCKET_TIMEOUT = 5.0
DEFAULT_TLS_WEBSOCKET_POLL_INTERVAL = 0.1


@dataclass(frozen=True, slots=True)
class WebSocketFixtureSession:
    """One observed TLS WebSocket session."""

    path: str
    mode: str
    opened_at: float
    closed_at: float
    received_messages: tuple[str, ...]


@dataclass(slots=True)
class _MutableWebSocketFixtureSession:
    path: str
    mode: str
    opened_at: float
    received_messages: list[str] = field(default_factory=list)
    closed_at: float | None = None

    def freeze(self) -> WebSocketFixtureSession:
        return WebSocketFixtureSession(
            path=self.path,
            mode=self.mode,
            opened_at=self.opened_at,
            closed_at=self.closed_at or time.time(),
            received_messages=tuple(self.received_messages),
        )


@dataclass(slots=True)
class LocalTlsWebSocketRuntime:
    """Host-side `wss://` runtime for composed-service boundary tests."""

    runtime_dir: Path
    mode: Literal["blackhole", "invalid-text", "proxy"] = "blackhole"
    backend_url: str | None = None
    http_backend_url: str | None = None
    listen_host: str = "0.0.0.0"
    public_host: str = "127.0.0.1"
    docker_host: str = "host.docker.internal"
    timeout: float = DEFAULT_TLS_WEBSOCKET_TIMEOUT
    poll_interval: float = DEFAULT_TLS_WEBSOCKET_POLL_INTERVAL
    _server: Server | None = field(init=False, default=None, repr=False)
    _thread: threading.Thread | None = field(init=False, default=None, repr=False)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock, repr=False)
    _sessions: list[WebSocketFixtureSession] = field(init=False, default_factory=list, repr=False)
    _started: threading.Event = field(init=False, default_factory=threading.Event, repr=False)
    _startup_error: BaseException | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        if self.mode not in {"blackhole", "invalid-text", "proxy"}:
            raise ValueError(
                "TLS WebSocket runtime mode must be 'blackhole', 'invalid-text', or 'proxy'"
            )
        if self.mode == "proxy" and not self.backend_url:
            raise ValueError("TLS WebSocket proxy mode requires a backend_url")
        if self.mode != "proxy" and self.http_backend_url is not None:
            raise ValueError("TLS WebSocket http_backend_url requires proxy mode")
        if self.timeout <= 0:
            raise ValueError("TLS WebSocket runtime timeout must be positive")
        if self.poll_interval <= 0:
            raise ValueError("TLS WebSocket runtime poll_interval must be positive")

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("TLS WebSocket runtime has not been started yet")
        return int(self._server.socket.getsockname()[1])

    def public_url(self, path: str = "/") -> str:
        return f"wss://{self.public_host}:{self.port}{self._normalize_path(path)}"

    def docker_url(self, path: str = "/") -> str:
        return f"wss://{self.docker_host}:{self.port}{self._normalize_path(path)}"

    def client_ssl_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    @property
    def certificate_path(self) -> Path:
        return self.runtime_dir / "cert.pem"

    @property
    def private_key_path(self) -> Path:
        return self.runtime_dir / "key.pem"

    @property
    def sessions_log_path(self) -> Path:
        return self.runtime_dir / "sessions.jsonl"

    def sessions(self, *, path: str | None = None) -> tuple[WebSocketFixtureSession, ...]:
        with self._lock:
            records = tuple(self._sessions)
        if path is None:
            return records
        normalized = self._normalize_path(path)
        return tuple(record for record in records if record.path == normalized)

    def clear_sessions(self) -> None:
        with self._lock:
            self._sessions.clear()
        if self.sessions_log_path.exists():
            self.sessions_log_path.unlink()

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("TLS WebSocket runtime is already running")

        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._write_certificate_chain()
        self.clear_sessions()
        self._startup_error = None
        self._started.clear()

        thread = threading.Thread(target=self._serve_forever, daemon=True)
        thread.start()
        self._thread = thread

        if not self._started.wait(timeout=self.timeout):
            self.stop()
            raise RuntimeError("Timed out waiting for TLS WebSocket runtime to start")
        if self._startup_error is not None:
            self.stop()
            raise RuntimeError("TLS WebSocket runtime failed to start") from self._startup_error

        self.wait_until_ready()
        self.clear_sessions()

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        if server is not None:
            server.shutdown()
        if thread is not None:
            thread.join(timeout=1.0)
        self._server = None
        self._thread = None
        self._startup_error = None
        self._started.clear()

    def wait_until_ready(self) -> None:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                with connect(
                    self.public_url("/ready"),
                    ssl=self.client_ssl_context(),
                    open_timeout=self.poll_interval,
                    close_timeout=self.poll_interval,
                ):
                    return
            except (ConnectionClosed, OSError, TimeoutError):
                time.sleep(self.poll_interval)

        raise RuntimeError("Timed out waiting for TLS WebSocket runtime to become ready")

    def _serve_forever(self) -> None:
        try:
            with serve(
                self._handle_connection,
                self.listen_host,
                0,
                ssl=self._server_ssl_context(),
                process_request=self._process_request,
                open_timeout=self.timeout,
                close_timeout=self.timeout,
                ping_interval=None,
                ping_timeout=None,
            ) as server:
                self._server = server
                self._started.set()
                server.serve_forever()
        except BaseException as exc:  # pragma: no cover - startup errors are surfaced to callers
            self._startup_error = exc
            self._started.set()
        finally:
            self._server = None

    def _handle_connection(self, websocket: ServerConnection) -> None:
        path = self._normalize_path(websocket.request.path)
        if path == "/ready":
            self._ready_connection(websocket)
            return
        session = _MutableWebSocketFixtureSession(
            path=path,
            mode=self.mode,
            opened_at=time.time(),
        )
        try:
            if self.mode == "proxy":
                assert self.backend_url is not None
                with connect(
                    self.backend_url,
                    open_timeout=self.timeout,
                    close_timeout=self.timeout,
                ) as backend:
                    self._proxy_connection(websocket, backend, session)
            elif self.mode == "invalid-text":
                self._invalid_text_connection(websocket, session)
            else:
                self._blackhole_connection(websocket, session)
        finally:
            session.closed_at = time.time()
            self._record_session(session.freeze())

    def _process_request(
        self,
        _connection: ServerConnection,
        request: Request,
    ) -> Response | None:
        if self.mode != "proxy" or self.http_backend_url is None:
            return None

        upgrade = request.headers.get("Upgrade", "")
        if isinstance(upgrade, str) and upgrade.lower() == "websocket":
            return None

        backend_url = self._http_backend_request_url(request.path)
        backend_request = urlrequest.Request(backend_url, method="GET")  # noqa: S310
        accept = request.headers.get("Accept")
        if isinstance(accept, str) and accept:
            backend_request.add_header("Accept", accept)

        try:
            with urlrequest.urlopen(backend_request, timeout=self.timeout) as response:  # noqa: S310
                body = response.read()
                content_type = response.headers.get("Content-Type", "application/octet-stream")
                headers = Headers(
                    {
                        "content-type": content_type,
                        "content-length": str(len(body)),
                    }
                )
                return Response(
                    status_code=response.status,
                    reason_phrase=HTTPStatus(response.status).phrase,
                    headers=headers,
                    body=body,
                )
        except error.HTTPError as exc:
            body = exc.read()
            headers = Headers(
                {
                    "content-type": exc.headers.get("Content-Type", "text/plain; charset=utf-8"),
                    "content-length": str(len(body)),
                }
            )
            return Response(
                status_code=exc.code,
                reason_phrase=HTTPStatus(exc.code).phrase,
                headers=headers,
                body=body,
            )
        except (error.URLError, OSError, TimeoutError):
            body = b"upstream timeout"
            return Response(
                status_code=HTTPStatus.GATEWAY_TIMEOUT,
                reason_phrase=HTTPStatus.GATEWAY_TIMEOUT.phrase,
                headers=Headers(
                    {
                        "content-type": "text/plain; charset=utf-8",
                        "content-length": str(len(body)),
                    }
                ),
                body=body,
            )

    def _blackhole_connection(
        self,
        websocket: ServerConnection,
        session: _MutableWebSocketFixtureSession,
    ) -> None:
        while True:
            try:
                message = websocket.recv()
            except ConnectionClosed:
                return
            session.received_messages.append(self._render_message(message))

    @staticmethod
    def _ready_connection(websocket: ServerConnection) -> None:
        with contextlib.suppress(Exception):
            websocket.close()

    def _proxy_connection(
        self,
        websocket: ServerConnection,
        backend: ClientConnection,
        session: _MutableWebSocketFixtureSession,
    ) -> None:
        stop_event = threading.Event()
        threads = (
            threading.Thread(
                target=self._forward_messages,
                args=(websocket, backend, session, stop_event),
                kwargs={"capture_messages": True},
                daemon=True,
            ),
            threading.Thread(
                target=self._forward_messages,
                args=(backend, websocket, session, stop_event),
                daemon=True,
            ),
        )
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=self.timeout * 2)
        if any(thread.is_alive() for thread in threads):
            stop_event.set()
            with contextlib.suppress(Exception):
                backend.close()
            with contextlib.suppress(Exception):
                websocket.close()
            for thread in threads:
                thread.join(timeout=self.timeout)
        if any(thread.is_alive() for thread in threads):
            raise RuntimeError("Timed out waiting for TLS WebSocket proxy threads to stop")

    def _invalid_text_connection(
        self,
        websocket: ServerConnection,
        session: _MutableWebSocketFixtureSession,
    ) -> None:
        try:
            message = websocket.recv()
        except ConnectionClosed:
            return
        session.received_messages.append(self._render_message(message))
        websocket.send("not nostr")
        with contextlib.suppress(Exception):
            websocket.close()

    def _forward_messages(
        self,
        source: ServerConnection | ClientConnection,
        target: ServerConnection | ClientConnection,
        session: _MutableWebSocketFixtureSession,
        stop_event: threading.Event,
        *,
        capture_messages: bool = False,
    ) -> None:
        try:
            while not stop_event.is_set():
                try:
                    message = source.recv(timeout=self.poll_interval)
                except TimeoutError:
                    continue
                if capture_messages:
                    session.received_messages.append(self._render_message(message))
                target.send(message)
        except (ConnectionClosed, OSError):
            return
        finally:
            stop_event.set()
            with contextlib.suppress(Exception):
                target.close()
            with contextlib.suppress(Exception):
                source.close()

    def _record_session(self, session: WebSocketFixtureSession) -> None:
        with self._lock:
            self._sessions.append(session)
        self.sessions_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.sessions_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(session), sort_keys=True) + "\n")

    def _http_backend_request_url(self, path: str) -> str:
        assert self.http_backend_url is not None
        backend = parse.urlsplit(self.http_backend_url)
        request_path = self._normalize_path(path)
        return parse.urlunsplit(
            (
                backend.scheme,
                backend.netloc,
                request_path,
                "",
                "",
            )
        )

    def _write_certificate_chain(self) -> None:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(UTC)
        subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, self.docker_host)])

        san_entries: list[x509.GeneralName] = [
            x509.DNSName(self.docker_host),
            x509.DNSName("localhost"),
        ]
        for host in {self.public_host, "127.0.0.1"}:
            try:
                san_entries.append(x509.IPAddress(ip_address(host)))
            except ValueError:
                san_entries.append(x509.DNSName(host))

        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
            .sign(private_key, hashes.SHA256())
        )

        self.private_key_path.write_bytes(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        self.certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))

    def _server_ssl_context(self) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.certificate_path, self.private_key_path)
        return context

    @staticmethod
    def _normalize_path(path: str) -> str:
        normalized = path.split("?", 1)[0].strip()
        if not normalized:
            return "/"
        return normalized if normalized.startswith("/") else f"/{normalized}"

    @staticmethod
    def _render_message(message: str | bytes) -> str:
        if isinstance(message, bytes):
            return f"<bytes:{len(message)}>"
        return message

    def __enter__(self) -> LocalTlsWebSocketRuntime:
        self.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.stop()
