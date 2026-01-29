"""
Unit tests for utils.yaml module.

Tests:
- load_yaml() - YAML configuration file loading
  - Valid YAML files
  - Empty files
  - File not found
  - Path handling
  - Special YAML values
  - Invalid YAML syntax
"""

from pathlib import Path

import pytest
import yaml

from utils.yaml import load_yaml


# =============================================================================
# Valid YAML Files Tests
# =============================================================================


class TestLoadYamlSimpleFiles:
    """load_yaml() with simple YAML files."""

    def test_simple_key_value(self, tmp_path: Path):
        """Loads simple key-value pairs."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("name: test\ncount: 42\n")

        result = load_yaml(str(yaml_file))
        assert result == {"name": "test", "count": 42}

    def test_single_key(self, tmp_path: Path):
        """Loads single key-value."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("key: value\n")

        result = load_yaml(str(yaml_file))
        assert result == {"key": "value"}

    def test_multiple_types(self, tmp_path: Path):
        """Loads various data types."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(
            """
name: bigbrotr
version: 1.0
enabled: true
timeout: 30.5
"""
        )

        result = load_yaml(str(yaml_file))
        assert result["name"] == "bigbrotr"
        assert result["version"] == 1.0
        assert result["enabled"] is True
        assert result["timeout"] == 30.5


class TestLoadYamlNestedStructures:
    """load_yaml() with nested YAML structures."""

    def test_nested_dict(self, tmp_path: Path):
        """Loads nested dictionary structures."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(
            """
database:
  host: localhost
  port: 5432
  credentials:
    username: admin
    password: secret
"""
        )

        result = load_yaml(str(yaml_file))
        assert result["database"]["host"] == "localhost"
        assert result["database"]["port"] == 5432
        assert result["database"]["credentials"]["username"] == "admin"
        assert result["database"]["credentials"]["password"] == "secret"  # pragma: allowlist secret

    def test_deeply_nested(self, tmp_path: Path):
        """Loads deeply nested structures."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(
            """
level1:
  level2:
    level3:
      level4:
        value: deep
"""
        )

        result = load_yaml(str(yaml_file))
        assert result["level1"]["level2"]["level3"]["level4"]["value"] == "deep"


class TestLoadYamlLists:
    """load_yaml() with list structures."""

    def test_simple_list(self, tmp_path: Path):
        """Loads simple list."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(
            """
relays:
  - wss://relay1.example.com
  - wss://relay2.example.com
  - wss://relay3.example.com
"""
        )

        result = load_yaml(str(yaml_file))
        assert result["relays"] == [
            "wss://relay1.example.com",
            "wss://relay2.example.com",
            "wss://relay3.example.com",
        ]

    def test_list_of_dicts(self, tmp_path: Path):
        """Loads list of dictionaries."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(
            """
servers:
  - name: server1
    host: 10.0.0.1
  - name: server2
    host: 10.0.0.2
"""
        )

        result = load_yaml(str(yaml_file))
        assert len(result["servers"]) == 2
        assert result["servers"][0]["name"] == "server1"
        assert result["servers"][1]["host"] == "10.0.0.2"

    def test_inline_list(self, tmp_path: Path):
        """Loads inline list syntax."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("tags: [nostr, relay, bigbrotr]\n")

        result = load_yaml(str(yaml_file))
        assert result["tags"] == ["nostr", "relay", "bigbrotr"]


class TestLoadYamlMixedStructures:
    """load_yaml() with mixed structures."""

    def test_mixed_types_and_structures(self, tmp_path: Path):
        """Loads complex mixed structure."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(
            """
name: bigbrotr
version: 1.0
enabled: true
timeout: 30.5
tags:
  - nostr
  - relay
settings:
  debug: false
  networks:
    - clearnet
    - tor
"""
        )

        result = load_yaml(str(yaml_file))
        assert result["name"] == "bigbrotr"
        assert result["version"] == 1.0
        assert result["enabled"] is True
        assert result["timeout"] == 30.5
        assert result["tags"] == ["nostr", "relay"]
        assert result["settings"]["debug"] is False
        assert result["settings"]["networks"] == ["clearnet", "tor"]


# =============================================================================
# Empty Files Tests
# =============================================================================


class TestLoadYamlEmptyFiles:
    """load_yaml() with empty files."""

    def test_empty_file_returns_empty_dict(self, tmp_path: Path):
        """Empty file returns empty dict."""
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("")

        result = load_yaml(str(yaml_file))
        assert result == {}

    def test_whitespace_only_returns_empty_dict(self, tmp_path: Path):
        """Whitespace-only file returns empty dict."""
        yaml_file = tmp_path / "whitespace.yaml"
        yaml_file.write_text("   \n\n   \n")

        result = load_yaml(str(yaml_file))
        assert result == {}

    def test_comments_only_returns_empty_dict(self, tmp_path: Path):
        """Comments-only file returns empty dict."""
        yaml_file = tmp_path / "comments.yaml"
        yaml_file.write_text("# This is a comment\n# Another comment\n")

        result = load_yaml(str(yaml_file))
        assert result == {}

    def test_document_marker_only(self, tmp_path: Path):
        """Document markers only returns empty dict."""
        yaml_file = tmp_path / "markers.yaml"
        yaml_file.write_text("---\n...\n")

        result = load_yaml(str(yaml_file))
        assert result == {}


# =============================================================================
# File Not Found Tests
# =============================================================================


class TestLoadYamlFileNotFound:
    """load_yaml() with non-existent files."""

    def test_raises_file_not_found(self):
        """Raises FileNotFoundError for non-existent file."""
        with pytest.raises(FileNotFoundError) as exc_info:
            load_yaml("/nonexistent/path/config.yaml")

        assert "Config file not found" in str(exc_info.value)
        assert "/nonexistent/path/config.yaml" in str(exc_info.value)

    def test_raises_for_missing_file_in_existing_dir(self, tmp_path: Path):
        """Raises FileNotFoundError for missing file in existing directory."""
        with pytest.raises(FileNotFoundError) as exc_info:
            load_yaml(str(tmp_path / "missing.yaml"))

        assert "Config file not found" in str(exc_info.value)

    def test_error_includes_path(self):
        """Error message includes the path that was not found."""
        path = "/some/specific/path/config.yaml"
        with pytest.raises(FileNotFoundError) as exc_info:
            load_yaml(path)

        assert path in str(exc_info.value)


# =============================================================================
# Path Handling Tests
# =============================================================================


class TestLoadYamlPathHandling:
    """load_yaml() path handling."""

    def test_string_path(self, tmp_path: Path):
        """Accepts string path."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("key: value\n")

        result = load_yaml(str(yaml_file))
        assert result == {"key": "value"}

    def test_absolute_path(self, tmp_path: Path):
        """Accepts absolute path."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("key: value\n")

        result = load_yaml(str(yaml_file.absolute()))
        assert result == {"key": "value"}

    def test_yml_extension(self, tmp_path: Path):
        """Accepts .yml extension."""
        yaml_file = tmp_path / "config.yml"
        yaml_file.write_text("key: value\n")

        result = load_yaml(str(yaml_file))
        assert result == {"key": "value"}

    def test_no_extension(self, tmp_path: Path):
        """Accepts file without extension."""
        yaml_file = tmp_path / "config"
        yaml_file.write_text("key: value\n")

        result = load_yaml(str(yaml_file))
        assert result == {"key": "value"}


# =============================================================================
# Special YAML Values Tests
# =============================================================================


class TestLoadYamlSpecialValues:
    """load_yaml() handles special YAML values."""

    def test_null_value(self, tmp_path: Path):
        """Parses null value."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("value: null\n")

        result = load_yaml(str(yaml_file))
        assert result["value"] is None

    def test_tilde_null(self, tmp_path: Path):
        """Parses tilde as null."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("value: ~\n")

        result = load_yaml(str(yaml_file))
        assert result["value"] is None

    def test_boolean_values(self, tmp_path: Path):
        """Parses various boolean representations."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(
            """
yes_value: yes
no_value: no
true_value: true
false_value: false
on_value: on
off_value: off
"""
        )

        result = load_yaml(str(yaml_file))
        assert result["yes_value"] is True
        assert result["no_value"] is False
        assert result["true_value"] is True
        assert result["false_value"] is False
        assert result["on_value"] is True
        assert result["off_value"] is False

    def test_multiline_string_literal(self, tmp_path: Path):
        """Parses literal block scalar (|)."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(
            """
description: |
  This is a
  multiline string
  with preserved newlines
"""
        )

        result = load_yaml(str(yaml_file))
        assert "multiline string" in result["description"]
        assert "\n" in result["description"]

    def test_multiline_string_folded(self, tmp_path: Path):
        """Parses folded block scalar (>)."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(
            """
description: >
  This is a long
  description that
  will be folded
"""
        )

        result = load_yaml(str(yaml_file))
        assert "long" in result["description"]
        assert "description" in result["description"]


class TestLoadYamlNumericValues:
    """load_yaml() with numeric values."""

    def test_integer(self, tmp_path: Path):
        """Parses integer value."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("count: 42\n")

        result = load_yaml(str(yaml_file))
        assert result["count"] == 42
        assert isinstance(result["count"], int)

    def test_float(self, tmp_path: Path):
        """Parses float value."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("ratio: 3.14159\n")

        result = load_yaml(str(yaml_file))
        assert result["ratio"] == pytest.approx(3.14159)
        assert isinstance(result["ratio"], float)

    def test_negative_numbers(self, tmp_path: Path):
        """Parses negative numbers."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("temperature: -10\noffset: -1.5\n")

        result = load_yaml(str(yaml_file))
        assert result["temperature"] == -10
        assert result["offset"] == -1.5

    def test_scientific_notation(self, tmp_path: Path):
        """Parses scientific notation."""
        yaml_file = tmp_path / "config.yaml"
        # YAML 1.1 (used by PyYAML) requires proper float format
        yaml_file.write_text("large: 1.0e+6\nsmall: 1.0e-6\n")

        result = load_yaml(str(yaml_file))
        assert result["large"] == 1_000_000
        assert result["small"] == pytest.approx(0.000001)


class TestLoadYamlUnicode:
    """load_yaml() with Unicode content."""

    def test_unicode_content(self, tmp_path: Path):
        """Loads Unicode content."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("message: Hello World\n", encoding="utf-8")

        result = load_yaml(str(yaml_file))
        assert result["message"] == "Hello World"

    def test_emoji(self, tmp_path: Path):
        """Loads emoji content."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("icon: Test Content\n", encoding="utf-8")

        result = load_yaml(str(yaml_file))
        assert result["icon"] == "Test Content"

    def test_chinese_characters(self, tmp_path: Path):
        """Loads Chinese characters."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("greeting: Hello\n", encoding="utf-8")

        result = load_yaml(str(yaml_file))
        assert result["greeting"] == "Hello"


# =============================================================================
# Invalid YAML Tests
# =============================================================================


class TestLoadYamlInvalidSyntax:
    """load_yaml() with invalid YAML syntax."""

    def test_invalid_indentation(self, tmp_path: Path):
        """Raises YAMLError for invalid indentation."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("parent:\n  child: value\n invalid: bad\n")

        with pytest.raises(yaml.YAMLError):
            load_yaml(str(yaml_file))

    def test_duplicate_keys_last_wins(self, tmp_path: Path):
        """Duplicate keys - last value wins (YAML 1.1 behavior)."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("key: first\nkey: second\n")

        result = load_yaml(str(yaml_file))
        assert result["key"] == "second"

    def test_colon_without_space(self, tmp_path: Path):
        """Colon without space may be treated as string."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("url: http://example.com\n")

        result = load_yaml(str(yaml_file))
        assert result["url"] == "http://example.com"


# =============================================================================
# Anchors and Aliases Tests
# =============================================================================


class TestLoadYamlAnchorsAliases:
    """load_yaml() with YAML anchors and aliases."""

    def test_anchor_and_alias(self, tmp_path: Path):
        """Parses anchors and aliases."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(
            """
defaults: &defaults
  timeout: 30
  retries: 3

production:
  <<: *defaults
  timeout: 60
"""
        )

        result = load_yaml(str(yaml_file))
        assert result["defaults"]["timeout"] == 30
        assert result["production"]["timeout"] == 60  # Overridden
        assert result["production"]["retries"] == 3  # Inherited


# =============================================================================
# Security Tests (safe_load)
# =============================================================================


class TestLoadYamlSecurity:
    """load_yaml() security (uses safe_load)."""

    def test_safe_load_prevents_arbitrary_objects(self, tmp_path: Path):
        """safe_load prevents Python object instantiation."""
        yaml_file = tmp_path / "config.yaml"
        # This would create a Python tuple if using unsafe load
        yaml_file.write_text("value: !!python/tuple [1, 2, 3]\n")

        # safe_load should raise an error for Python-specific tags
        with pytest.raises(yaml.YAMLError):
            load_yaml(str(yaml_file))
