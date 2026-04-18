"""Unit tests for low-level ``bigbrotr.utils.keys`` loading."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from nostr_sdk import Keys

from bigbrotr.utils.keys import load_keys_from_env


VALID_HEX_KEY = (
    "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"  # pragma: allowlist secret
)
VALID_NSEC_KEY = (
    "nsec1vl029mgpspedva04g90vltkh6fvh240zqtv9k0t9af8935ke9laqsnlfe5"  # pragma: allowlist secret
)
INVALID_KEYS = [
    "invalid_key",
    "0" * 32,
    "0" * 128,
    "nsec1invalid",
    "npub1abc",
    "xyz" * 21 + "x",
]


class TestLoadKeysFromEnv:
    def test_missing_env_returns_none(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert load_keys_from_env("NOSTR_PRIVATE_KEY_MONITOR") is None

    def test_empty_env_returns_none(self) -> None:
        with patch.dict(os.environ, {"NOSTR_PRIVATE_KEY_MONITOR": ""}):
            assert load_keys_from_env("NOSTR_PRIVATE_KEY_MONITOR") is None

    def test_whitespace_env_returns_none(self) -> None:
        with patch.dict(os.environ, {"NOSTR_PRIVATE_KEY_MONITOR": "   "}):
            assert load_keys_from_env("NOSTR_PRIVATE_KEY_MONITOR") is None

    def test_valid_hex_key_returns_keys(self) -> None:
        with patch.dict(os.environ, {"NOSTR_PRIVATE_KEY_MONITOR": VALID_HEX_KEY}):
            keys = load_keys_from_env("NOSTR_PRIVATE_KEY_MONITOR")
        assert isinstance(keys, Keys)
        assert keys.secret_key().to_hex() == VALID_HEX_KEY

    def test_valid_nsec_key_returns_keys(self) -> None:
        with patch.dict(os.environ, {"NOSTR_PRIVATE_KEY_MONITOR": VALID_NSEC_KEY}):
            keys = load_keys_from_env("NOSTR_PRIVATE_KEY_MONITOR")
        assert isinstance(keys, Keys)
        assert len(keys.public_key().to_hex()) == 64

    @pytest.mark.parametrize("invalid_key", INVALID_KEYS)
    def test_invalid_key_raises(self, invalid_key: str) -> None:
        with (
            patch.dict(
                os.environ,
                {"NOSTR_PRIVATE_KEY_MONITOR": invalid_key},  # pragma: allowlist secret
            ),
            pytest.raises(BaseException),  # noqa: B017
        ):
            load_keys_from_env("NOSTR_PRIVATE_KEY_MONITOR")
