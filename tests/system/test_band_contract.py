from pathlib import Path


def test_system_band_scaffold_exists() -> None:
    root = Path(__file__).resolve().parent

    assert (root / "README.md").is_file()
    assert (root / "harness").is_dir()
    assert (root / "pipelines").is_dir()
    assert (root / "pipelines" / "README.md").is_file()
    assert (root / "services").is_dir()
    assert (root / "services" / "README.md").is_file()
