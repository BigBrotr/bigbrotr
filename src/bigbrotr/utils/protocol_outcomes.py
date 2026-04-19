"""Normalization helpers for relay-level nostr-sdk outcomes."""

from __future__ import annotations

from collections.abc import Mapping

from bigbrotr.models.relay_url import normalize_relay_url


_HEX_32_TEXT_LENGTH = 64


def normalize_failed_relays(failed_relays: dict[str, str]) -> dict[str, str]:
    """Return failed relay outcomes in stable lexical relay-url order."""
    return {relay_url: failed_relays[relay_url] for relay_url in sorted(failed_relays)}


def normalize_output_relay_url(value: object) -> str:
    """Return one SDK relay output as a canonical relay URL string."""
    relay_url = str(value)
    if not relay_url:
        raise ValueError("relay output contained an empty relay URL")

    try:
        canonical = normalize_relay_url(relay_url, allow_local=True)
    except ValueError as exc:
        raise ValueError(f"relay output contained invalid relay URL: {relay_url!r}") from exc

    if canonical != relay_url:
        raise ValueError(f"relay output contained non-canonical relay URL: {relay_url!r}")

    return relay_url


def normalize_output_event_id(value: object) -> str:
    """Return one SDK event output id as a canonical 32-byte hex string."""
    event_id = str(value)
    if len(event_id) != _HEX_32_TEXT_LENGTH:
        raise ValueError(f"event output contained invalid event id: {event_id!r}")

    try:
        bytes.fromhex(event_id)
    except ValueError as exc:
        raise ValueError(f"event output contained invalid event id: {event_id!r}") from exc

    return event_id.lower()


def normalize_relay_outcomes(output: object) -> tuple[tuple[str, ...], dict[str, str]]:
    """Normalize one SDK connect/send output into canonical relay outcomes."""
    success_raw = getattr(output, "success", ())
    try:
        successful_relays = tuple(
            sorted({normalize_output_relay_url(relay_url) for relay_url in success_raw})
        )
    except TypeError as exc:
        raise ValueError("relay output success entries must be iterable") from exc

    failed_raw = getattr(output, "failed", {})
    if not isinstance(failed_raw, Mapping):
        raise ValueError("relay output failed entries must be a mapping")

    failed_relays = {
        normalize_output_relay_url(relay_url): str(error) for relay_url, error in failed_raw.items()
    }
    return successful_relays, normalize_failed_relays(failed_relays)
