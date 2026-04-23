from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from tests.system.deployments.runtime_overrides import (
    configure_runtime_host_gateway,
    configure_runtime_relay_targets,
    prepare_runtime_compose_config,
    resolve_runtime_relay_url,
)
from tests.system.harness import RuntimeAddressPlan


def _load_yaml(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text())
    assert isinstance(payload, dict)
    return payload


class TestPrepareRuntimeComposeConfig:
    def test_overrides_runtime_relay_targets(self, tmp_path: Path) -> None:
        plan = RuntimeAddressPlan.create("lilbrotr", tmp_path, "relay-runtime-overrides")
        relay = MagicMock()
        relay.inspect.return_value = {
            "NetworkSettings": {
                "Networks": {
                    plan.data_network_name: {
                        "IPAddress": "172.31.0.10",
                    }
                }
            }
        }

        prepare_runtime_compose_config(plan)
        relay_url = configure_runtime_relay_targets(plan, relay)

        config_dir = plan.runtime_root / "config"
        dvm_config = _load_yaml(config_dir / "services" / "dvm.yaml")
        assert relay_url == "ws://172.31.0.10:8080"
        assert dvm_config["relays"] == [relay_url]

        assertor_config = _load_yaml(config_dir / "services" / "assertor.yaml")
        assert assertor_config["publishing"] == {"relays": [relay_url]}
        assert assertor_config["trusted_provider_list"] == {
            "enabled": True,
            "relay_hint": "wss://relay.damus.io",
            "tag_names": ["rank"],
        }

    def test_rewrites_compose_runtime_mounts_to_runtime_tree(self, tmp_path: Path) -> None:
        plan = RuntimeAddressPlan.create("bigbrotr", tmp_path, "compose-runtime-overrides")

        prepare_runtime_compose_config(plan)

        compose_data = _load_yaml(plan.compose_file)
        services = compose_data["services"]
        assert isinstance(services, dict)

        for service_name in ("seeder", "api", "assertor"):
            service = services[service_name]
            assert isinstance(service, dict)
            volumes = service.get("volumes")
            assert isinstance(volumes, list)
            assert any(
                isinstance(spec, str) and spec.startswith(f"{plan.runtime_root / 'config'}:")
                for spec in volumes
            )

        seeder_service = services["seeder"]
        assert isinstance(seeder_service, dict)
        seeder_volumes = seeder_service.get("volumes")
        assert isinstance(seeder_volumes, list)
        assert any(
            isinstance(spec, str) and spec.startswith(f"{plan.runtime_root / 'static'}:")
            for spec in seeder_volumes
        )


class TestConfigureRuntimeHostGateway:
    def test_adds_host_gateway_alias_once_for_requested_services(self, tmp_path: Path) -> None:
        plan = RuntimeAddressPlan.create("bigbrotr", tmp_path, "compose-runtime-host-gateway")
        prepare_runtime_compose_config(plan)

        configure_runtime_host_gateway(plan, "finder", "finder")

        compose_data = _load_yaml(plan.compose_file)
        services = compose_data["services"]
        assert isinstance(services, dict)
        finder = services["finder"]
        assert isinstance(finder, dict)
        assert finder["extra_hosts"] == ["host.docker.internal:host-gateway"]

    def test_rejects_unknown_service_name(self, tmp_path: Path) -> None:
        plan = RuntimeAddressPlan.create("bigbrotr", tmp_path, "compose-runtime-host-gateway")
        prepare_runtime_compose_config(plan)

        with pytest.raises(RuntimeError, match="does not contain service 'unknown'"):
            configure_runtime_host_gateway(plan, "unknown")


class TestResolveRuntimeRelayUrl:
    def test_uses_private_data_network_address(self, tmp_path: Path) -> None:
        plan = RuntimeAddressPlan.create("bigbrotr", tmp_path, "relay-runtime-url")
        relay = MagicMock()
        relay.inspect.return_value = {
            "NetworkSettings": {
                "Networks": {
                    plan.data_network_name: {
                        "IPAddress": "172.22.0.15",
                    }
                }
            }
        }

        assert resolve_runtime_relay_url(plan, relay) == "ws://172.22.0.15:8080"
