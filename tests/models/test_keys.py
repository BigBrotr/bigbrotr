"""Tests for models.keys module."""

import os
import pytest
from unittest.mock import patch

from models import Keys


# Valid secp256k1 test key (DO NOT USE IN PRODUCTION)
VALID_HEX_KEY = "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"
VALID_NSEC_KEY = "nsec1vl029mgpspedva04g90vltkh6fvh240zqtv9k0t9af8935ke9laqsnlfe5"


class TestFromEnv:
    """Keys.from_env() class method."""

    def test_returns_none_when_not_set(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PRIVATE_KEY", None)
            assert Keys.from_env() is None

    def test_returns_none_when_empty(self):
        with patch.dict(os.environ, {"PRIVATE_KEY": ""}):
            assert Keys.from_env() is None

    def test_with_valid_hex_key(self):
        with patch.dict(os.environ, {"PRIVATE_KEY": VALID_HEX_KEY}):
            result = Keys.from_env()
        assert result is not None
        assert isinstance(result, Keys)

    def test_with_custom_env_var(self):
        with patch.dict(os.environ, {"CUSTOM_KEY": VALID_HEX_KEY}):
            result = Keys.from_env("CUSTOM_KEY")
        assert result is not None

    def test_with_invalid_key(self):
        with patch.dict(os.environ, {"PRIVATE_KEY": "invalid_key"}):
            with pytest.raises(ValueError, match="Invalid PRIVATE_KEY"):
                Keys.from_env()

    def test_with_short_key(self):
        with patch.dict(os.environ, {"PRIVATE_KEY": "0" * 32}):
            with pytest.raises(ValueError, match="Invalid PRIVATE_KEY"):
                Keys.from_env()

    def test_with_nsec_bech32_key(self):
        with patch.dict(os.environ, {"PRIVATE_KEY": VALID_NSEC_KEY}):
            result = Keys.from_env()
        assert result is not None
        assert isinstance(result, Keys)


class TestInheritance:
    """Keys extends NostrKeys."""

    def test_has_public_key(self):
        with patch.dict(os.environ, {"PRIVATE_KEY": VALID_HEX_KEY}):
            keys = Keys.from_env()
        assert keys is not None
        assert keys.public_key() is not None

    def test_has_secret_key(self):
        with patch.dict(os.environ, {"PRIVATE_KEY": VALID_HEX_KEY}):
            keys = Keys.from_env()
        assert keys is not None
        assert keys.secret_key() is not None
