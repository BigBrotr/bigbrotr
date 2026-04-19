"""Pure helper utilities for the Assertor service."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, Final

from bigbrotr.nips.nip85 import TrustedProviderDeclaration


if TYPE_CHECKING:
    from .configs import AssertorConfig, ProviderProfileKind0Content


CHECKPOINT_PARTS: Final[int] = 3
PROVIDER_PROFILE_SUBJECT_ID: Final[str] = "provider_profile"
TRUSTED_PROVIDER_LIST_SUBJECT_ID: Final[str] = "trusted_provider_list"


def build_state_key(*, algorithm_id: str, kind: int, subject_id: str) -> str:
    """Build the canonical checkpoint key for one algorithm/kind/subject tuple."""
    return f"{algorithm_id}:{int(kind)}:{subject_id}"


def parse_state_key(state_key: str) -> tuple[str, int, str] | None:
    """Parse ``<algorithm_id>:<kind>:<subject_id>`` checkpoint keys."""
    if not isinstance(state_key, str):
        return None
    parts = state_key.split(":", 2)
    if len(parts) != CHECKPOINT_PARTS:
        return None
    kind_text = parts[1]
    try:
        kind = int(kind_text)
    except ValueError:
        return None
    if kind < 0 or str(kind) != kind_text:
        return None
    return parts[0], kind, parts[2]


def content_hash(content: Any) -> str:
    """Compute a stable SHA-256 hash for JSON-serializable publication content."""
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


def trusted_provider_declarations(
    *,
    config: AssertorConfig,
    service_pubkey: str,
) -> tuple[TrustedProviderDeclaration, ...]:
    """Build the canonical Kind 10040 declaration set for the active provider package."""
    relay_hint = config.trusted_provider_list.relay_hint or config.publishing.relays[0].url
    declarations = [
        TrustedProviderDeclaration(
            result_kind=int(result_kind),
            tag_name=tag_name,
            service_pubkey=service_pubkey,
            relay_hint=relay_hint,
        )
        for result_kind in sorted(config.selection.kinds)
        for tag_name in sorted(config.trusted_provider_list.tag_names)
    ]
    return tuple(declarations)
