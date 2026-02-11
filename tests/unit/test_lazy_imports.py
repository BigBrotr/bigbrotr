"""Tests for lazy import system in bigbrotr.__init__."""

from __future__ import annotations

import importlib
import sys

import pytest


class TestLazyImports:
    """Test PEP 562 lazy loading in bigbrotr.__init__."""

    def test_lazy_import_does_not_eagerly_load(self) -> None:
        """Verify that importing bigbrotr does not eagerly load subpackages."""
        # Remove cached bigbrotr modules
        for mod in list(sys.modules):
            if mod.startswith("bigbrotr"):
                del sys.modules[mod]

        importlib.import_module("bigbrotr")

        # Subpackages should not be loaded until accessed
        assert "bigbrotr.core" not in sys.modules
        assert "bigbrotr.models" not in sys.modules
        assert "bigbrotr.services" not in sys.modules
        assert "bigbrotr.nips" not in sys.modules

    def test_lazy_import_resolves_on_access(self) -> None:
        """Verify that lazy attributes resolve correctly."""
        from bigbrotr import Relay
        from bigbrotr.models.relay import Relay as DirectRelay

        assert Relay is DirectRelay

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

    def test_version_is_accessible(self) -> None:
        """Verify that __version__ is set from package metadata."""
        import bigbrotr

        assert hasattr(bigbrotr, "__version__")
        assert isinstance(bigbrotr.__version__, str)
        assert bigbrotr.__version__  # Not empty
