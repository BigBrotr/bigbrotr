"""
Unit tests for models.keys module.

Tests:
- Keys.generate() - random key generation
- Keys.parse() - parsing from hex/nsec
- Keys.from_mnemonic() - NIP-06 derivation
- Keys.from_env() - environment variable loading
- Public key derivation
- Invalid key handling
"""

import os
from unittest.mock import patch

import pytest

from models import Keys


# Valid secp256k1 test key (DO NOT USE IN PRODUCTION)
VALID_HEX_KEY = "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"
VALID_NSEC_KEY = "nsec1vl029mgpspedva04g90vltkh6fvh240zqtv9k0t9af8935ke9laqsnlfe5"
# BIP-39 test mnemonic (DO NOT USE IN PRODUCTION)
VALID_MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"


class TestGenerate:
    """Keys.generate() class method."""

    def test_returns_keys_instance(self):
        keys = Keys.generate()
        assert isinstance(keys, Keys)

    def test_generates_unique_keys(self):
        keys1 = Keys.generate()
        keys2 = Keys.generate()
        assert keys1.public_key().to_hex() != keys2.public_key().to_hex()

    def test_has_public_key(self):
        keys = Keys.generate()
        pubkey = keys.public_key()
        assert pubkey is not None
        assert len(pubkey.to_hex()) == 64

    def test_has_secret_key(self):
        keys = Keys.generate()
        secret = keys.secret_key()
        assert secret is not None
        assert len(secret.to_hex()) == 64


class TestParse:
    """Keys.parse() class method."""

    def test_parse_hex_key(self):
        keys = Keys.parse(VALID_HEX_KEY)
        assert isinstance(keys, Keys)
        assert keys.secret_key().to_hex() == VALID_HEX_KEY

    def test_parse_nsec_key(self):
        keys = Keys.parse(VALID_NSEC_KEY)
        assert isinstance(keys, Keys)
        assert keys.secret_key().to_bech32() == VALID_NSEC_KEY

    def test_parse_invalid_key_raises(self):
        with pytest.raises(Exception):
            Keys.parse("invalid_key")

    def test_parse_short_key_raises(self):
        with pytest.raises(Exception):
            Keys.parse("0" * 32)


class TestFromMnemonic:
    """Keys.from_mnemonic() class method (NIP-06)."""

    def test_derives_keys_from_mnemonic(self):
        keys = Keys.from_mnemonic(VALID_MNEMONIC)
        assert isinstance(keys, Keys)
        # NIP-06 standard derivation should produce deterministic keys
        assert keys.public_key() is not None

    def test_same_mnemonic_produces_same_keys(self):
        keys1 = Keys.from_mnemonic(VALID_MNEMONIC)
        keys2 = Keys.from_mnemonic(VALID_MNEMONIC)
        assert keys1.public_key().to_hex() == keys2.public_key().to_hex()

    def test_passphrase_produces_different_keys(self):
        keys_no_pass = Keys.from_mnemonic(VALID_MNEMONIC)
        keys_with_pass = Keys.from_mnemonic(VALID_MNEMONIC, passphrase="secret")
        assert keys_no_pass.public_key().to_hex() != keys_with_pass.public_key().to_hex()

    def test_invalid_mnemonic_raises(self):
        with pytest.raises(Exception):
            Keys.from_mnemonic("invalid mnemonic words")


class TestFromEnv:
    """Keys.from_env() class method."""

    def test_returns_none_when_not_set(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PRIVATE_KEY", None)
            assert Keys.from_env("PRIVATE_KEY") is None

    def test_returns_none_when_empty(self):
        with patch.dict(os.environ, {"PRIVATE_KEY": ""}):
            assert Keys.from_env("PRIVATE_KEY") is None

    def test_with_valid_hex_key(self):
        with patch.dict(os.environ, {"PRIVATE_KEY": VALID_HEX_KEY}):
            result = Keys.from_env("PRIVATE_KEY")
        assert result is not None
        assert isinstance(result, Keys)

    def test_with_custom_env_var(self):
        with patch.dict(os.environ, {"CUSTOM_KEY": VALID_HEX_KEY}):
            result = Keys.from_env("CUSTOM_KEY")
        assert result is not None

    def test_with_invalid_key(self):
        with (
            patch.dict(os.environ, {"PRIVATE_KEY": "invalid_key"}),
            pytest.raises(Exception),
        ):
            Keys.from_env("PRIVATE_KEY")

    def test_with_short_key(self):
        with (
            patch.dict(os.environ, {"PRIVATE_KEY": "0" * 32}),
            pytest.raises(Exception),
        ):
            Keys.from_env("PRIVATE_KEY")

    def test_with_nsec_bech32_key(self):
        with patch.dict(os.environ, {"PRIVATE_KEY": VALID_NSEC_KEY}):
            result = Keys.from_env("PRIVATE_KEY")
        assert result is not None
        assert isinstance(result, Keys)


class TestDelegation:
    """Keys delegates to NostrKeys."""

    def test_has_public_key(self):
        with patch.dict(os.environ, {"PRIVATE_KEY": VALID_HEX_KEY}):
            keys = Keys.from_env("PRIVATE_KEY")
        assert keys is not None
        assert keys.public_key() is not None

    def test_has_secret_key(self):
        with patch.dict(os.environ, {"PRIVATE_KEY": VALID_HEX_KEY}):
            keys = Keys.from_env("PRIVATE_KEY")
        assert keys is not None
        assert keys.secret_key() is not None
