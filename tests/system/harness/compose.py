"""Docker Compose lifecycle helpers for higher-band system tests."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Mapping


DEFAULT_READY_TIMEOUT = 90.0
DEFAULT_POLL_INTERVAL = 0.5
REQUIRED_ENV_KEYS = (
    "DB_ADMIN_PASSWORD",
    "DB_WRITER_PASSWORD",
    "DB_REFRESHER_PASSWORD",
    "DB_READER_PASSWORD",
    "DB_RANKER_PASSWORD",
    "NOSTR_PRIVATE_KEY_MONITOR",
    "NOSTR_PRIVATE_KEY_SYNCHRONIZER",
    "NOSTR_PRIVATE_KEY_DVM",
    "NOSTR_PRIVATE_KEY_ASSERTOR",
    "GRAFANA_PASSWORD",
)
ROOT_DIR = Path(__file__).resolve().parents[3]
DEPLOYMENTS_DIR = ROOT_DIR / "deployments"
VALID_PROFILES = ("bigbrotr", "lilbrotr")


def deployment_dir(profile: str) -> Path:
    """Return the built-in deployment directory for the requested profile."""
    if profile not in VALID_PROFILES:
        raise ValueError(f"Unsupported deployment profile: {profile}")
    return DEPLOYMENTS_DIR / profile


def _compose_command_env() -> dict[str, str]:
    """Build an env for `docker compose` that preserves CLI plugin discovery."""
    env = dict(os.environ)
    env.pop("DOCKER_CONFIG", None)
    return env


def _format_compose_failure(exc: subprocess.CalledProcessError) -> RuntimeError:
    """Return one readable error that preserves compose stdout/stderr."""
    command = exc.cmd if isinstance(exc.cmd, str) else " ".join(str(part) for part in exc.cmd)
    message_lines = [
        f"Compose command failed with exit code {exc.returncode}: {command}",
    ]
    if isinstance(exc.stdout, str) and exc.stdout.strip():
        message_lines.extend(("stdout:", exc.stdout.rstrip()))
    if isinstance(exc.stderr, str) and exc.stderr.strip():
        message_lines.extend(("stderr:", exc.stderr.rstrip()))
    return RuntimeError("\n".join(message_lines))


def env_template_path(profile: str) -> Path:
    """Return the `.env.example` template path for a built-in deployment."""
    return deployment_dir(profile) / ".env.example"


def _derive_hex(profile: str, project_name: str, label: str, length: int) -> str:
    digest = ""
    seed = f"{profile}:{project_name}:{label}".encode()
    while len(digest) < length:
        seed = hashlib.sha256(seed).digest()
        digest += seed.hex()
    return digest[:length]


def build_test_env_values(
    profile: str,
    project_name: str,
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build deterministic non-production secrets for a system-test stack."""
    deployment_dir(profile)

    values = {
        "DB_ADMIN_PASSWORD": _derive_hex(profile, project_name, "db-admin", 32),
        "DB_WRITER_PASSWORD": _derive_hex(profile, project_name, "db-writer", 32),
        "DB_REFRESHER_PASSWORD": _derive_hex(profile, project_name, "db-refresher", 32),
        "DB_READER_PASSWORD": _derive_hex(profile, project_name, "db-reader", 32),
        "DB_RANKER_PASSWORD": _derive_hex(profile, project_name, "db-ranker", 32),
        "NOSTR_PRIVATE_KEY_MONITOR": _derive_hex(profile, project_name, "monitor", 64),
        "NOSTR_PRIVATE_KEY_SYNCHRONIZER": _derive_hex(
            profile,
            project_name,
            "synchronizer",
            64,
        ),
        "NOSTR_PRIVATE_KEY_DVM": _derive_hex(profile, project_name, "dvm", 64),
        "NOSTR_PRIVATE_KEY_ASSERTOR": _derive_hex(profile, project_name, "assertor", 64),
        "GRAFANA_PASSWORD": _derive_hex(profile, project_name, "grafana", 24),
    }
    if overrides:
        values.update(overrides)

    for key in REQUIRED_ENV_KEYS:
        if not values.get(key):
            raise ValueError(f"Missing required compose env value: {key}")
    return values


def write_test_env_file(
    profile: str,
    project_name: str,
    target: Path,
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Render a deterministic `.env` file for the requested deployment profile."""
    values = build_test_env_values(profile, project_name, overrides=overrides)
    template_lines = env_template_path(profile).read_text().splitlines()

    rendered_lines: list[str] = []
    remaining = dict(values)
    for line in template_lines:
        if "=" not in line or line.lstrip().startswith("#"):
            rendered_lines.append(line)
            continue

        key, _, _ = line.partition("=")
        if key in remaining:
            rendered_lines.append(f"{key}={remaining.pop(key)}")
        else:
            rendered_lines.append(line)

    if remaining:
        rendered_lines.append("")
        for key in sorted(remaining):
            rendered_lines.append(f"{key}={remaining[key]}")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(rendered_lines) + "\n")
    return values


@dataclass(frozen=True, slots=True)
class ComposeServiceStatus:
    """Normalized `docker compose ps` status for one service."""

    service: str
    state: str
    health: str | None = None
    exit_code: int | None = None

    @property
    def is_ready(self) -> bool:
        if self.state != "running":
            return False
        return self.health in (None, "healthy")


def parse_compose_ps(output: str) -> tuple[ComposeServiceStatus, ...]:
    """Parse `docker compose ps --format json` output robustly."""
    payload = output.strip()
    if not payload:
        return ()

    rows: list[dict[str, object]]
    if payload.startswith("["):
        parsed = json.loads(payload)
        rows = [row for row in parsed if isinstance(row, dict)]
    else:
        rows = []
        for line in payload.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                rows.append(parsed)

    statuses: list[ComposeServiceStatus] = []
    for row in rows:
        service = str(row.get("Service", "")).strip()
        if not service:
            continue

        raw_state = str(row.get("State", "")).strip().lower()
        raw_health = row.get("Health")
        health = None
        if isinstance(raw_health, str):
            normalized = raw_health.strip().lower()
            health = normalized or None

        raw_exit_code = row.get("ExitCode")
        exit_code = None if raw_exit_code in (None, "") else int(raw_exit_code)

        statuses.append(
            ComposeServiceStatus(
                service=service,
                state=raw_state,
                health=health,
                exit_code=exit_code,
            )
        )

    return tuple(statuses)


@dataclass(frozen=True, slots=True)
class ComposeStack:
    """Deterministic wrapper around a Docker Compose deployment profile."""

    profile: str
    project_name: str
    project_dir: Path
    env_file: Path
    compose_files: tuple[Path, ...]
    ready_timeout: float = DEFAULT_READY_TIMEOUT
    poll_interval: float = DEFAULT_POLL_INTERVAL

    def __post_init__(self) -> None:
        deployment_dir(self.profile)
        if not self.project_name.strip():
            raise ValueError("Compose project_name must not be blank")
        if not self.compose_files:
            raise ValueError("Compose stack must include at least one compose file")
        if self.ready_timeout <= 0:
            raise ValueError("Compose ready_timeout must be positive")
        if self.poll_interval <= 0:
            raise ValueError("Compose poll_interval must be positive")

    @classmethod
    def for_profile(
        cls,
        profile: str,
        runtime_dir: Path,
        project_name: str,
        *,
        compose_files: tuple[Path, ...] = (),
        env_overrides: Mapping[str, str] | None = None,
        ready_timeout: float = DEFAULT_READY_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ) -> ComposeStack:
        """Create a stack object and materialize its deterministic env file."""
        base_dir = deployment_dir(profile)
        stack_compose_files = compose_files or (base_dir / "docker-compose.yaml",)
        env_file = runtime_dir / f"{profile}.env"
        write_test_env_file(
            profile=profile,
            project_name=project_name,
            target=env_file,
            overrides=env_overrides,
        )
        return cls(
            profile=profile,
            project_name=project_name,
            project_dir=base_dir,
            env_file=env_file,
            compose_files=stack_compose_files,
            ready_timeout=ready_timeout,
            poll_interval=poll_interval,
        )

    def command(self, *args: str) -> tuple[str, ...]:
        """Build a complete `docker compose` command for this stack."""
        command = [
            "docker",
            "compose",
            "--project-name",
            self.project_name,
            "--project-directory",
            str(self.project_dir),
            "--env-file",
            str(self.env_file),
        ]
        for compose_file in self.compose_files:
            command.extend(("-f", str(compose_file)))
        command.extend(args)
        return tuple(command)

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run a compose command with captured text output."""
        try:
            return subprocess.run(  # noqa: S603
                self.command(*args),
                cwd=self.project_dir,
                check=check,
                text=True,
                capture_output=True,
                env=_compose_command_env(),
            )
        except subprocess.CalledProcessError as exc:
            raise _format_compose_failure(exc) from exc

    def up(
        self,
        *services: str,
        detach: bool = True,
        build: bool = False,
        force_recreate: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Bring the compose stack up."""
        args = ["up"]
        if detach:
            args.append("-d")
        if build:
            args.append("--build")
        if force_recreate:
            args.append("--force-recreate")
        args.extend(services)
        return self.run(*args)

    def down(
        self,
        *,
        remove_orphans: bool = True,
        volumes: bool = True,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Tear the compose stack down."""
        args = ["down"]
        if remove_orphans:
            args.append("--remove-orphans")
        if volumes:
            args.append("--volumes")
        if timeout is not None:
            if timeout <= 0:
                raise ValueError("Compose down timeout must be positive")
            args.extend(("--timeout", str(timeout)))
        return self.run(*args)

    def ps(self, *, all_services: bool = False) -> tuple[ComposeServiceStatus, ...]:
        """Inspect compose service state via the JSON `ps` output."""
        args = ["ps"]
        if all_services:
            args.append("--all")
        args.extend(("--format", "json"))
        result = self.run(*args)
        return parse_compose_ps(result.stdout)

    def wait_until_ready(
        self,
        services: tuple[str, ...],
        *,
        timeout: float | None = None,
    ) -> tuple[ComposeServiceStatus, ...]:
        """Poll compose state until the requested services are ready."""
        if not services:
            raise ValueError("Compose readiness polling requires at least one service name")

        deadline = time.monotonic() + (timeout or self.ready_timeout)
        wanted = set(services)
        snapshot: dict[str, ComposeServiceStatus] = {}

        while time.monotonic() < deadline:
            snapshot = {status.service: status for status in self.ps()}
            if wanted.issubset(snapshot):
                ordered = tuple(snapshot[service] for service in services)
                if all(status.is_ready for status in ordered):
                    return ordered
            time.sleep(self.poll_interval)

        details = ", ".join(
            f"{name}={snapshot[name].state}/{snapshot[name].health}" for name in sorted(snapshot)
        )
        raise RuntimeError(
            "Timed out waiting for compose services to become ready: "
            f"{', '.join(services)}; last snapshot: {details or 'no services reported'}"
        )

    def wait_until_state(
        self,
        service: str,
        *,
        state: str,
        exit_code: int | None = None,
        health: str | None = None,
        all_services: bool = True,
        timeout: float | None = None,
    ) -> ComposeServiceStatus:
        """Poll compose state until one service reaches the requested state."""
        if not service.strip():
            raise ValueError("Compose state polling requires a non-blank service name")
        if not state.strip():
            raise ValueError("Compose state polling requires a non-blank target state")

        deadline = time.monotonic() + (timeout or self.ready_timeout)
        snapshot: dict[str, ComposeServiceStatus] = {}

        while time.monotonic() < deadline:
            snapshot = {status.service: status for status in self.ps(all_services=all_services)}
            current = snapshot.get(service)
            if current is not None and current.state == state:
                if exit_code is not None and current.exit_code != exit_code:
                    time.sleep(self.poll_interval)
                    continue
                if health is not None and current.health != health:
                    time.sleep(self.poll_interval)
                    continue
                return current
            time.sleep(self.poll_interval)

        if service in snapshot:
            last = snapshot[service]
            details = f"{service}={last.state}/{last.health}/{last.exit_code}"
        else:
            details = f"{service}=missing"
        raise RuntimeError(
            "Timed out waiting for compose service state: "
            f"{service}->{state}; last snapshot: {details}"
        )
