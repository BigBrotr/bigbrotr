"""Runtime-only deployment overrides for deterministic stack certification."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import yaml

from tests.system.harness import LocalRelayRuntime, RuntimeAddressPlan
from tests.system.harness.compose import deployment_dir


BOOTSTRAP_SERVICES = ("postgres", "pgbouncer", "tor")
_CONFIG_VOLUME_TARGET = "/app/config"
_STATIC_VOLUME_TARGET = "/app/static"
_MONITORING_VOLUME_ROOT = "monitoring"
_BASELINE_RELAY_CONTAINER_PORT = 8080
_RUNTIME_HOST_GATEWAY_ALIAS = "host.docker.internal:host-gateway"


def prepare_runtime_compose_config(plan: RuntimeAddressPlan) -> None:
    """Copy deployment-owned config/static trees into the runtime root and rewrite mounts."""
    config_dir = _copy_runtime_config_tree(plan)
    static_dir = _copy_runtime_static_tree(plan)
    monitoring_dir = _copy_runtime_monitoring_tree(plan)
    _rewrite_runtime_compose_mounts(
        plan.compose_file,
        config_dir=config_dir,
        static_dir=static_dir,
        monitoring_dir=monitoring_dir,
    )


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


def configure_runtime_host_gateway(plan: RuntimeAddressPlan, *service_names: str) -> None:
    """Allow selected runtime services to reach host-side fixture services."""
    if not service_names:
        raise ValueError("Runtime host gateway override requires at least one service")

    compose_data = yaml.safe_load(plan.compose_file.read_text())
    services = compose_data.get("services", {})
    if not isinstance(services, dict):
        raise RuntimeError("Runtime compose file does not contain a services mapping")

    for service_name in service_names:
        if not service_name.strip():
            raise ValueError("Runtime host gateway override requires non-blank service names")
        service_data = services.get(service_name)
        if not isinstance(service_data, dict):
            raise RuntimeError(f"Runtime compose file does not contain service {service_name!r}")
        extra_hosts = service_data.setdefault("extra_hosts", [])
        if not isinstance(extra_hosts, list):
            raise RuntimeError(
                f"Runtime compose service {service_name!r} has a non-list extra_hosts payload"
            )
        if _RUNTIME_HOST_GATEWAY_ALIAS not in extra_hosts:
            extra_hosts.append(_RUNTIME_HOST_GATEWAY_ALIAS)

    plan.compose_file.write_text(yaml.safe_dump(compose_data, sort_keys=False))


def _copy_runtime_config_tree(plan: RuntimeAddressPlan) -> Path:
    source_dir = deployment_dir(plan.profile) / "config"
    target_dir = plan.runtime_root / "config"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)
    return target_dir


def _copy_runtime_static_tree(plan: RuntimeAddressPlan) -> Path:
    source_dir = deployment_dir(plan.profile) / "static"
    target_dir = plan.runtime_root / "static"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)
    return target_dir


def _copy_runtime_monitoring_tree(plan: RuntimeAddressPlan) -> Path:
    source_dir = deployment_dir(plan.profile) / "monitoring"
    target_dir = plan.runtime_root / "monitoring"
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
    assertor_path.write_text(yaml.safe_dump(assertor_config, sort_keys=False))


def _rewrite_runtime_compose_mounts(
    compose_file: Path,
    *,
    config_dir: Path,
    static_dir: Path,
    monitoring_dir: Path,
) -> None:
    compose_data = yaml.safe_load(compose_file.read_text())
    services = compose_data.get("services", {})
    for service_data in services.values():
        volumes = service_data.get("volumes")
        if not isinstance(volumes, list):
            continue
        service_data["volumes"] = [
            _replace_runtime_volume(
                spec,
                config_dir=config_dir,
                static_dir=static_dir,
                monitoring_dir=monitoring_dir,
            )
            if isinstance(spec, str)
            else spec
            for spec in volumes
        ]
    compose_file.write_text(yaml.safe_dump(compose_data, sort_keys=False))


def _replace_runtime_volume(
    spec: str,
    *,
    config_dir: Path,
    static_dir: Path,
    monitoring_dir: Path,
) -> str:
    parts = spec.split(":")
    if len(parts) < 2:
        return spec

    monitoring_source = _replace_runtime_monitoring_source(parts[0], monitoring_dir)
    if monitoring_source is not None:
        parts[0] = monitoring_source
    elif parts[1] == _CONFIG_VOLUME_TARGET:
        parts[0] = config_dir.as_posix()
    elif parts[1] == _STATIC_VOLUME_TARGET:
        parts[0] = static_dir.as_posix()
    else:
        return spec
    return ":".join(parts)


def _replace_runtime_monitoring_source(source: str, monitoring_dir: Path) -> str | None:
    normalized = source.removeprefix("./")
    if normalized == _MONITORING_VOLUME_ROOT:
        return monitoring_dir.as_posix()
    if not normalized.startswith(f"{_MONITORING_VOLUME_ROOT}/"):
        return None

    relative_path = Path(normalized).relative_to(_MONITORING_VOLUME_ROOT)
    return (monitoring_dir / relative_path).as_posix()
