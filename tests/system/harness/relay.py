"""Real relay harness helpers for higher-band system tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import aiohttp
from nostr_sdk import EventBuilder, Keys, Kind

from tests.integration.harness.postgres import (
    ensure_docker_available,
    ensure_testcontainers_environment,
)
from tests.system.harness.artifacts import sanitize_artifact_component


if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


NOSTR_RS_RELAY_IMAGE = (
    "scsibug/nostr-rs-relay@sha256:03f54bfbffff80a50db62c9287913bd25a2dec08033b56d2122bc2550363d5c5"
)
NOSTR_RS_RELAY_PLATFORM = "linux/amd64"
NOSTR_RS_RELAY_CONTAINER_PORT = 8080
NOSTR_RS_RELAY_DATA_PATH = "/usr/src/app/db"
DEFAULT_RELAY_READY_TIMEOUT = 20.0
DEFAULT_RELAY_FRAME_TIMEOUT = 5.0
DEFAULT_RELAY_POLL_INTERVAL = 0.25
READINESS_SENTINEL_EVENT_ID = "0" * 64


def build_relay_container_name(role: str, runtime_dir: Path) -> str:
    """Build a deterministic container name for one relay runtime root."""
    normalized_role = sanitize_artifact_component(role)
    digest = hashlib.sha256(str(runtime_dir.resolve()).encode()).hexdigest()[:12]
    return f"bigbrotr-relay-{normalized_role}-{digest}"


@dataclass(frozen=True, slots=True)
class SignedRelayEvent:
    """Signed event payload ready to send through a real relay."""

    event_id: str
    pubkey: str
    payload: dict[str, object]


def build_text_note_event(content: str, *, keys: Keys | None = None) -> SignedRelayEvent:
    """Build and sign a minimal text-note event for relay contract tests."""
    event = EventBuilder(Kind(1), content).sign_with_keys(keys or Keys.generate())
    payload = json.loads(event.as_json())
    return SignedRelayEvent(
        event_id=str(payload["id"]),
        pubkey=str(payload["pubkey"]),
        payload=payload,
    )


@dataclass(frozen=True, slots=True)
class RelayOkFrame:
    """Normalized relay OK frame."""

    event_id: str
    accepted: bool
    message: str


@dataclass(frozen=True, slots=True)
class RelayEventFrame:
    """Normalized relay EVENT frame."""

    subscription_id: str
    event: dict[str, object]


@dataclass(frozen=True, slots=True)
class RelayEoseFrame:
    """Normalized relay EOSE frame."""

    subscription_id: str


RelayFrame = RelayOkFrame | RelayEventFrame | RelayEoseFrame


def _parse_ok_frame(payload: list[object]) -> RelayOkFrame:
    if len(payload) != 4:
        raise ValueError("OK frame must contain four items")
    event_id, accepted, message = payload[1], payload[2], payload[3]
    if not isinstance(event_id, str):
        raise ValueError("OK frame event id must be a string")
    if not isinstance(accepted, bool):
        raise ValueError("OK frame accepted flag must be a bool")
    if not isinstance(message, str):
        raise ValueError("OK frame message must be a string")
    return RelayOkFrame(event_id=event_id, accepted=accepted, message=message)


def _parse_event_frame(payload: list[object]) -> RelayEventFrame:
    if len(payload) != 3:
        raise ValueError("EVENT frame must contain three items")
    subscription_id, event = payload[1], payload[2]
    if not isinstance(subscription_id, str):
        raise ValueError("EVENT frame subscription id must be a string")
    if not isinstance(event, dict):
        raise ValueError("EVENT frame payload must be an object")
    return RelayEventFrame(subscription_id=subscription_id, event=dict(event))


def _parse_eose_frame(payload: list[object]) -> RelayEoseFrame:
    if len(payload) != 2:
        raise ValueError("EOSE frame must contain two items")
    subscription_id = payload[1]
    if not isinstance(subscription_id, str):
        raise ValueError("EOSE frame subscription id must be a string")
    return RelayEoseFrame(subscription_id=subscription_id)


def parse_relay_frame(payload: object) -> RelayFrame:
    """Parse one JSON relay frame into a stable typed shape."""
    if not isinstance(payload, list) or len(payload) < 2:
        raise ValueError("Relay frame must be a JSON array with at least two items")

    frame_type = payload[0]
    if not isinstance(frame_type, str):
        raise ValueError("Relay frame type must be a string")

    if frame_type == "OK":
        return _parse_ok_frame(payload)

    if frame_type == "EVENT":
        return _parse_event_frame(payload)

    if frame_type == "EOSE":
        return _parse_eose_frame(payload)

    raise ValueError(f"Unsupported relay frame type: {frame_type}")


class RelaySession:
    """Async wrapper around one real relay WebSocket session."""

    def __init__(
        self,
        *,
        ws_url: str,
        session: aiohttp.ClientSession,
        websocket: aiohttp.ClientWebSocketResponse,
    ) -> None:
        self._ws_url = ws_url
        self._session = session
        self._websocket = websocket

    @classmethod
    async def connect(cls, ws_url: str) -> RelaySession:
        """Open a real WebSocket session to the relay under test."""
        session = aiohttp.ClientSession()
        try:
            websocket = await session.ws_connect(ws_url)
        except Exception:
            await session.close()
            raise
        return cls(ws_url=ws_url, session=session, websocket=websocket)

    @property
    def ws_url(self) -> str:
        return self._ws_url

    async def close(self) -> None:
        """Close the WebSocket session and the owning HTTP session."""
        await self._websocket.close()
        await self._session.close()

    async def __aenter__(self) -> RelaySession:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()

    async def request(self, subscription_id: str, filters: Mapping[str, object]) -> None:
        """Send a REQ subscription frame."""
        await self._websocket.send_json(["REQ", subscription_id, dict(filters)])

    async def publish(self, event_payload: Mapping[str, object]) -> RelayOkFrame:
        """Publish one signed event and return the normalized OK frame."""
        await self._websocket.send_json(["EVENT", dict(event_payload)])
        frame = await self.receive_frame()
        if not isinstance(frame, RelayOkFrame):
            raise RuntimeError(f"Relay publish did not return OK, got {type(frame).__name__}")
        return frame

    async def receive_frame(self, *, timeout: float = DEFAULT_RELAY_FRAME_TIMEOUT) -> RelayFrame:
        """Receive and parse one relay frame."""
        payload = await self._websocket.receive_json(timeout=timeout)
        return parse_relay_frame(payload)

    async def collect_until_eose(
        self,
        *,
        subscription_id: str,
        timeout: float = DEFAULT_RELAY_FRAME_TIMEOUT,
        max_frames: int = 20,
    ) -> tuple[RelayFrame, ...]:
        """Collect frames until the requested subscription reaches EOSE."""
        if max_frames <= 0:
            raise ValueError("Relay collect_until_eose max_frames must be positive")

        frames: list[RelayFrame] = []
        for _ in range(max_frames):
            frame = await self.receive_frame(timeout=timeout)
            frames.append(frame)
            if isinstance(frame, RelayEoseFrame) and frame.subscription_id == subscription_id:
                return tuple(frames)

        raise RuntimeError(
            f"Relay subscription {subscription_id!r} did not reach EOSE within {max_frames} frames"
        )


async def publish_event(ws_url: str, event_payload: Mapping[str, object]) -> RelayOkFrame:
    """Publish one event using a short-lived relay connection."""
    async with await RelaySession.connect(ws_url) as relay:
        return await relay.publish(event_payload)


async def query_events(
    ws_url: str,
    *,
    filters: Mapping[str, object],
    subscription_id: str,
    timeout: float = DEFAULT_RELAY_FRAME_TIMEOUT,
) -> tuple[RelayEventFrame, ...]:
    """Query a relay and return only the EVENT frames for one REQ/EOSE cycle."""
    async with await RelaySession.connect(ws_url) as relay:
        await relay.request(subscription_id, filters)
        frames = await relay.collect_until_eose(subscription_id=subscription_id, timeout=timeout)
    return tuple(frame for frame in frames if isinstance(frame, RelayEventFrame))


async def wait_until_relay_ready(
    ws_url: str,
    *,
    timeout: float = DEFAULT_RELAY_READY_TIMEOUT,
    poll_interval: float = DEFAULT_RELAY_POLL_INTERVAL,
) -> None:
    """Wait until the relay accepts a REQ cycle and responds with EOSE."""
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            await query_events(
                ws_url,
                filters={"ids": [READINESS_SENTINEL_EVENT_ID]},
                subscription_id="relay-ready",
            )
            return
        except (
            aiohttp.ClientError,
            TimeoutError,
            OSError,
            ValueError,
            RuntimeError,
        ) as exc:
            last_error = exc
            await asyncio.sleep(poll_interval)
    if last_error is None:
        raise RuntimeError(f"Relay {ws_url} did not become ready within {timeout} seconds")
    raise RuntimeError(f"Relay {ws_url} did not become ready: {last_error}") from last_error


def _docker_command(*args: str) -> tuple[str, ...]:
    return ("docker", *args)


def _run_docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        _docker_command(*args),
        check=True,
        text=True,
        capture_output=True,
    )


def _ensure_relay_image(image: str, platform: str) -> None:
    inspect_result = subprocess.run(  # noqa: S603
        _docker_command("image", "inspect", image),
        check=False,
        text=True,
        capture_output=True,
    )
    if inspect_result.returncode == 0:
        return

    _run_docker("pull", "--platform", platform, image)


@dataclass(slots=True)
class LocalRelayRuntime:
    """Lifecycle wrapper around a real local relay container."""

    role: str
    runtime_dir: Path
    image: str = NOSTR_RS_RELAY_IMAGE
    platform: str = NOSTR_RS_RELAY_PLATFORM
    host: str = "127.0.0.1"
    ready_timeout: float = DEFAULT_RELAY_READY_TIMEOUT
    poll_interval: float = DEFAULT_RELAY_POLL_INTERVAL
    container_id: str | None = field(init=False, default=None)
    host_port: int | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if not self.role.strip():
            raise ValueError("Relay runtime role must not be blank")
        if self.ready_timeout <= 0:
            raise ValueError("Relay ready_timeout must be positive")
        if self.poll_interval <= 0:
            raise ValueError("Relay poll_interval must be positive")

    @property
    def container_name(self) -> str:
        return build_relay_container_name(self.role, self.runtime_dir)

    @property
    def data_dir(self) -> Path:
        return self.runtime_dir / "db"

    @property
    def ws_url(self) -> str:
        if self.host_port is None:
            raise RuntimeError("Relay runtime has not been started yet")
        return f"ws://{self.host}:{self.host_port}"

    def start(self) -> None:
        """Start the relay container and resolve its mapped host port."""
        if self.container_id is not None:
            raise RuntimeError("Relay runtime is already running")

        ensure_docker_available()
        ensure_testcontainers_environment()
        _ensure_relay_image(self.image, self.platform)

        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        try:
            result = _run_docker(
                "run",
                "-d",
                "--platform",
                self.platform,
                "--name",
                self.container_name,
                "-p",
                f"{self.host}::{NOSTR_RS_RELAY_CONTAINER_PORT}",
                "-v",
                f"{self.data_dir}:{NOSTR_RS_RELAY_DATA_PATH}",
                self.image,
            )
            self.container_id = result.stdout.strip()
            if not self.container_id:
                raise RuntimeError("Relay container did not return a container id")

            inspect_payload = self.inspect()
            port_bindings = (
                inspect_payload.get("NetworkSettings", {})
                .get("Ports", {})
                .get(f"{NOSTR_RS_RELAY_CONTAINER_PORT}/tcp")
            )
            if not isinstance(port_bindings, list) or not port_bindings:
                raise RuntimeError("Relay container did not expose the expected TCP port")

            binding = port_bindings[0]
            if not isinstance(binding, dict):
                raise RuntimeError("Relay container port binding payload is invalid")

            host_port = binding.get("HostPort")
            if not isinstance(host_port, str) or not host_port:
                raise RuntimeError("Relay container did not report a mapped host port")
            self.host_port = int(host_port)
        except Exception:
            self.stop()
            raise

    async def wait_until_ready(self) -> None:
        """Wait until the relay accepts a simple REQ/EOSE cycle."""
        await wait_until_relay_ready(
            self.ws_url,
            timeout=self.ready_timeout,
            poll_interval=self.poll_interval,
        )

    def inspect(self) -> dict[str, Any]:
        """Return the raw `docker inspect` payload for the running container."""
        container_ref = self.container_id or self.container_name
        result = _run_docker("inspect", container_ref)
        payload = json.loads(result.stdout)
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            raise RuntimeError("Relay inspect payload was not a single JSON object")
        return payload[0]

    def logs(self) -> str:
        """Return the current relay container logs."""
        container_ref = self.container_id or self.container_name
        return _run_docker("logs", container_ref).stdout

    def data_files(self) -> tuple[Path, ...]:
        """Return the relay data files created in the mounted runtime directory."""
        if not self.data_dir.exists():
            return ()
        return tuple(sorted(path for path in self.data_dir.iterdir() if path.is_file()))

    def stop(self) -> None:
        """Force-remove the relay container if it is still present."""
        if self.container_id is None:
            return

        try:
            subprocess.run(  # noqa: S603
                _docker_command("rm", "-f", self.container_id),
                check=False,
                text=True,
                capture_output=True,
            )
        finally:
            self.container_id = None
            self.host_port = None

    def __enter__(self) -> LocalRelayRuntime:
        self.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.stop()
