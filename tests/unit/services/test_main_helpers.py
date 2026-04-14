import logging
from pathlib import Path
from typing import Any

import pytest

from bigbrotr.__main__ import _apply_pool_overrides, _load_yaml_dict, setup_logging


_PASSWORD_ENV = "DB_WRITER_PASSWORD"  # pragma: allowlist secret


class TestSetupLogging:
    def _cleanup_root_handlers(self) -> None:
        from bigbrotr.core.logger import StructuredFormatter

        logging.root.handlers = [
            h for h in logging.root.handlers if not isinstance(h.formatter, StructuredFormatter)
        ]

    @pytest.mark.parametrize(
        ("level_name", "level_value"),
        [
            ("DEBUG", logging.DEBUG),
            ("INFO", logging.INFO),
            ("WARNING", logging.WARNING),
            ("ERROR", logging.ERROR),
        ],
    )
    def test_log_level_configured(self, level_name: str, level_value: int) -> None:
        setup_logging(level_name)
        assert logging.root.level == level_value
        self._cleanup_root_handlers()

    def test_structured_formatter_installed(self) -> None:
        from bigbrotr.core.logger import StructuredFormatter

        setup_logging("INFO")
        structured_handlers = [
            h for h in logging.root.handlers if isinstance(h.formatter, StructuredFormatter)
        ]
        assert len(structured_handlers) >= 1
        assert all(isinstance(h, logging.StreamHandler) for h in structured_handlers)
        self._cleanup_root_handlers()

    def test_structured_formatter_is_not_duplicated(self) -> None:
        from bigbrotr.core.logger import StructuredFormatter

        setup_logging("INFO")
        setup_logging("DEBUG")

        structured_handlers = [
            h for h in logging.root.handlers if isinstance(h.formatter, StructuredFormatter)
        ]
        assert len(structured_handlers) == 1
        assert logging.root.level == logging.DEBUG
        self._cleanup_root_handlers()


class TestLoadYamlDict:
    def test_load_from_existing_file(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text("key: value\nnested:\n  a: 1\n")
        result = _load_yaml_dict(config_file)
        assert result == {"key": "value", "nested": {"a": 1}}

    def test_load_from_nonexistent_file(self, tmp_path: Path) -> None:
        config_file = tmp_path / "nonexistent.yaml"
        result = _load_yaml_dict(config_file)
        assert result == {}

    def test_load_empty_file(self, tmp_path: Path) -> None:
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")
        result = _load_yaml_dict(config_file)
        assert result == {}

    def test_load_preserves_types(self, tmp_path: Path) -> None:
        config_file = tmp_path / "typed.yaml"
        config_file.write_text("count: 42\nenabled: true\nratio: 3.14\nname: test\n")
        result = _load_yaml_dict(config_file)
        assert result == {"count": 42, "enabled": True, "ratio": 3.14, "name": "test"}


class TestApplyPoolOverrides:
    def test_no_overrides_sets_application_name(self) -> None:
        brotr_dict: dict[str, Any] = {}
        _apply_pool_overrides(brotr_dict, None, "monitor")
        assert brotr_dict["pool"]["server_settings"]["application_name"] == "monitor"

    def test_no_overrides_preserves_existing_application_name(self) -> None:
        brotr_dict: dict[str, Any] = {"pool": {"server_settings": {"application_name": "custom"}}}
        _apply_pool_overrides(brotr_dict, None, "monitor")
        assert brotr_dict["pool"]["server_settings"]["application_name"] == "custom"

    def test_full_overrides(self) -> None:
        brotr_dict: dict[str, Any] = {"pool": {"database": {"host": "pgbouncer"}}}
        overrides = {
            "user": "writer",
            "password_env": _PASSWORD_ENV,
            "min_size": 1,
            "max_size": 3,
        }
        _apply_pool_overrides(brotr_dict, overrides, "monitor")

        assert brotr_dict["pool"]["database"]["user"] == "writer"
        assert brotr_dict["pool"]["database"]["password_env"] == _PASSWORD_ENV
        assert brotr_dict["pool"]["database"]["host"] == "pgbouncer"
        assert brotr_dict["pool"]["limits"]["min_size"] == 1
        assert brotr_dict["pool"]["limits"]["max_size"] == 3
        assert brotr_dict["pool"]["server_settings"]["application_name"] == "monitor"

    def test_partial_override_only_min_size(self) -> None:
        brotr_dict: dict[str, Any] = {"pool": {"database": {"host": "pgbouncer", "user": "admin"}}}
        overrides = {"min_size": 2}
        _apply_pool_overrides(brotr_dict, overrides, "finder")

        assert brotr_dict["pool"]["database"]["user"] == "admin"
        assert brotr_dict["pool"]["limits"]["min_size"] == 2
        assert "max_size" not in brotr_dict["pool"]["limits"]
        assert brotr_dict["pool"]["server_settings"]["application_name"] == "finder"

    def test_explicit_application_name_overrides_service_name(self) -> None:
        brotr_dict: dict[str, Any] = {}
        overrides = {"application_name": "my_custom_app"}
        _apply_pool_overrides(brotr_dict, overrides, "monitor")
        assert brotr_dict["pool"]["server_settings"]["application_name"] == "my_custom_app"

    def test_empty_overrides_dict(self) -> None:
        brotr_dict: dict[str, Any] = {}
        _apply_pool_overrides(brotr_dict, {}, "seeder")
        assert brotr_dict["pool"]["server_settings"]["application_name"] == "seeder"
        assert "database" not in brotr_dict["pool"]
        assert "limits" not in brotr_dict["pool"]

    def test_empty_brotr_dict(self) -> None:
        brotr_dict: dict[str, Any] = {}
        overrides = {"user": "writer", "min_size": 1, "max_size": 5}
        _apply_pool_overrides(brotr_dict, overrides, "synchronizer")

        assert brotr_dict["pool"]["database"]["user"] == "writer"
        assert brotr_dict["pool"]["limits"]["min_size"] == 1
        assert brotr_dict["pool"]["limits"]["max_size"] == 5
        assert brotr_dict["pool"]["server_settings"]["application_name"] == "synchronizer"
