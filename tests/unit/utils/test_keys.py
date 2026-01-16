"""
Unit tests for utils.keys module.

Tests:
- load_keys_from_env() - environment variable loading
- KeysConfig - Pydantic model for Nostr keys configuration
"""

import os
from unittest.mock import patch

import pytest
from nostr_sdk import Keys

from utils.keys import ENV_PRIVATE_KEY, KeysConfig, load_keys_from_env


# Valid secp256k1 test key (DO NOT USE IN PRODUCTION)
VALID_HEX_KEY = (
    "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"  # pragma: allowlist secret
)
VALID_NSEC_KEY = (
    "nsec1vl029mgpspedva04g90vltkh6fvh240zqtv9k0t9af8935ke9laqsnlfe5"  # pragma: allowlist secret
)


class TestLoadKeysFromEnv:
    """load_keys_from_env() function."""

    def test_returns_none_when_not_set(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PRIVATE_KEY", None)
            assert load_keys_from_env("PRIVATE_KEY") is None

    def test_returns_none_when_empty(self):
        with patch.dict(os.environ, {"PRIVATE_KEY": ""}):  # pragma: allowlist secret
            assert load_keys_from_env("PRIVATE_KEY") is None

    def test_with_valid_hex_key(self):
        with patch.dict(os.environ, {"PRIVATE_KEY": VALID_HEX_KEY}):
            result = load_keys_from_env("PRIVATE_KEY")
        assert result is not None
        assert isinstance(result, Keys)

    def test_with_custom_env_var(self):
        with patch.dict(os.environ, {"CUSTOM_KEY": VALID_HEX_KEY}):
            result = load_keys_from_env("CUSTOM_KEY")
        assert result is not None

    def test_with_invalid_key(self):
        with (
            patch.dict(os.environ, {"PRIVATE_KEY": "invalid_key"}),  # pragma: allowlist secret
            pytest.raises(BaseException),  # noqa: B017
        ):
            load_keys_from_env("PRIVATE_KEY")

    def test_with_short_key(self):
        with (
            patch.dict(os.environ, {"PRIVATE_KEY": "0" * 32}),  # pragma: allowlist secret
            pytest.raises(BaseException),  # noqa: B017
        ):
            load_keys_from_env("PRIVATE_KEY")

    def test_with_nsec_bech32_key(self):
        with patch.dict(os.environ, {"PRIVATE_KEY": VALID_NSEC_KEY}):
            result = load_keys_from_env("PRIVATE_KEY")
        assert result is not None
        assert isinstance(result, Keys)

    def test_returns_keys_with_public_key(self):
        with patch.dict(os.environ, {"PRIVATE_KEY": VALID_HEX_KEY}):
            keys = load_keys_from_env("PRIVATE_KEY")
        assert keys is not None
        assert keys.public_key() is not None
        assert len(keys.public_key().to_hex()) == 64

    def test_returns_keys_with_secret_key(self):
        with patch.dict(os.environ, {"PRIVATE_KEY": VALID_HEX_KEY}):
            keys = load_keys_from_env("PRIVATE_KEY")
        assert keys is not None
        assert keys.secret_key() is not None
        assert keys.secret_key().to_hex() == VALID_HEX_KEY


# =============================================================================
# KeysConfig Tests
# =============================================================================


class TestKeysConfigDefaults:
    """KeysConfig default values."""

    def test_keys_none_when_env_not_set(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop(ENV_PRIVATE_KEY, None)
            config = KeysConfig()
        assert config.keys is None

    def test_env_private_key_constant(self):
        assert ENV_PRIVATE_KEY == "PRIVATE_KEY"  # pragma: allowlist secret


class TestKeysConfigFromEnv:
    """KeysConfig loads keys from environment."""

    def test_loads_hex_key_from_env(self):
        with patch.dict(os.environ, {ENV_PRIVATE_KEY: VALID_HEX_KEY}):
            config = KeysConfig()
        assert config.keys is not None
        assert isinstance(config.keys, Keys)

    def test_loads_nsec_key_from_env(self):
        with patch.dict(os.environ, {ENV_PRIVATE_KEY: VALID_NSEC_KEY}):
            config = KeysConfig()
        assert config.keys is not None
        assert isinstance(config.keys, Keys)

    def test_empty_env_results_in_none(self):
        with patch.dict(os.environ, {ENV_PRIVATE_KEY: ""}):
            config = KeysConfig()
        assert config.keys is None


class TestKeysConfigExplicitKeys:
    """KeysConfig with explicitly provided keys."""

    def test_explicit_keys_override_env(self):
        explicit_keys = Keys.generate()
        with patch.dict(os.environ, {ENV_PRIVATE_KEY: VALID_HEX_KEY}):
            config = KeysConfig(keys=explicit_keys)
        assert config.keys is explicit_keys

    def test_explicit_none_when_env_set(self):
        with patch.dict(os.environ, {ENV_PRIVATE_KEY: VALID_HEX_KEY}):
            config = KeysConfig(keys=None)
        # When keys=None is explicit, env is still loaded (model_validator runs before)
        # This is the expected behavior
        assert config.keys is None


class TestKeysConfigModelValidator:
    """KeysConfig model_validator behavior."""

    def test_dict_input_triggers_env_load(self):
        with patch.dict(os.environ, {ENV_PRIVATE_KEY: VALID_HEX_KEY}):
            config = KeysConfig.model_validate({})
        assert config.keys is not None
        assert isinstance(config.keys, Keys)

    def test_dict_with_keys_uses_provided(self):
        explicit_keys = Keys.generate()
        with patch.dict(os.environ, {ENV_PRIVATE_KEY: VALID_HEX_KEY}):
            config = KeysConfig.model_validate({"keys": explicit_keys})
        assert config.keys is explicit_keys


class TestKeysConfigArbitraryTypes:
    """KeysConfig allows arbitrary types (Keys is not a Pydantic type)."""

    def test_accepts_keys_object(self):
        keys = Keys.generate()
        config = KeysConfig(keys=keys)
        assert config.keys is keys
        assert isinstance(config.keys, Keys)

    def test_keys_have_public_key(self):
        with patch.dict(os.environ, {ENV_PRIVATE_KEY: VALID_HEX_KEY}):
            config = KeysConfig()
        assert config.keys is not None
        assert config.keys.public_key() is not None
        assert len(config.keys.public_key().to_hex()) == 64

    def test_keys_have_secret_key(self):
        with patch.dict(os.environ, {ENV_PRIVATE_KEY: VALID_HEX_KEY}):
            config = KeysConfig()
        assert config.keys is not None
        assert config.keys.secret_key() is not None
        assert config.keys.secret_key().to_hex() == VALID_HEX_KEY
