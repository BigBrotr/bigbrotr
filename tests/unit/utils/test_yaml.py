"""
Unit tests for utils.yaml module.

Tests:
- load_yaml() - YAML configuration file loading
"""

from pathlib import Path

import pytest

from utils.yaml import load_yaml


class TestLoadYamlValidFiles:
    """load_yaml() with valid YAML files."""

    def test_simple_yaml(self, tmp_path: Path):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("name: test\ncount: 42\n")

        result = load_yaml(str(yaml_file))
        assert result == {"name": "test", "count": 42}

    def test_nested_yaml(self, tmp_path: Path):
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

    def test_list_yaml(self, tmp_path: Path):
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

    def test_mixed_types(self, tmp_path: Path):
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
"""
        )

        result = load_yaml(str(yaml_file))
        assert result["name"] == "bigbrotr"
        assert result["version"] == 1.0
        assert result["enabled"] is True
        assert result["timeout"] == 30.5
        assert result["tags"] == ["nostr", "relay"]
        assert result["settings"]["debug"] is False

    def test_unicode_content(self, tmp_path: Path):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("message: Hello 世界 🌍\n", encoding="utf-8")

        result = load_yaml(str(yaml_file))
        assert result["message"] == "Hello 世界 🌍"


class TestLoadYamlEmptyFile:
    """load_yaml() with empty files."""

    def test_empty_file_returns_empty_dict(self, tmp_path: Path):
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("")

        result = load_yaml(str(yaml_file))
        assert result == {}

    def test_whitespace_only_returns_empty_dict(self, tmp_path: Path):
        yaml_file = tmp_path / "whitespace.yaml"
        yaml_file.write_text("   \n\n   \n")  # Only spaces and newlines (no tabs)

        result = load_yaml(str(yaml_file))
        assert result == {}

    def test_comments_only_returns_empty_dict(self, tmp_path: Path):
        yaml_file = tmp_path / "comments.yaml"
        yaml_file.write_text("# This is a comment\n# Another comment\n")

        result = load_yaml(str(yaml_file))
        assert result == {}


class TestLoadYamlFileNotFound:
    """load_yaml() with non-existent files."""

    def test_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError) as exc_info:
            load_yaml("/nonexistent/path/config.yaml")

        assert "Config file not found" in str(exc_info.value)
        assert "/nonexistent/path/config.yaml" in str(exc_info.value)

    def test_raises_for_missing_file_in_existing_dir(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_yaml(str(tmp_path / "missing.yaml"))


class TestLoadYamlPathTypes:
    """load_yaml() accepts different path formats."""

    def test_string_path(self, tmp_path: Path):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("key: value\n")

        result = load_yaml(str(yaml_file))
        assert result == {"key": "value"}

    def test_absolute_path(self, tmp_path: Path):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("key: value\n")

        result = load_yaml(str(yaml_file.absolute()))
        assert result == {"key": "value"}


class TestLoadYamlSpecialValues:
    """load_yaml() handles special YAML values."""

    def test_null_value(self, tmp_path: Path):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("value: null\n")

        result = load_yaml(str(yaml_file))
        assert result["value"] is None

    def test_tilde_null(self, tmp_path: Path):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("value: ~\n")

        result = load_yaml(str(yaml_file))
        assert result["value"] is None

    def test_boolean_values(self, tmp_path: Path):
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

    def test_multiline_string(self, tmp_path: Path):
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

    def test_folded_string(self, tmp_path: Path):
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
