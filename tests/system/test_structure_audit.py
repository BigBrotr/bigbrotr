from __future__ import annotations

from pathlib import Path

import pytest


pytestmark = pytest.mark.system


_SYSTEM_ROOT = Path("tests/system")
_LIVE_SMOKE_ROOT = Path("tests/live_smoke")
_EXPECTED_SYSTEM_ROOT_DIRS = {
    "deployments",
    "harness",
    "observability",
    "pipelines",
    "profiles",
    "relay",
    "resilience",
    "services",
}
_EXPECTED_SYSTEM_ROOT_FILES = {
    "__init__.py",
    "README.md",
    "test_band_contract.py",
    "test_structure_audit.py",
}
_EXPECTED_LIVE_SMOKE_FILES = {
    "__init__.py",
    "README.md",
    "test_band_contract.py",
}
_EXPECTED_SUPPORT_MODULES = {
    "tests/system/deployments/baseline.py",
    "tests/system/deployments/runtime_overrides.py",
    "tests/system/harness/addressing.py",
    "tests/system/harness/artifacts.py",
    "tests/system/harness/compose.py",
    "tests/system/harness/database.py",
    "tests/system/harness/faults.py",
    "tests/system/harness/http.py",
    "tests/system/harness/metrics.py",
    "tests/system/harness/observability.py",
    "tests/system/harness/relay.py",
    "tests/system/harness/websocket.py",
    "tests/system/observability/alertmanager/common.py",
    "tests/system/observability/alerts/common.py",
    "tests/system/observability/grafana/common.py",
    "tests/system/observability/postgres_exporter/common.py",
    "tests/system/observability/prometheus/common.py",
}
_HELPER_ONLY_LEAF_DIRS = {
    Path("tests/system/harness"),
}
_WEAK_MARKERS = (
    "historical",
    "pending migration",
    "superseded",
    "obsolete",
    "placeholder",
    "todo",
)


def _band_files(*roots: Path) -> tuple[Path, ...]:
    files: set[Path] = set()
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            files.add(path)
    return tuple(sorted(files))


def _tracked_dirs(root: Path, tracked_files: tuple[Path, ...]) -> set[Path]:
    dirs = {root}
    for path in tracked_files:
        if root not in path.parents:
            continue
        current = path.parent
        while current != root:
            dirs.add(current)
            current = current.parent
    return dirs


def _tracked_python_files(root: Path, tracked_files: tuple[Path, ...]) -> set[Path]:
    return {path for path in tracked_files if root in path.parents and path.suffix == ".py"}


def _leaf_dirs(root: Path, tracked_dirs: set[Path]) -> set[Path]:
    return {
        path
        for path in tracked_dirs
        if path != root and not any(other.parent == path for other in tracked_dirs if other != path)
    }


def test_system_and_live_smoke_topology_matches_final_contract() -> None:
    tracked = _band_files(_SYSTEM_ROOT, _LIVE_SMOKE_ROOT)

    system_root_entries = {
        path.relative_to(_SYSTEM_ROOT).parts[0] for path in tracked if _SYSTEM_ROOT in path.parents
    }
    live_smoke_entries = {path.name for path in tracked if path.parent == _LIVE_SMOKE_ROOT}

    assert system_root_entries == _EXPECTED_SYSTEM_ROOT_DIRS | _EXPECTED_SYSTEM_ROOT_FILES
    assert live_smoke_entries == _EXPECTED_LIVE_SMOKE_FILES


def test_leaf_packages_ship_readme_init_and_real_assertions() -> None:
    tracked = _band_files(_SYSTEM_ROOT, _LIVE_SMOKE_ROOT)
    system_dirs = _tracked_dirs(_SYSTEM_ROOT, tracked)

    for directory in _leaf_dirs(_SYSTEM_ROOT, system_dirs):
        tracked_names = {path.name for path in tracked if path.parent == directory}
        assert "README.md" in tracked_names, f"{directory} is missing README.md"
        assert "__init__.py" in tracked_names, f"{directory} is missing __init__.py"
        if directory in _HELPER_ONLY_LEAF_DIRS:
            continue
        assert any(name.startswith("test_") for name in tracked_names), (
            f"{directory} must contain at least one test module"
        )


def test_support_modules_stay_scoped_to_explicit_helper_surfaces() -> None:
    tracked = _band_files(_SYSTEM_ROOT)
    tracked_python = {
        path.as_posix()
        for path in _tracked_python_files(_SYSTEM_ROOT, tracked)
        if path.name not in {"__init__.py", "test_band_contract.py", "test_structure_audit.py"}
        and not path.name.startswith("test_")
    }

    assert tracked_python == _EXPECTED_SUPPORT_MODULES


def test_higher_band_docs_have_no_unresolved_weak_markers() -> None:
    tracked = _band_files(_SYSTEM_ROOT, _LIVE_SMOKE_ROOT)
    readmes = [path for path in tracked if path.name == "README.md"]

    for readme in readmes:
        normalized = readme.read_text().lower()
        for marker in _WEAK_MARKERS:
            assert marker not in normalized, f"{readme} still contains unresolved marker {marker!r}"
