"""Tests for lazy import system in bigbrotr.__init__."""

from __future__ import annotations

import importlib
import sys
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest


class TestLazyImports:
    """Test PEP 562 lazy loading in bigbrotr.__init__."""

    def test_lazy_import_does_not_eagerly_load(self) -> None:
        """Verify that importing bigbrotr does not eagerly load subpackages."""
        # Snapshot and restore sys.modules to avoid polluting other tests.
        saved = dict(sys.modules)
        try:
            for mod in list(sys.modules):
                if mod.startswith("bigbrotr"):
                    del sys.modules[mod]

            importlib.import_module("bigbrotr")

            assert "bigbrotr.core" not in sys.modules
            assert "bigbrotr.models" not in sys.modules
            assert "bigbrotr.services" not in sys.modules
            assert "bigbrotr.nips" not in sys.modules
        finally:
            sys.modules.update(saved)

    def test_lazy_import_resolves_on_access(self) -> None:
        """Verify that lazy attributes resolve correctly."""
        from bigbrotr import Relay
        from bigbrotr.models.relay import Relay as DirectRelay

        assert Relay is DirectRelay

    def test_top_level_service_exports_include_assertor(self) -> None:
        """Verify that the full built-in service set is available from the package root."""
        from bigbrotr import Assertor, AssertorConfig
        from bigbrotr.services.assertor import Assertor as DirectAssertor
        from bigbrotr.services.assertor import AssertorConfig as DirectAssertorConfig

        assert Assertor is DirectAssertor
        assert AssertorConfig is DirectAssertorConfig

    def test_lazy_import_caches_after_first_access(self) -> None:
        """Verify that resolved attributes are cached in globals."""
        import bigbrotr

        # First access triggers __getattr__
        _ = bigbrotr.Relay

        # Second access should hit the cached global, not __getattr__
        assert "Relay" in vars(bigbrotr)

    def test_lazy_import_invalid_attribute(self) -> None:
        """Verify that invalid attributes raise AttributeError."""
        import bigbrotr

        with pytest.raises(AttributeError, match="no_such_thing"):
            _ = getattr(bigbrotr, "no_such_thing")  # noqa: B009

    def test_all_exports_are_in_lazy_imports(self) -> None:
        """Verify that __all__ and _LAZY_IMPORTS are in sync."""
        import bigbrotr

        all_set = set(bigbrotr.__all__)
        lazy_set = set(bigbrotr._LAZY_IMPORTS)
        assert all_set == lazy_set

    def test_dir_returns_all(self) -> None:
        """Verify that dir(bigbrotr) returns __all__."""
        import bigbrotr

        assert dir(bigbrotr) == bigbrotr.__all__

    def test_services_package_is_lazy(self) -> None:
        saved = dict(sys.modules)
        try:
            for mod in list(sys.modules):
                if mod.startswith("bigbrotr.services"):
                    del sys.modules[mod]

            importlib.import_module("bigbrotr.services")

            assert "bigbrotr.services.api" not in sys.modules
            assert "bigbrotr.services.monitor" not in sys.modules
            assert "bigbrotr.services.dvm" not in sys.modules
        finally:
            sys.modules.update(saved)

    def test_nips_package_is_lazy(self) -> None:
        saved = dict(sys.modules)
        try:
            for mod in list(sys.modules):
                if mod.startswith("bigbrotr.nips"):
                    del sys.modules[mod]

            importlib.import_module("bigbrotr.nips")

            assert "bigbrotr.nips.nip11" not in sys.modules
            assert "bigbrotr.nips.nip66" not in sys.modules
            assert "bigbrotr.nips.registry" not in sys.modules
        finally:
            sys.modules.update(saved)

    def test_services_registry_does_not_import_service_modules(self) -> None:
        saved = dict(sys.modules)
        try:
            for mod in list(sys.modules):
                if mod.startswith("bigbrotr.services"):
                    del sys.modules[mod]

            importlib.import_module("bigbrotr.services.registry")

            assert "bigbrotr.services.api" not in sys.modules
            assert "bigbrotr.services.monitor" not in sys.modules
            assert "bigbrotr.services.dvm" not in sys.modules
        finally:
            sys.modules.update(saved)

    def test_version_is_accessible(self) -> None:
        """Verify that __version__ is set from package metadata."""
        import bigbrotr

        assert hasattr(bigbrotr, "__version__")
        assert isinstance(bigbrotr.__version__, str)
        assert bigbrotr.__version__  # Not empty

    def test_resolve_version_prefers_pyproject_version(self, tmp_path: Path) -> None:
        import bigbrotr

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nversion = '9.9.9'\n")

        with patch("bigbrotr._get_version", return_value="5.0.1"):
            assert bigbrotr._resolve_version(pyproject) == "9.9.9"

    def test_resolve_version_falls_back_to_runtime_metadata_when_pyproject_missing(self) -> None:
        import bigbrotr

        with patch("bigbrotr._get_version", return_value="6.6.9"):
            assert bigbrotr._resolve_version(Path("/definitely/missing/pyproject.toml")) == "6.6.9"

    def test_resolve_version_returns_unknown_when_no_metadata_is_available(self) -> None:
        import bigbrotr

        with patch("bigbrotr._get_version", side_effect=bigbrotr.PackageNotFoundError):
            assert (
                bigbrotr._resolve_version(Path("/definitely/missing/pyproject.toml")) == "0+unknown"
            )

    def test_source_tree_version_matches_pyproject(self) -> None:
        import bigbrotr

        expected = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
        assert bigbrotr._source_tree_version() == expected
