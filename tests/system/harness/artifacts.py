"""Artifact-capture helpers for higher-band system tests."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path


SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]+")
DEFAULT_ARTIFACT_SUBDIRS = (
    "containers",
    "observability/prometheus",
    "observability/grafana",
    "observability/alertmanager",
    "relay",
    "database",
)


def sanitize_artifact_component(value: str) -> str:
    """Normalize a path component used in artifact filenames and directories."""
    cleaned = SAFE_COMPONENT_RE.sub("-", value.strip())
    cleaned = cleaned.strip(".-")
    if not cleaned:
        raise ValueError("Artifact component must contain at least one safe character")
    return cleaned


def _json_default(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, set | tuple):
        return list(value)
    return repr(value)


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """Manifest entry for one captured runtime artifact."""

    category: str
    name: str
    relative_path: str


@dataclass(slots=True)
class SystemArtifactBundle:
    """Own the filesystem layout and manifest for one higher-band test run."""

    root: Path
    records: list[ArtifactRecord] = field(default_factory=list)

    @classmethod
    def create(cls, base_dir: Path, run_name: str) -> SystemArtifactBundle:
        """Create a new artifact bundle with the canonical directory layout."""
        root = base_dir / sanitize_artifact_component(run_name)
        root.mkdir(parents=True, exist_ok=True)
        for relative_dir in DEFAULT_ARTIFACT_SUBDIRS:
            (root / relative_dir).mkdir(parents=True, exist_ok=True)
        bundle = cls(root=root)
        bundle._write_manifest()
        return bundle

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def _record(self, category: str, name: str, path: Path) -> None:
        self.records.append(
            ArtifactRecord(
                category=category,
                name=name,
                relative_path=path.relative_to(self.root).as_posix(),
            )
        )
        self._write_manifest()

    def _write_manifest(self) -> None:
        payload = {
            "root": self.root.as_posix(),
            "records": [asdict(record) for record in self.records],
        }
        self.manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def write_text_artifact(
        self,
        *,
        category: str,
        subdir: str,
        name: str,
        contents: str,
        suffix: str,
    ) -> Path:
        """Write a text artifact and register it in the bundle manifest."""
        relative_dir = Path(subdir)
        filename = f"{sanitize_artifact_component(name)}{suffix}"
        path = self.root / relative_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
        self._record(category, name, path)
        return path

    def write_json_artifact(
        self,
        *,
        category: str,
        subdir: str,
        name: str,
        payload: object,
        suffix: str = ".json",
    ) -> Path:
        """Write a JSON artifact and register it in the bundle manifest."""
        relative_dir = Path(subdir)
        filename = f"{sanitize_artifact_component(name)}{suffix}"
        path = self.root / relative_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        rendered = json.dumps(payload, indent=2, sort_keys=True, default=_json_default)
        path.write_text(rendered + "\n")
        self._record(category, name, path)
        return path

    def capture_container_logs(self, service_name: str, logs: str) -> Path:
        """Capture logs for one named container or compose service."""
        return self.write_text_artifact(
            category="containers",
            subdir="containers",
            name=service_name,
            contents=logs,
            suffix=".log",
        )

    def capture_prometheus_targets(self, payload: object) -> Path:
        """Capture the Prometheus target snapshot for the current run."""
        return self.write_json_artifact(
            category="observability",
            subdir="observability/prometheus",
            name="targets",
            payload=payload,
        )

    def capture_grafana_response(
        self,
        name: str,
        *,
        status_code: int,
        payload: object,
        headers: dict[str, str] | None = None,
    ) -> Path:
        """Capture one Grafana health or provisioning response."""
        envelope = {
            "status_code": status_code,
            "headers": headers or {},
            "payload": payload,
        }
        return self.write_json_artifact(
            category="observability",
            subdir="observability/grafana",
            name=name,
            payload=envelope,
        )

    def capture_alertmanager_response(
        self,
        name: str,
        *,
        status_code: int,
        payload: object,
        headers: dict[str, str] | None = None,
    ) -> Path:
        """Capture one Alertmanager API response."""
        envelope = {
            "status_code": status_code,
            "headers": headers or {},
            "payload": payload,
        }
        return self.write_json_artifact(
            category="observability",
            subdir="observability/alertmanager",
            name=name,
            payload=envelope,
        )

    def capture_relay_events(self, relay_name: str, payload: object) -> Path:
        """Capture relay-published or relay-observed events."""
        return self.write_json_artifact(
            category="relay",
            subdir="relay",
            name=relay_name,
            payload=payload,
        )

    def capture_db_snapshot(self, name: str, payload: object) -> Path:
        """Capture a DB-side snapshot for later audit."""
        return self.write_json_artifact(
            category="database",
            subdir="database",
            name=name,
            payload=payload,
        )
