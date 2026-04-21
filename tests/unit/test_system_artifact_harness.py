from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.system.harness import SystemArtifactBundle, sanitize_artifact_component


@dataclass(frozen=True, slots=True)
class SnapshotRow:
    relay_url: str
    seen_count: int


class TestSanitizeArtifactComponent:
    def test_normalizes_unsafe_characters(self) -> None:
        assert sanitize_artifact_component(" grafana / dashboards ") == "grafana-dashboards"

    def test_rejects_empty_after_normalization(self) -> None:
        with pytest.raises(ValueError, match="safe character"):
            sanitize_artifact_component(" / ")


class TestSystemArtifactBundle:
    def test_create_materializes_canonical_layout_and_manifest(self, tmp_path: Path) -> None:
        bundle = SystemArtifactBundle.create(tmp_path, "compose run / one")

        assert bundle.root.name == "compose-run-one"
        assert (bundle.root / "containers").is_dir()
        assert (bundle.root / "observability" / "prometheus").is_dir()
        assert (bundle.root / "observability" / "grafana").is_dir()
        assert (bundle.root / "observability" / "alertmanager").is_dir()
        assert (bundle.root / "relay").is_dir()
        assert (bundle.root / "database").is_dir()
        assert bundle.manifest_path.is_file()
        assert '"records": []' in bundle.manifest_path.read_text()

    def test_capture_container_logs_updates_manifest(self, tmp_path: Path) -> None:
        bundle = SystemArtifactBundle.create(tmp_path, "compose-run")

        log_path = bundle.capture_container_logs("api", "hello\nworld\n")

        assert log_path.read_text() == "hello\nworld\n"
        manifest = bundle.manifest_path.read_text()
        assert '"category": "containers"' in manifest
        assert '"relative_path": "containers/api.log"' in manifest

    def test_capture_prometheus_targets_writes_json(self, tmp_path: Path) -> None:
        bundle = SystemArtifactBundle.create(tmp_path, "compose-run")

        path = bundle.capture_prometheus_targets({"activeTargets": [{"health": "up"}]})

        assert path.read_text().strip().startswith("{")
        assert '"activeTargets"' in path.read_text()

    def test_capture_grafana_response_wraps_metadata(self, tmp_path: Path) -> None:
        bundle = SystemArtifactBundle.create(tmp_path, "compose-run")

        path = bundle.capture_grafana_response(
            "health",
            status_code=200,
            payload={"database": "ok"},
            headers={"content-type": "application/json"},
        )

        rendered = path.read_text()
        assert '"status_code": 200' in rendered
        assert '"database": "ok"' in rendered
        assert '"content-type": "application/json"' in rendered

    def test_capture_relay_events_and_db_snapshot_support_dataclasses(self, tmp_path: Path) -> None:
        bundle = SystemArtifactBundle.create(tmp_path, "compose-run")

        relay_path = bundle.capture_relay_events(
            "relay-capture",
            [{"kind": 30382, "id": "abc123"}],
        )
        snapshot_path = bundle.capture_db_snapshot(
            "relay-stats",
            [SnapshotRow(relay_url="wss://relay.example.com", seen_count=2)],
        )

        assert '"kind": 30382' in relay_path.read_text()
        assert '"relay_url": "wss://relay.example.com"' in snapshot_path.read_text()
        manifest = bundle.manifest_path.read_text()
        assert '"relative_path": "relay/relay-capture.json"' in manifest
        assert '"relative_path": "database/relay-stats.json"' in manifest
