"""Shared proxy URL validation for protocol helpers."""

from __future__ import annotations

from urllib.parse import urlparse


def normalize_proxy_url(proxy_url: object) -> str | None:
    """Return one canonical proxy URL or ``None``."""
    if proxy_url is None:
        return None
    if not isinstance(proxy_url, str):
        raise ValueError("proxy_url must be a valid proxy URL with scheme and hostname")

    normalized_proxy_url = proxy_url.strip()
    if not normalized_proxy_url:
        raise ValueError("proxy_url must be a valid proxy URL with scheme and hostname")

    parsed = urlparse(normalized_proxy_url)
    try:
        proxy_port = parsed.port
    except ValueError as exc:
        raise ValueError("proxy_url must be a valid proxy URL with scheme and hostname") from exc

    if (
        parsed.scheme == ""
        or parsed.hostname is None
        or (proxy_port is not None and proxy_port < 1)
    ):
        raise ValueError("proxy_url must be a valid proxy URL with scheme and hostname")

    return normalized_proxy_url
