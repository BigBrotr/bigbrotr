"""Pure helper utilities for the Assertor service."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, Final


if TYPE_CHECKING:
    from .configs import ProviderProfileKind0Content


LEGACY_CHECKPOINT_PREFIXES: Final[tuple[str, ...]] = ("user:", "event:")
PROVIDER_PROFILE_SUBJECT_ID: Final[str] = "provider_profile"
V2_CHECKPOINT_PARTS: Final[int] = 4


def build_state_key(*, algorithm_id: str, kind: int, subject_id: str) -> str:
    """Build the v2 checkpoint key for one algorithm/kind/subject tuple."""
    return f"v2:{algorithm_id}:{int(kind)}:{subject_id}"


def parse_v2_checkpoint_key(state_key: str) -> tuple[str, int, str] | None:
    """Parse ``v2:<algorithm_id>:<kind>:<subject_id>`` checkpoint keys."""
    parts = state_key.split(":", 3)
    if len(parts) != V2_CHECKPOINT_PARTS or parts[0] != "v2":
        return None
    try:
        kind = int(parts[2])
    except ValueError:
        return None
    return parts[1], kind, parts[3]


def is_legacy_checkpoint_key(state_key: str) -> bool:
    """Return whether a checkpoint key belongs to the pre-v2 assertor contract."""
    return state_key.startswith(LEGACY_CHECKPOINT_PREFIXES)


def content_hash(content: dict[str, Any]) -> str:
    """Compute a stable SHA-256 hash for JSON profile content."""
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def provider_profile_content(
    *,
    algorithm_id: str,
    kind0_content: ProviderProfileKind0Content,
) -> dict[str, Any]:
    """Return the effective Kind 0 content for the provider profile."""
    content: dict[str, Any] = {
        "name": kind0_content.name,
        "about": kind0_content.about,
        "website": kind0_content.website,
        "algorithm_id": algorithm_id,
    }

    optional_fields = {
        "picture": kind0_content.picture,
        "nip05": kind0_content.nip05,
        "banner": kind0_content.banner,
        "lud16": kind0_content.lud16,
    }
    content.update({key: value for key, value in optional_fields.items() if value is not None})

    for key, value in kind0_content.extra_fields.items():
        if key and value is not None and key not in content:
            content[key] = value

    return content
