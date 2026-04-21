"""Runtime-only deployment overrides for deterministic stack certification."""

from __future__ import annotations

import asyncio
import os
import shutil
from typing import TYPE_CHECKING

import yaml

from tests.system.harness import LocalRelayRuntime, RuntimeAddressPlan
from tests.system.harness.compose import deployment_dir


if TYPE_CHECKING:
    from pathlib import Path


BOOTSTRAP_SERVICES = ("postgres", "pgbouncer", "tor")
_CONFIG_VOLUME_TARGET = "/app/config"
_BASELINE_RELAY_CONTAINER_PORT = 8080


def prepare_runtime_compose_config(plan: RuntimeAddressPlan) -> None:
    """Copy deployment config into the runtime root and rewrite bind mounts to it."""
    config_dir = _copy_runtime_config_tree(plan)
    _rewrite_runtime_compose_config_mounts(plan.compose_file, config_dir)


def start_baseline_relay(plan: RuntimeAddressPlan) -> LocalRelayRuntime:
    """Start one real relay container attached to the runtime data network."""
    relay = LocalRelayRuntime(
        role=f"{plan.profile}-baseline",
        runtime_dir=plan.runtime_root / "relay",
        network_name=plan.data_network_name,
    )
    original_docker_config = os.environ.get("DOCKER_CONFIG")
    relay.start()
    if original_docker_config is None:
        os.environ.pop("DOCKER_CONFIG", None)
    else:
        os.environ["DOCKER_CONFIG"] = original_docker_config
    asyncio.run(relay.wait_until_ready())
    return relay


def configure_runtime_relay_targets(plan: RuntimeAddressPlan, relay: LocalRelayRuntime) -> str:
    """Point runtime config at the started local relay on the compose data network."""
    relay_url = resolve_runtime_relay_url(plan, relay)
    _override_runtime_relay_targets(plan.runtime_root / "config", relay_url)
    return relay_url


def _copy_runtime_config_tree(plan: RuntimeAddressPlan) -> Path:
    source_dir = deployment_dir(plan.profile) / "config"
    target_dir = plan.runtime_root / "config"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)
    return target_dir


def resolve_runtime_relay_url(plan: RuntimeAddressPlan, relay: LocalRelayRuntime) -> str:
    """Resolve the relay's private data-network address into one canonical config URL."""
    inspect_payload = relay.inspect()
    networks = inspect_payload.get("NetworkSettings", {}).get("Networks", {})
    if not isinstance(networks, dict):
        raise RuntimeError("Relay inspect payload did not include network settings")

    network_payload = networks.get(plan.data_network_name)
    if not isinstance(network_payload, dict):
        raise RuntimeError(f"Relay is not attached to network {plan.data_network_name!r}")

    ip_address = network_payload.get("IPAddress")
    if not isinstance(ip_address, str) or not ip_address:
        raise RuntimeError(f"Relay network {plan.data_network_name!r} did not report an IP address")

    return f"ws://{ip_address}:{_BASELINE_RELAY_CONTAINER_PORT}"


def _override_runtime_relay_targets(config_dir: Path, relay_url: str) -> None:
    dvm_path = config_dir / "services" / "dvm.yaml"
    dvm_config = yaml.safe_load(dvm_path.read_text())
    dvm_config["relays"] = [relay_url]
    dvm_path.write_text(yaml.safe_dump(dvm_config, sort_keys=False))

    assertor_path = config_dir / "services" / "assertor.yaml"
    assertor_config = yaml.safe_load(assertor_path.read_text())
    publishing = assertor_config.setdefault("publishing", {})
    publishing["relays"] = [relay_url]
    trusted_provider_list = assertor_config.setdefault("trusted_provider_list", {})
    trusted_provider_list["relay_hint"] = relay_url
    assertor_path.write_text(yaml.safe_dump(assertor_config, sort_keys=False))


def _rewrite_runtime_compose_config_mounts(compose_file: Path, config_dir: Path) -> None:
    compose_data = yaml.safe_load(compose_file.read_text())
    services = compose_data.get("services", {})
    for service_data in services.values():
        volumes = service_data.get("volumes")
        if not isinstance(volumes, list):
            continue
        service_data["volumes"] = [
            _replace_config_volume(spec, config_dir) if isinstance(spec, str) else spec
            for spec in volumes
        ]
    compose_file.write_text(yaml.safe_dump(compose_data, sort_keys=False))


def _replace_config_volume(spec: str, config_dir: Path) -> str:
    parts = spec.split(":")
    if len(parts) < 2 or parts[1] != _CONFIG_VOLUME_TARGET:
        return spec
    parts[0] = config_dir.as_posix()
    return ":".join(parts)
