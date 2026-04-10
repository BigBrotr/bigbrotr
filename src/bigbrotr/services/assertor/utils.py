"""Pure helper utilities for the Assertor service."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, Final


if TYPE_CHECKING:
    from .configs import ProviderProfileKind0Content


CHECKPOINT_PARTS: Final[int] = 3
PROVIDER_PROFILE_SUBJECT_ID: Final[str] = "provider_profile"


def build_state_key(*, algorithm_id: str, kind: int, subject_id: str) -> str:
    """Build the canonical checkpoint key for one algorithm/kind/subject tuple."""
    return f"{algorithm_id}:{int(kind)}:{subject_id}"


def parse_state_key(state_key: str) -> tuple[str, int, str] | None:
    """Parse ``<algorithm_id>:<kind>:<subject_id>`` checkpoint keys."""
    parts = state_key.split(":", 2)
    if len(parts) != CHECKPOINT_PARTS:
        return None
    try:
        kind = int(parts[1])
    except ValueError:
        return None
    return parts[0], kind, parts[2]


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
