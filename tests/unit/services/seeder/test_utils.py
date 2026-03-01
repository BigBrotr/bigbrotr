"""Unit tests for services.seeder.utils module."""

from pathlib import Path

from bigbrotr.services.seeder.utils import parse_seed_file


# ============================================================================
# Parse Seed File Tests
# ============================================================================


class TestParseSeedFile:
    """Tests for parse_seed_file() utility function."""

    def test_parse_valid_relays(self, tmp_path: Path) -> None:
        """Test parsing valid relay URLs."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("wss://relay1.example.com\nwss://relay2.example.com\n")

        relays = parse_seed_file(seed_file)

        assert len(relays) == 2
        urls = [r.url for r in relays]
        assert "wss://relay1.example.com" in urls
        assert "wss://relay2.example.com" in urls

    def test_parse_skips_comments(self, tmp_path: Path) -> None:
        """Test parsing skips comment lines."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("# This is a comment\nwss://relay.example.com\n# Another comment\n")

        relays = parse_seed_file(seed_file)

        assert len(relays) == 1
        assert relays[0].url == "wss://relay.example.com"

    def test_parse_skips_empty_lines(self, tmp_path: Path) -> None:
        """Test parsing skips empty lines."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("\n\nwss://relay.example.com\n\n")

        relays = parse_seed_file(seed_file)

        assert len(relays) == 1

    def test_parse_skips_invalid_urls(self, tmp_path: Path) -> None:
        """Test parsing skips invalid URLs."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("invalid-url\nwss://valid.relay.com\nnot-a-relay\n")

        relays = parse_seed_file(seed_file)

        assert len(relays) == 1
        assert relays[0].url == "wss://valid.relay.com"

    def test_parse_strips_whitespace(self, tmp_path: Path) -> None:
        """Test parsing strips leading/trailing whitespace."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("  wss://relay.example.com  \n")

        relays = parse_seed_file(seed_file)

        assert len(relays) == 1
        assert relays[0].url == "wss://relay.example.com"

    def test_parse_handles_tor_urls(self, tmp_path: Path) -> None:
        """Test parsing handles Tor .onion URLs."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("ws://example.onion\n")

        relays = parse_seed_file(seed_file)

        assert len(relays) == 1
        assert "onion" in relays[0].url

    def test_parse_handles_i2p_urls(self, tmp_path: Path) -> None:
        """Test parsing handles I2P .i2p URLs."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("ws://example.i2p\n")

        relays = parse_seed_file(seed_file)

        assert len(relays) == 1
        assert "i2p" in relays[0].url

    def test_parse_file_not_found(self, tmp_path: Path) -> None:
        """Test parsing returns empty list for non-existent file."""
        relays = parse_seed_file(tmp_path / "nonexistent.txt")
        assert relays == []

    def test_parse_permission_error(self, tmp_path: Path) -> None:
        """Test parsing returns empty list when file is not readable."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_text("wss://relay.example.com")
        seed_file.chmod(0o000)

        relays = parse_seed_file(seed_file)
        assert relays == []

        seed_file.chmod(0o644)

    def test_parse_is_a_directory_error(self, tmp_path: Path) -> None:
        """Test parsing returns empty list when path is a directory."""
        relays = parse_seed_file(tmp_path)
        assert relays == []

    def test_parse_unicode_decode_error(self, tmp_path: Path) -> None:
        """Test parsing returns empty list for non-UTF-8 file."""
        seed_file = tmp_path / "seed.txt"
        seed_file.write_bytes(b"\xff\xfe" + b"\x00" * 50)

        relays = parse_seed_file(seed_file)
        assert relays == []
