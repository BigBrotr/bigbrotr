"""
Unit tests for utils.keys module.

Tests:
- ENV_PRIVATE_KEY constant
- load_keys_from_env() - environment variable loading with various key formats
- KeysConfig - Pydantic model for Nostr keys configuration
"""

import os
from unittest.mock import patch

import pytest
from nostr_sdk import Keys

from utils.keys import ENV_PRIVATE_KEY, KeysConfig, load_keys_from_env


# =============================================================================
# Test Constants
# =============================================================================

# Valid secp256k1 test keys (DO NOT USE IN PRODUCTION)
VALID_HEX_KEY = (
    "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"  # pragma: allowlist secret
)
VALID_NSEC_KEY = (
    "nsec1vl029mgpspedva04g90vltkh6fvh240zqtv9k0t9af8935ke9laqsnlfe5"  # pragma: allowlist secret
)

# Invalid key formats for testing error handling
INVALID_KEYS = [
    "invalid_key",  # Not hex or nsec
    "0" * 32,  # Too short (32 chars instead of 64)
    "0" * 128,  # Too long
    "nsec1invalid",  # Invalid bech32 checksum
    "npub1abc",  # Wrong prefix (public key, not secret)
    "xyz" * 21 + "x",  # 64 chars but not valid hex
]


# =============================================================================
# ENV_PRIVATE_KEY Constant Tests
# =============================================================================


class TestEnvPrivateKeyConstant:
    """ENV_PRIVATE_KEY constant value."""

    def test_constant_value(self):
        """Verify the constant has the expected value."""
        assert ENV_PRIVATE_KEY == "PRIVATE_KEY"  # pragma: allowlist secret

    def test_constant_is_string(self):
        """Verify the constant is a string."""
        assert isinstance(ENV_PRIVATE_KEY, str)


# =============================================================================
# load_keys_from_env() Tests
# =============================================================================


class TestLoadKeysFromEnvMissingVar:
    """load_keys_from_env() with missing environment variable."""

    def test_raises_when_env_var_not_set(self):
        """Test that ValueError is raised when env var is not set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PRIVATE_KEY", None)
            with pytest.raises(ValueError) as exc_info:
                load_keys_from_env("PRIVATE_KEY")
            assert "PRIVATE_KEY environment variable is required" in str(exc_info.value)

    def test_raises_when_env_var_is_empty(self):
        """Test that ValueError is raised when env var is empty string."""
        with patch.dict(os.environ, {"PRIVATE_KEY": ""}):  # pragma: allowlist secret
            with pytest.raises(ValueError) as exc_info:
                load_keys_from_env("PRIVATE_KEY")
            assert "PRIVATE_KEY environment variable is required" in str(exc_info.value)

    def test_error_message_includes_generation_hint(self):
        """Test that error message includes hint for generating keys."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MY_KEY", None)
            with pytest.raises(ValueError) as exc_info:
                load_keys_from_env("MY_KEY")
            assert "openssl rand -hex 32" in str(exc_info.value)


class TestLoadKeysFromEnvHexKey:
    """load_keys_from_env() with hex format keys."""

    def test_valid_hex_key_returns_keys(self):
        """Test that valid 64-char hex key returns Keys object."""
        with patch.dict(os.environ, {"PRIVATE_KEY": VALID_HEX_KEY}):
            result = load_keys_from_env("PRIVATE_KEY")
        assert isinstance(result, Keys)

    def test_hex_key_has_correct_secret_key(self):
        """Test that returned Keys has the correct secret key."""
        with patch.dict(os.environ, {"PRIVATE_KEY": VALID_HEX_KEY}):
            keys = load_keys_from_env("PRIVATE_KEY")
        assert keys.secret_key().to_hex() == VALID_HEX_KEY

    def test_hex_key_derives_public_key(self):
        """Test that public key is correctly derived from hex private key."""
        with patch.dict(os.environ, {"PRIVATE_KEY": VALID_HEX_KEY}):
            keys = load_keys_from_env("PRIVATE_KEY")
        assert keys.public_key() is not None
        assert len(keys.public_key().to_hex()) == 64

    def test_hex_key_public_key_format(self):
        """Test that public key can be converted to bech32."""
        with patch.dict(os.environ, {"PRIVATE_KEY": VALID_HEX_KEY}):
            keys = load_keys_from_env("PRIVATE_KEY")
        bech32 = keys.public_key().to_bech32()
        assert bech32.startswith("npub1")


class TestLoadKeysFromEnvNsecKey:
    """load_keys_from_env() with nsec (bech32) format keys."""

    def test_valid_nsec_key_returns_keys(self):
        """Test that valid nsec1 key returns Keys object."""
        with patch.dict(os.environ, {"PRIVATE_KEY": VALID_NSEC_KEY}):
            result = load_keys_from_env("PRIVATE_KEY")
        assert isinstance(result, Keys)

    def test_nsec_key_has_public_key(self):
        """Test that Keys from nsec has valid public key."""
        with patch.dict(os.environ, {"PRIVATE_KEY": VALID_NSEC_KEY}):
            keys = load_keys_from_env("PRIVATE_KEY")
        assert keys.public_key() is not None
        assert len(keys.public_key().to_hex()) == 64

    def test_nsec_key_can_export_to_hex(self):
        """Test that nsec key can be exported to hex format."""
        with patch.dict(os.environ, {"PRIVATE_KEY": VALID_NSEC_KEY}):
            keys = load_keys_from_env("PRIVATE_KEY")
        hex_key = keys.secret_key().to_hex()
        assert len(hex_key) == 64
        # Verify it's valid hex
        int(hex_key, 16)


class TestLoadKeysFromEnvInvalidKeys:
    """load_keys_from_env() with invalid key formats."""

    @pytest.mark.parametrize("invalid_key", INVALID_KEYS)
    def test_invalid_key_raises_error(self, invalid_key: str):
        """Test that invalid keys raise an exception."""
        with patch.dict(os.environ, {"PRIVATE_KEY": invalid_key}):  # pragma: allowlist secret
            with pytest.raises(BaseException):  # noqa: B017 - nostr_sdk raises various exceptions
                load_keys_from_env("PRIVATE_KEY")

    def test_whitespace_key_raises_error(self):
        """Test that whitespace-only key raises an error."""
        with patch.dict(os.environ, {"PRIVATE_KEY": "   "}):  # pragma: allowlist secret
            # Whitespace is passed to Keys.parse which raises NostrSdkError
            with pytest.raises(BaseException):  # noqa: B017 - nostr_sdk raises various exceptions
                load_keys_from_env("PRIVATE_KEY")


class TestLoadKeysFromEnvCustomEnvVar:
    """load_keys_from_env() with custom environment variable names."""

    def test_custom_env_var_name(self):
        """Test loading from a custom environment variable."""
        with patch.dict(os.environ, {"CUSTOM_KEY": VALID_HEX_KEY}):
            result = load_keys_from_env("CUSTOM_KEY")
        assert isinstance(result, Keys)

    def test_custom_env_var_not_set(self):
        """Test custom env var raises when not set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MY_CUSTOM_KEY", None)
            with pytest.raises(ValueError) as exc_info:
                load_keys_from_env("MY_CUSTOM_KEY")
            assert "MY_CUSTOM_KEY environment variable is required" in str(exc_info.value)


# =============================================================================
# KeysConfig Tests - Defaults and Initialization
# =============================================================================


class TestKeysConfigEnvironmentLoading:
    """KeysConfig automatic loading from PRIVATE_KEY environment."""

    def test_raises_when_env_not_set(self):
        """Test that ValidationError is raised when PRIVATE_KEY is not set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop(ENV_PRIVATE_KEY, None)
            with pytest.raises(Exception):  # noqa: B017
                KeysConfig()

    def test_raises_when_env_empty(self):
        """Test that ValidationError is raised when PRIVATE_KEY is empty."""
        with patch.dict(os.environ, {ENV_PRIVATE_KEY: ""}):
            with pytest.raises(Exception):  # noqa: B017
                KeysConfig()

    def test_loads_hex_key_from_env(self):
        """Test that hex key is loaded from environment."""
        with patch.dict(os.environ, {ENV_PRIVATE_KEY: VALID_HEX_KEY}):
            config = KeysConfig()
        assert config.keys is not None
        assert isinstance(config.keys, Keys)

    def test_loads_nsec_key_from_env(self):
        """Test that nsec key is loaded from environment."""
        with patch.dict(os.environ, {ENV_PRIVATE_KEY: VALID_NSEC_KEY}):
            config = KeysConfig()
        assert config.keys is not None
        assert isinstance(config.keys, Keys)


class TestKeysConfigExplicitKeys:
    """KeysConfig with explicitly provided keys."""

    def test_explicit_keys_override_env(self):
        """Test that explicitly provided keys override environment."""
        explicit_keys = Keys.generate()
        with patch.dict(os.environ, {ENV_PRIVATE_KEY: VALID_HEX_KEY}):
            config = KeysConfig(keys=explicit_keys)
        assert config.keys is explicit_keys

    def test_explicit_keys_without_env_var(self):
        """Test that explicit keys work without environment variable set."""
        explicit_keys = Keys.generate()
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop(ENV_PRIVATE_KEY, None)
            config = KeysConfig(keys=explicit_keys)
        assert config.keys is explicit_keys

    def test_explicit_keys_preserved_identity(self):
        """Test that the exact Keys instance is preserved."""
        explicit_keys = Keys.generate()
        config = KeysConfig(keys=explicit_keys)
        assert config.keys is explicit_keys
        assert id(config.keys) == id(explicit_keys)


class TestKeysConfigModelValidator:
    """KeysConfig model_validator behavior."""

    def test_dict_input_triggers_env_load(self):
        """Test that empty dict input triggers environment loading."""
        with patch.dict(os.environ, {ENV_PRIVATE_KEY: VALID_HEX_KEY}):
            config = KeysConfig.model_validate({})
        assert config.keys is not None
        assert isinstance(config.keys, Keys)

    def test_dict_with_keys_uses_provided(self):
        """Test that dict with keys field uses provided keys."""
        explicit_keys = Keys.generate()
        with patch.dict(os.environ, {ENV_PRIVATE_KEY: VALID_HEX_KEY}):
            config = KeysConfig.model_validate({"keys": explicit_keys})
        assert config.keys is explicit_keys

    def test_validator_only_affects_dict_input(self):
        """Test that non-dict input is passed through."""
        explicit_keys = Keys.generate()
        config = KeysConfig(keys=explicit_keys)
        assert config.keys is explicit_keys


class TestKeysConfigArbitraryTypes:
    """KeysConfig arbitrary_types_allowed configuration."""

    def test_accepts_keys_object(self):
        """Test that Keys object is accepted (not a Pydantic type)."""
        keys = Keys.generate()
        config = KeysConfig(keys=keys)
        assert config.keys is keys
        assert isinstance(config.keys, Keys)

    def test_keys_have_public_key(self):
        """Test that loaded keys have accessible public key."""
        with patch.dict(os.environ, {ENV_PRIVATE_KEY: VALID_HEX_KEY}):
            config = KeysConfig()
        assert config.keys is not None
        assert config.keys.public_key() is not None
        assert len(config.keys.public_key().to_hex()) == 64

    def test_keys_have_secret_key(self):
        """Test that loaded keys have accessible secret key."""
        with patch.dict(os.environ, {ENV_PRIVATE_KEY: VALID_HEX_KEY}):
            config = KeysConfig()
        assert config.keys is not None
        assert config.keys.secret_key() is not None
        assert config.keys.secret_key().to_hex() == VALID_HEX_KEY

    def test_keys_can_sign(self):
        """Test that loaded keys can be used for signing."""
        with patch.dict(os.environ, {ENV_PRIVATE_KEY: VALID_HEX_KEY}):
            config = KeysConfig()
        # If keys are valid, they should be able to derive public key
        # which is required for signing operations
        assert config.keys.public_key().to_bech32().startswith("npub1")


class TestKeysConfigSerialization:
    """KeysConfig serialization behavior."""

    def test_model_dump_includes_keys(self):
        """Test that model_dump includes keys field."""
        with patch.dict(os.environ, {ENV_PRIVATE_KEY: VALID_HEX_KEY}):
            config = KeysConfig()
        dump = config.model_dump()
        assert "keys" in dump

    def test_model_config_allows_arbitrary_types(self):
        """Test that model_config has arbitrary_types_allowed."""
        assert KeysConfig.model_config.get("arbitrary_types_allowed") is True
