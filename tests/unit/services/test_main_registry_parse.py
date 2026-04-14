from pathlib import Path
from unittest.mock import patch

import pytest

from bigbrotr.__main__ import SERVICE_REGISTRY, ServiceEntry, parse_args


class TestServiceRegistry:
    def test_all_services_registered(self) -> None:
        expected = {
            "seeder",
            "finder",
            "validator",
            "monitor",
            "synchronizer",
            "refresher",
            "ranker",
            "api",
            "dvm",
            "assertor",
        }
        assert set(SERVICE_REGISTRY.keys()) == expected

    def test_service_config_paths(self) -> None:
        from bigbrotr.__main__ import CONFIG_BASE

        for name, (_, config_path) in SERVICE_REGISTRY.items():
            expected = CONFIG_BASE / "services" / f"{name}.yaml"
            assert config_path == expected, f"{name} config path mismatch"

    def test_service_classes_are_base_service_subclasses(self) -> None:
        from bigbrotr.core.base_service import BaseService

        for name, (service_class, _) in SERVICE_REGISTRY.items():
            assert issubclass(service_class, BaseService), (
                f"{name} should be a BaseService subclass"
            )

    def test_registry_entries_are_service_entry(self) -> None:
        for name, entry in SERVICE_REGISTRY.items():
            assert isinstance(entry, ServiceEntry), f"{name} should be a ServiceEntry"

    def test_service_classes_match_expected(self) -> None:
        from bigbrotr.services import (
            Api,
            Assertor,
            Dvm,
            Finder,
            Monitor,
            Ranker,
            Refresher,
            Seeder,
            Synchronizer,
            Validator,
        )

        expected_classes = {
            "seeder": Seeder,
            "finder": Finder,
            "validator": Validator,
            "monitor": Monitor,
            "refresher": Refresher,
            "ranker": Ranker,
            "synchronizer": Synchronizer,
            "api": Api,
            "dvm": Dvm,
            "assertor": Assertor,
        }

        for name, (service_class, _) in SERVICE_REGISTRY.items():
            assert service_class == expected_classes[name]


class TestParseArgs:
    def test_service_required(self) -> None:
        with patch("sys.argv", ["prog"]), pytest.raises(SystemExit):
            parse_args()

    def test_valid_service(self) -> None:
        with patch("sys.argv", ["prog", "finder"]):
            args = parse_args()
            assert args.service == "finder"

    def test_invalid_service_rejected(self) -> None:
        with patch("sys.argv", ["prog", "invalid"]), pytest.raises(SystemExit):
            parse_args()

    def test_all_services_accepted(self) -> None:
        for service_name in SERVICE_REGISTRY:
            with patch("sys.argv", ["prog", service_name]):
                args = parse_args()
                assert args.service == service_name

    def test_config_option(self) -> None:
        with patch("sys.argv", ["prog", "finder", "--config", "custom/config.yaml"]):
            args = parse_args()
            assert args.config == Path("custom/config.yaml")

    def test_config_option_default_is_none(self) -> None:
        with patch("sys.argv", ["prog", "finder"]):
            args = parse_args()
            assert args.config is None

    def test_brotr_config_default(self) -> None:
        from bigbrotr.__main__ import CORE_CONFIG

        with patch("sys.argv", ["prog", "finder"]):
            args = parse_args()
            assert args.brotr_config == CORE_CONFIG

    def test_brotr_config_custom(self) -> None:
        with patch("sys.argv", ["prog", "finder", "--brotr-config", "custom/brotr.yaml"]):
            args = parse_args()
            assert args.brotr_config == Path("custom/brotr.yaml")

    def test_log_level_default(self) -> None:
        with patch("sys.argv", ["prog", "finder"]):
            args = parse_args()
            assert args.log_level == "INFO"

    @pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR"])
    def test_log_level_choices(self, level: str) -> None:
        with patch("sys.argv", ["prog", "finder", "--log-level", level]):
            args = parse_args()
            assert args.log_level == level

    @pytest.mark.parametrize("invalid_level", ["INVALID", "debug", "info"])
    def test_log_level_invalid_rejected(self, invalid_level: str) -> None:
        with (
            patch("sys.argv", ["prog", "finder", "--log-level", invalid_level]),
            pytest.raises(SystemExit),
        ):
            parse_args()

    def test_once_flag_default(self) -> None:
        with patch("sys.argv", ["prog", "finder"]):
            args = parse_args()
            assert args.once is False

    def test_once_flag_enabled(self) -> None:
        with patch("sys.argv", ["prog", "finder", "--once"]):
            args = parse_args()
            assert args.once is True

    def test_combined_arguments(self) -> None:
        with patch(
            "sys.argv",
            [
                "prog",
                "monitor",
                "--config",
                "custom/monitor.yaml",
                "--brotr-config",
                "custom/brotr.yaml",
                "--log-level",
                "DEBUG",
                "--once",
            ],
        ):
            args = parse_args()
            assert args.service == "monitor"
            assert args.config == Path("custom/monitor.yaml")
            assert args.brotr_config == Path("custom/brotr.yaml")
            assert args.log_level == "DEBUG"
            assert args.once is True
