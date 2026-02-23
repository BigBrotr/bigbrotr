"""Unit tests for utils.http module.

Tests:
- _read_bounded() internal helper
  - Single-read responses (fits in one read)
  - Chunked responses (multiple reads required)
  - Size enforcement across chunks
  - EOF handling
- download_bounded_file() async function
  - Successful download within size limit
  - Oversized download rejection (no file written)
  - Parent directory creation
  - HTTP error propagation
  - Size boundary behavior
- read_bounded_json() async function
  - Valid JSON parsing within size limit
  - Oversized response rejection
  - Exact-limit boundary behavior
  - Invalid JSON handling
  - Various JSON value types
  - Chunked JSON responses
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from bigbrotr.utils.http import _read_bounded, download_bounded_file, read_bounded_json


def _mock_response(*chunks: bytes) -> MagicMock:
    """Build a mock aiohttp.ClientResponse that yields chunks then EOF.

    Each positional argument is a chunk returned by successive ``content.read()``
    calls. An implicit ``b""`` is appended to signal EOF.
    """
    resp = MagicMock()
    content = MagicMock()
    content.read = AsyncMock(side_effect=[*chunks, b""])
    resp.content = content
    return resp


def _mock_session(*chunks: bytes, status: int = 200) -> MagicMock:
    """Build a mock aiohttp.ClientSession for download_bounded_file tests."""
    response = _mock_response(*chunks)
    response.raise_for_status = MagicMock()
    if status >= 400:
        response.raise_for_status.side_effect = aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=status
        )

    context_response = AsyncMock()
    context_response.__aenter__ = AsyncMock(return_value=response)
    context_response.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.get = MagicMock(return_value=context_response)

    context_session = AsyncMock()
    context_session.__aenter__ = AsyncMock(return_value=session)
    context_session.__aexit__ = AsyncMock(return_value=False)

    return context_session


# =============================================================================
# _read_bounded() Tests - Single Read
# =============================================================================


class TestReadBoundedSingleRead:
    """Tests for _read_bounded() when the body fits in a single read."""

    async def test_returns_full_body(self) -> None:
        """A body that fits in one read is returned completely."""
        body = b"hello world"
        resp = _mock_response(body)

        result = await _read_bounded(resp, max_size=1024)

        assert result == body

    async def test_accepts_body_at_exact_limit(self) -> None:
        """A body exactly at max_size is accepted."""
        body = b"x" * 100
        resp = _mock_response(body)

        result = await _read_bounded(resp, max_size=100)

        assert result == body

    async def test_rejects_one_byte_over_limit(self) -> None:
        """A body one byte over max_size raises ValueError."""
        body = b"x" * 101
        resp = _mock_response(body)

        with pytest.raises(ValueError, match="Response body too large"):
            await _read_bounded(resp, max_size=100)

    async def test_returns_empty_body(self) -> None:
        """An empty response body returns empty bytes."""
        resp = _mock_response()
        resp.content.read = AsyncMock(return_value=b"")

        result = await _read_bounded(resp, max_size=1024)

        assert result == b""


# =============================================================================
# _read_bounded() Tests - Chunked Reads
# =============================================================================


class TestReadBoundedChunked:
    """Tests for _read_bounded() with chunked transfer encoding."""

    async def test_reassembles_multiple_chunks(self) -> None:
        """Multiple chunks are concatenated into the full body."""
        resp = _mock_response(b"hello ", b"world")

        result = await _read_bounded(resp, max_size=1024)

        assert result == b"hello world"

    async def test_reassembles_many_small_chunks(self) -> None:
        """Many small chunks are correctly reassembled."""
        chunks = [b"a", b"b", b"c", b"d", b"e"]
        resp = _mock_response(*chunks)

        result = await _read_bounded(resp, max_size=1024)

        assert result == b"abcde"

    async def test_rejects_when_chunks_exceed_limit(self) -> None:
        """Raises ValueError when accumulated chunks exceed max_size."""
        resp = _mock_response(b"x" * 50, b"x" * 51)

        with pytest.raises(ValueError, match="Response body too large"):
            await _read_bounded(resp, max_size=100)

    async def test_accepts_chunks_at_exact_limit(self) -> None:
        """Chunks totaling exactly max_size are accepted."""
        resp = _mock_response(b"x" * 50, b"x" * 50)

        result = await _read_bounded(resp, max_size=100)

        assert result == b"x" * 100


# =============================================================================
# download_bounded_file() Tests - Successful Download
# =============================================================================


class TestDownloadBoundedFileSuccess:
    """Tests for download_bounded_file() with valid downloads."""

    async def test_writes_file_within_limit(self, tmp_path: Path) -> None:
        """A download within max_size is written to disk."""
        data = b"file content here"
        dest = tmp_path / "output.dat"

        with patch("bigbrotr.utils.http.aiohttp.ClientSession", return_value=_mock_session(data)):
            await download_bounded_file("https://example.com/file", dest, max_size=1024)

        assert dest.read_bytes() == data

    async def test_writes_file_at_exact_limit(self, tmp_path: Path) -> None:
        """A download exactly at max_size is accepted and written."""
        data = b"x" * 100
        dest = tmp_path / "exact.dat"

        with patch("bigbrotr.utils.http.aiohttp.ClientSession", return_value=_mock_session(data)):
            await download_bounded_file("https://example.com/file", dest, max_size=100)

        assert dest.read_bytes() == data

    async def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Parent directories are created if they do not exist."""
        data = b"nested"
        dest = tmp_path / "a" / "b" / "c" / "file.dat"

        with patch("bigbrotr.utils.http.aiohttp.ClientSession", return_value=_mock_session(data)):
            await download_bounded_file("https://example.com/file", dest, max_size=1024)

        assert dest.read_bytes() == data
        assert dest.parent.is_dir()

    async def test_first_read_requests_max_size_plus_one(self, tmp_path: Path) -> None:
        """First read() call requests max_size + 1 bytes to detect oversized bodies."""
        data = b"small"
        mock = _mock_session(data)
        dest = tmp_path / "probe.dat"

        with patch("bigbrotr.utils.http.aiohttp.ClientSession", return_value=mock):
            await download_bounded_file("https://example.com/file", dest, max_size=500)

        session = await mock.__aenter__()
        resp_ctx = session.get("https://example.com/file")
        response = await resp_ctx.__aenter__()
        first_call_args = response.content.read.await_args_list[0]
        assert first_call_args.args[0] == 501


# =============================================================================
# download_bounded_file() Tests - Size Enforcement
# =============================================================================


class TestDownloadBoundedFileSizeLimit:
    """Tests for download_bounded_file() size enforcement behavior."""

    async def test_rejects_oversized_download(self, tmp_path: Path) -> None:
        """A download exceeding max_size raises ValueError without writing."""
        data = b"x" * 101
        dest = tmp_path / "too_large.dat"

        with (
            patch("bigbrotr.utils.http.aiohttp.ClientSession", return_value=_mock_session(data)),
            pytest.raises(ValueError, match="Response body too large"),
        ):
            await download_bounded_file("https://example.com/file", dest, max_size=100)

        assert not dest.exists()

    async def test_rejects_one_byte_over_limit(self, tmp_path: Path) -> None:
        """A download one byte over max_size is rejected."""
        data = b"x" * 11
        dest = tmp_path / "over.dat"

        with (
            patch("bigbrotr.utils.http.aiohttp.ClientSession", return_value=_mock_session(data)),
            pytest.raises(ValueError, match="Response body too large"),
        ):
            await download_bounded_file("https://example.com/file", dest, max_size=10)

        assert not dest.exists()


# =============================================================================
# download_bounded_file() Tests - HTTP Errors
# =============================================================================


class TestDownloadBoundedFileErrors:
    """Tests for download_bounded_file() error handling."""

    async def test_propagates_http_error(self, tmp_path: Path) -> None:
        """HTTP errors from raise_for_status() propagate to the caller."""
        dest = tmp_path / "error.dat"

        with (
            patch(
                "bigbrotr.utils.http.aiohttp.ClientSession",
                return_value=_mock_session(b"", status=404),
            ),
            pytest.raises(aiohttp.ClientResponseError),
        ):
            await download_bounded_file("https://example.com/missing", dest, max_size=1024)

        assert not dest.exists()


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

    async def test_first_read_requests_max_size_plus_one(self) -> None:
        """First read() call requests max_size + 1 bytes to detect oversized bodies."""
        body = b'{"ok": true}'
        resp = _mock_response(body)

        await read_bounded_json(resp, max_size=1024)

        first_call_args = resp.content.read.await_args_list[0]
        assert first_call_args.args[0] == 1025

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


# =============================================================================
# read_bounded_json() Tests - Chunked Responses
# =============================================================================


class TestReadBoundedJsonChunked:
    """Tests for read_bounded_json() with chunked transfer encoding."""

    async def test_parses_json_split_across_chunks(self) -> None:
        """JSON split across multiple chunks is reassembled and parsed."""
        payload = ["wss://relay1.example.com", "wss://relay2.example.com"]
        full = json.dumps(payload).encode()
        mid = len(full) // 2
        resp = _mock_response(full[:mid], full[mid:])

        result = await read_bounded_json(resp, max_size=1024)

        assert result == payload

    async def test_parses_json_in_many_small_chunks(self) -> None:
        """JSON delivered in many small chunks is correctly parsed."""
        payload = {"key": "value", "num": 42}
        full = json.dumps(payload).encode()
        chunks = [full[i : i + 3] for i in range(0, len(full), 3)]
        resp = _mock_response(*chunks)

        result = await read_bounded_json(resp, max_size=1024)

        assert result == payload

    async def test_rejects_chunked_response_over_limit(self) -> None:
        """Chunked response exceeding max_size raises ValueError."""
        resp = _mock_response(b"x" * 60, b"x" * 60)

        with pytest.raises(ValueError, match="Response body too large"):
            await read_bounded_json(resp, max_size=100)
