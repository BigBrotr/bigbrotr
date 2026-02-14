"""Unit tests for utils.http module.

Tests:
- read_bounded_json() async function
  - Valid JSON parsing within size limit
  - Oversized response rejection
  - Exact-limit boundary behavior
  - Invalid JSON handling
  - Various JSON value types
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.utils.http import read_bounded_json


def _mock_response(body: bytes) -> MagicMock:
    """Build a mock aiohttp.ClientResponse with the given body bytes."""
    resp = MagicMock()
    content = MagicMock()
    content.read = AsyncMock(return_value=body)
    resp.content = content
    return resp


# =============================================================================
# read_bounded_json() Tests - Valid Input
# =============================================================================


class TestReadBoundedJsonValid:
    """Tests for read_bounded_json() with valid, within-limit responses."""

    async def test_parses_valid_json_dict(self) -> None:
        """A JSON object within the size limit is parsed correctly."""
        payload = {"relays": ["wss://relay.example.com"]}
        body = json.dumps(payload).encode()
        resp = _mock_response(body)

        result = await read_bounded_json(resp, max_size=1024)

        assert result == payload

    async def test_parses_valid_json_list(self) -> None:
        """A JSON array within the size limit is parsed correctly."""
        payload = ["wss://relay1.example.com", "wss://relay2.example.com"]
        body = json.dumps(payload).encode()
        resp = _mock_response(body)

        result = await read_bounded_json(resp, max_size=1024)

        assert result == payload

    async def test_parses_json_string(self) -> None:
        """A JSON string value is parsed correctly."""
        body = b'"hello"'
        resp = _mock_response(body)

        result = await read_bounded_json(resp, max_size=1024)

        assert result == "hello"

    async def test_parses_json_number(self) -> None:
        """A JSON number value is parsed correctly."""
        body = b"42"
        resp = _mock_response(body)

        result = await read_bounded_json(resp, max_size=1024)

        assert result == 42

    async def test_parses_json_null(self) -> None:
        """A JSON null value is parsed correctly."""
        body = b"null"
        resp = _mock_response(body)

        result = await read_bounded_json(resp, max_size=1024)

        assert result is None

    async def test_parses_json_boolean(self) -> None:
        """A JSON boolean value is parsed correctly."""
        body = b"true"
        resp = _mock_response(body)

        result = await read_bounded_json(resp, max_size=1024)

        assert result is True


# =============================================================================
# read_bounded_json() Tests - Size Enforcement
# =============================================================================


class TestReadBoundedJsonSizeLimit:
    """Tests for read_bounded_json() size enforcement behavior."""

    async def test_accepts_body_at_exact_limit(self) -> None:
        """A body exactly at max_size is accepted."""
        body = b"x" * 100
        resp = _mock_response(body)

        # max_size=100, body is exactly 100 bytes — within limit
        # json.loads will fail but size check passes
        with pytest.raises(json.JSONDecodeError):
            await read_bounded_json(resp, max_size=100)

    async def test_accepts_json_at_exact_limit(self) -> None:
        """Valid JSON body exactly at max_size is parsed correctly."""
        payload = json.dumps({"k": "v"}).encode()  # 10 bytes
        resp = _mock_response(payload)

        result = await read_bounded_json(resp, max_size=len(payload))

        assert result == {"k": "v"}

    async def test_rejects_oversized_response(self) -> None:
        """A body exceeding max_size raises ValueError."""
        body = b"x" * 101
        resp = _mock_response(body)

        with pytest.raises(ValueError, match="Response body too large"):
            await read_bounded_json(resp, max_size=100)

    async def test_reads_max_size_plus_one_bytes(self) -> None:
        """read() is called with max_size + 1 to detect oversized bodies."""
        body = b'{"ok": true}'
        resp = _mock_response(body)

        await read_bounded_json(resp, max_size=1024)

        resp.content.read.assert_awaited_once_with(1025)

    async def test_rejects_one_byte_over_limit(self) -> None:
        """A body one byte over max_size is rejected."""
        body = b"x" * 11
        resp = _mock_response(body)

        with pytest.raises(ValueError, match="Response body too large"):
            await read_bounded_json(resp, max_size=10)


# =============================================================================
# read_bounded_json() Tests - Invalid JSON
# =============================================================================


class TestReadBoundedJsonInvalidBody:
    """Tests for read_bounded_json() with invalid JSON bodies."""

    async def test_raises_on_invalid_json(self) -> None:
        """Non-JSON body within size limit raises JSONDecodeError."""
        body = b"this is not json"
        resp = _mock_response(body)

        with pytest.raises(json.JSONDecodeError):
            await read_bounded_json(resp, max_size=1024)

    async def test_raises_on_empty_body(self) -> None:
        """Empty body raises JSONDecodeError."""
        resp = _mock_response(b"")

        with pytest.raises(json.JSONDecodeError):
            await read_bounded_json(resp, max_size=1024)

    async def test_raises_on_truncated_json(self) -> None:
        """Truncated JSON raises JSONDecodeError."""
        body = b'{"key": "val'
        resp = _mock_response(body)

        with pytest.raises(json.JSONDecodeError):
            await read_bounded_json(resp, max_size=1024)
