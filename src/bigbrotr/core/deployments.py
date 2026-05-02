"""Helpers for built-in deployment contracts, storage profiles, and path resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeGuard


if TYPE_CHECKING:
    from collections.abc import Iterable


DeploymentProfile = Literal["bigbrotr", "lilbrotr"]
StorageProfile = Literal["full_archive", "lightweight_archive"]
EventPayloadMode = Literal["full", "lightweight"]
DEFAULT_DEPLOYMENT_PROFILE: DeploymentProfile = "bigbrotr"
BUILTIN_DEPLOYMENT_PROFILES: tuple[DeploymentProfile, ...] = ("bigbrotr", "lilbrotr")
BUILTIN_STORAGE_PROFILES: tuple[StorageProfile, ...] = ("full_archive", "lightweight_archive")

CONFIG_DIR = Path("config")
BROTR_CONFIG = CONFIG_DIR / "brotr.yaml"
SERVICES_CONFIG_DIR = CONFIG_DIR / "services"
DOCKER_COMPOSE = Path("docker-compose.yaml")
ENV_EXAMPLE = Path(".env.example")
POSTGRES_INIT_DIR = Path("postgres") / "init"
_REQUIRED_DEPLOYMENT_PATHS: tuple[Path, ...] = (
    DOCKER_COMPOSE,
    ENV_EXAMPLE,
    BROTR_CONFIG,
    SERVICES_CONFIG_DIR,
    POSTGRES_INIT_DIR,
)


@dataclass(frozen=True, slots=True)
class StorageProfileSpec:
    """Contract metadata for one storage profile."""

    name: StorageProfile
    description: str
    event_payload_mode: EventPayloadMode
    sql_template_namespace: str | None
    stores_event_tags: bool
    stores_event_content: bool
    stores_event_signature: bool

    @property
    def stores_full_event_payload(self) -> bool:
        """Return whether this profile stores the full Nostr event payload."""
        return self.event_payload_mode == "full"


@dataclass(frozen=True, slots=True)
class BuiltinDeploymentSpec:
    """Contract metadata for one built-in deployment profile."""

    name: DeploymentProfile
    description: str
    database_name: str
    storage_profile: StorageProfile


_STORAGE_PROFILE_SPECS: dict[StorageProfile, StorageProfileSpec] = {
    "full_archive": StorageProfileSpec(
        name="full_archive",
        description="Complete event archive with tags, content, and signatures stored.",
        event_payload_mode="full",
        sql_template_namespace=None,
        stores_event_tags=True,
        stores_event_content=True,
        stores_event_signature=True,
    ),
    "lightweight_archive": StorageProfileSpec(
        name="lightweight_archive",
        description=(
            "Compact event archive that keeps event identity, metadata, and tagvalues while "
            "leaving tags/content/signature nullable and unpopulated."
        ),
        event_payload_mode="lightweight",
        sql_template_namespace="lilbrotr",
        stores_event_tags=False,
        stores_event_content=False,
        stores_event_signature=False,
    ),
}

_BUILTIN_DEPLOYMENT_SPECS: dict[DeploymentProfile, BuiltinDeploymentSpec] = {
    "bigbrotr": BuiltinDeploymentSpec(
        name="bigbrotr",
        description="Reference deployment for the full archive storage profile.",
        database_name="bigbrotr",
        storage_profile="full_archive",
    ),
    "lilbrotr": BuiltinDeploymentSpec(
        name="lilbrotr",
        description="Reference deployment for the lightweight archive storage profile.",
        database_name="lilbrotr",
        storage_profile="lightweight_archive",
    ),
}


def _is_builtin_profile(profile: str) -> TypeGuard[DeploymentProfile]:
    return profile in BUILTIN_DEPLOYMENT_PROFILES


def _is_storage_profile(profile: str) -> TypeGuard[StorageProfile]:
    return profile in BUILTIN_STORAGE_PROFILES


def _normalize_builtin_profile(profile: str) -> DeploymentProfile:
    """Validate and normalize one built-in deployment profile name."""
    if not _is_builtin_profile(profile):
        choices = ", ".join(BUILTIN_DEPLOYMENT_PROFILES)
        raise ValueError(
            f"Unsupported built-in deployment profile: {profile!r} (expected one of {choices})"
        )
    return profile


def _normalize_storage_profile(profile: str) -> StorageProfile:
    """Validate and normalize one built-in storage profile name."""
    if not _is_storage_profile(profile):
        choices = ", ".join(BUILTIN_STORAGE_PROFILES)
        raise ValueError(
            f"Unsupported built-in storage profile: {profile!r} (expected one of {choices})"
        )
    return profile


def builtin_deployment_spec(profile: str) -> BuiltinDeploymentSpec:
    """Return the canonical contract metadata for one built-in deployment."""
    normalized_profile = _normalize_builtin_profile(profile)
    return _BUILTIN_DEPLOYMENT_SPECS[normalized_profile]


def storage_profile_spec(profile: str) -> StorageProfileSpec:
    """Return the canonical contract metadata for one built-in storage profile."""
    normalized_profile = _normalize_storage_profile(profile)
    return _STORAGE_PROFILE_SPECS[normalized_profile]


@dataclass(frozen=True, slots=True)
class DeploymentLayout:
    """Concrete folder layout for one deployment profile."""

    name: DeploymentProfile
    root: Path

    @property
    def brotr_config_path(self) -> Path:
        """Return the shared brotr config path for this deployment."""
        return self.root / BROTR_CONFIG

    @property
    def spec(self) -> BuiltinDeploymentSpec:
        """Return the canonical built-in deployment metadata."""
        return builtin_deployment_spec(self.name)

    @property
    def storage_profile(self) -> StorageProfile:
        """Return the storage profile used by this deployment."""
        return self.spec.storage_profile

    @property
    def storage_profile_contract(self) -> StorageProfileSpec:
        """Return the storage-profile contract metadata for this deployment."""
        return storage_profile_spec(self.storage_profile)

    @property
    def service_config_dir(self) -> Path:
        """Return the service-config directory for this deployment."""
        return self.root / SERVICES_CONFIG_DIR

    @property
    def docker_compose_path(self) -> Path:
        """Return the Docker Compose file for this deployment."""
        return self.root / DOCKER_COMPOSE

    @property
    def env_example_path(self) -> Path:
        """Return the example environment file for this deployment."""
        return self.root / ENV_EXAMPLE

    @property
    def postgres_init_dir(self) -> Path:
        """Return the generated PostgreSQL init directory for this deployment."""
        return self.root / POSTGRES_INIT_DIR

    def service_config_path(self, service_name: str) -> Path:
        """Return the config path for one service inside this deployment."""
        return self.service_config_dir / f"{service_name}.yaml"

    def required_paths(self, *, service_names: Iterable[str] = ()) -> tuple[Path, ...]:
        """Return the required deployment-contract paths for this layout."""
        service_paths = tuple(
            self.service_config_path(service_name) for service_name in service_names
        )
        required_root_paths = tuple(
            self.root / relative_path for relative_path in _REQUIRED_DEPLOYMENT_PATHS
        )
        return required_root_paths + service_paths

    def missing_required_paths(self, *, service_names: Iterable[str] = ()) -> tuple[Path, ...]:
        """Return the required deployment-contract paths that do not exist."""
        return tuple(
            path for path in self.required_paths(service_names=service_names) if not path.exists()
        )


def _looks_like_deployment_root(candidate: Path, *, profile: DeploymentProfile) -> bool:
    """Return whether one path looks like the root of the requested deployment."""
    if candidate.name != profile:
        return False
    return not DeploymentLayout(profile, candidate).missing_required_paths()


def _search_checkout_root(profile: DeploymentProfile, *, cwd: Path) -> Path | None:
    """Search upward for one repository checkout containing the deployment folder."""
    for base in (cwd, *cwd.parents):
        candidate = base / "deployments" / profile
        if not candidate.exists():
            continue
        if not DeploymentLayout(profile, candidate).missing_required_paths():
            return candidate
    return None


def resolve_builtin_deployment_root(
    profile: str,
    *,
    cwd: Path | None = None,
) -> Path:
    """Resolve the concrete root path for one built-in deployment profile.

    Resolution prefers:

    1. The current working directory if it is already the deployment root.
    2. A repository checkout found by searching upward for ``deployments/<profile>``.
    3. The relative fallback ``deployments/<profile>`` if nothing concrete exists yet.
    """
    normalized_profile = _normalize_builtin_profile(profile)
    current_dir = (cwd or Path.cwd()).resolve()
    if _looks_like_deployment_root(current_dir, profile=normalized_profile):
        return current_dir

    checkout_candidate = _search_checkout_root(normalized_profile, cwd=current_dir)
    if checkout_candidate is not None:
        return checkout_candidate

    return Path("deployments") / normalized_profile


def deployment_layout(
    profile: str,
    *,
    cwd: Path | None = None,
) -> DeploymentLayout:
    """Build the resolved folder layout for one built-in deployment profile."""
    normalized_profile = _normalize_builtin_profile(profile)
    return DeploymentLayout(
        name=normalized_profile,
        root=resolve_builtin_deployment_root(normalized_profile, cwd=cwd),
    )
