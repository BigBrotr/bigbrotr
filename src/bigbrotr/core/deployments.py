"""Helpers for built-in deployment-folder contracts and path resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeGuard


if TYPE_CHECKING:
    from collections.abc import Iterable


DeploymentProfile = Literal["bigbrotr", "lilbrotr"]
DEFAULT_DEPLOYMENT_PROFILE: DeploymentProfile = "bigbrotr"
BUILTIN_DEPLOYMENT_PROFILES: tuple[DeploymentProfile, ...] = ("bigbrotr", "lilbrotr")

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


def _is_builtin_profile(profile: str) -> TypeGuard[DeploymentProfile]:
    return profile in BUILTIN_DEPLOYMENT_PROFILES


def _normalize_builtin_profile(profile: str) -> DeploymentProfile:
    """Validate and normalize one built-in deployment profile name."""
    if not _is_builtin_profile(profile):
        choices = ", ".join(BUILTIN_DEPLOYMENT_PROFILES)
        raise ValueError(
            f"Unsupported built-in deployment profile: {profile!r} (expected one of {choices})"
        )
    return profile


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
