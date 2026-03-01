"""Unit tests for services.monitor.utils module.

Tests:
- get_success: extract success status from metadata result logs
- get_reason: extract failure reason from metadata result logs
- safe_result: safely extract results from asyncio.gather output
- collect_metadata: build RelayMetadata list from successful check results
"""

from unittest.mock import MagicMock

from bigbrotr.models import Relay, RelayMetadata
from bigbrotr.nips.base import BaseLogs
from bigbrotr.nips.nip66.logs import Nip66RttMultiPhaseLogs
from bigbrotr.services.monitor.configs import MetadataFlags
from bigbrotr.services.monitor.utils import (
    collect_metadata,
    get_reason,
    get_success,
    safe_result,
)


# ============================================================================
# get_success Tests
# ============================================================================


class TestGetSuccess:
    """Tests for get_success function."""

    def test_base_logs_success_true(self) -> None:
        """Test success extraction from BaseLogs with success=True."""
        logs = BaseLogs(success=True, reason=None)
        result = MagicMock()
        result.logs = logs

        assert get_success(result) is True

    def test_base_logs_success_false(self) -> None:
        """Test success extraction from BaseLogs with success=False."""
        logs = BaseLogs(success=False, reason="connection refused")
        result = MagicMock()
        result.logs = logs

        assert get_success(result) is False

    def test_rtt_multi_phase_logs_success(self) -> None:
        """Test success extraction from Nip66RttMultiPhaseLogs."""
        logs = Nip66RttMultiPhaseLogs(
            open_success=True,
            open_reason=None,
            read_success=True,
            read_reason=None,
            write_success=True,
            write_reason=None,
        )
        result = MagicMock()
        result.logs = logs

        assert get_success(result) is True

    def test_rtt_multi_phase_logs_failure(self) -> None:
        """Test success extraction from Nip66RttMultiPhaseLogs with failure."""
        logs = Nip66RttMultiPhaseLogs(
            open_success=False,
            open_reason="timeout",
            read_success=False,
            read_reason="timeout",
            write_success=False,
            write_reason="timeout",
        )
        result = MagicMock()
        result.logs = logs

        assert get_success(result) is False

    def test_unknown_logs_type(self) -> None:
        """Test success returns False for unknown logs type."""
        result = MagicMock()
        result.logs = "not a logs object"

        assert get_success(result) is False


# ============================================================================
# get_reason Tests
# ============================================================================


class TestGetReason:
    """Tests for get_reason function."""

    def test_base_logs_with_reason(self) -> None:
        """Test reason extraction from BaseLogs with failure reason."""
        logs = BaseLogs(success=False, reason="connection refused")
        result = MagicMock()
        result.logs = logs

        assert get_reason(result) == "connection refused"

    def test_base_logs_no_reason(self) -> None:
        """Test reason extraction from BaseLogs with no reason (success)."""
        logs = BaseLogs(success=True, reason=None)
        result = MagicMock()
        result.logs = logs

        assert get_reason(result) is None

    def test_rtt_multi_phase_logs_with_reason(self) -> None:
        """Test reason extraction from Nip66RttMultiPhaseLogs."""
        logs = Nip66RttMultiPhaseLogs(
            open_success=False,
            open_reason="timeout",
            read_success=False,
            read_reason="timeout",
            write_success=False,
            write_reason="timeout",
        )
        result = MagicMock()
        result.logs = logs

        assert get_reason(result) == "timeout"

    def test_rtt_multi_phase_logs_no_reason(self) -> None:
        """Test reason extraction from Nip66RttMultiPhaseLogs with success."""
        logs = Nip66RttMultiPhaseLogs(
            open_success=True,
            open_reason=None,
            read_success=True,
            read_reason=None,
            write_success=True,
            write_reason=None,
        )
        result = MagicMock()
        result.logs = logs

        assert get_reason(result) is None

    def test_unknown_logs_type(self) -> None:
        """Test reason returns None for unknown logs type."""
        result = MagicMock()
        result.logs = "not a logs object"

        assert get_reason(result) is None


# ============================================================================
# safe_result Tests
# ============================================================================


class TestSafeResult:
    """Tests for safe_result function."""

    def test_valid_result(self) -> None:
        """Test extracting a valid (non-exception) result."""
        results = {"nip11": MagicMock(), "nip66_rtt": MagicMock()}

        value = safe_result(results, "nip11")
        assert value is not None

    def test_exception_result(self) -> None:
        """Test that exception results return None."""
        results = {"nip11": ValueError("some error")}

        value = safe_result(results, "nip11")
        assert value is None

    def test_missing_key(self) -> None:
        """Test that missing keys return None."""
        results = {"nip11": MagicMock()}

        value = safe_result(results, "nip66_rtt")
        assert value is None

    def test_none_value(self) -> None:
        """Test that None values return None."""
        results = {"nip11": None}

        value = safe_result(results, "nip11")
        assert value is None

    def test_base_exception_result(self) -> None:
        """Test that BaseException subclasses return None."""
        results = {"nip11": KeyboardInterrupt()}

        value = safe_result(results, "nip11")
        assert value is None


# ============================================================================
# collect_metadata Tests
# ============================================================================


class TestCollectMetadata:
    """Tests for collect_metadata function."""

    def _make_check_result(self, **nip_fields: MagicMock | None) -> MagicMock:
        """Create a mock CheckResult with given NIP fields."""
        result = MagicMock()
        result.generated_at = 1700000000

        for field in (
            "nip11",
            "nip66_rtt",
            "nip66_ssl",
            "nip66_geo",
            "nip66_net",
            "nip66_dns",
            "nip66_http",
        ):
            setattr(result, field, nip_fields.get(field))

        return result

    def test_empty_successful_list(self) -> None:
        """Test with no successful results."""
        metadata = collect_metadata([], MetadataFlags())
        assert metadata == []

    def test_collects_enabled_metadata_types(self) -> None:
        """Test that enabled store flags produce RelayMetadata entries."""
        relay = Relay("wss://relay.example.com")
        nip11_meta = MagicMock()
        nip11_meta.to_dict.return_value = {"name": "test relay"}

        result = self._make_check_result(nip11=nip11_meta)

        # Only nip11_info enabled for store
        store = MetadataFlags(
            nip11_info=True,
            nip66_rtt=False,
            nip66_ssl=False,
            nip66_geo=False,
            nip66_net=False,
            nip66_dns=False,
            nip66_http=False,
        )

        metadata = collect_metadata([(relay, result)], store)

        assert len(metadata) == 1
        assert isinstance(metadata[0], RelayMetadata)

    def test_skips_disabled_store_flags(self) -> None:
        """Test that disabled store flags produce no metadata."""
        relay = Relay("wss://relay.example.com")
        nip11_meta = MagicMock()
        nip11_meta.to_dict.return_value = {"name": "test relay"}

        result = self._make_check_result(nip11=nip11_meta)

        store = MetadataFlags(
            nip11_info=False,
            nip66_rtt=False,
            nip66_ssl=False,
            nip66_geo=False,
            nip66_net=False,
            nip66_dns=False,
            nip66_http=False,
        )

        metadata = collect_metadata([(relay, result)], store)
        assert metadata == []

    def test_skips_none_results(self) -> None:
        """Test that None NIP metadata fields are skipped even when store enabled."""
        relay = Relay("wss://relay.example.com")
        result = self._make_check_result()  # All fields None

        metadata = collect_metadata([(relay, result)], MetadataFlags())
        assert metadata == []

    def test_multiple_relays_and_types(self) -> None:
        """Test metadata collection from multiple relays with multiple types."""
        relay1 = Relay("wss://relay1.example.com")
        relay2 = Relay("wss://relay2.example.com")

        nip11_meta = MagicMock()
        nip11_meta.to_dict.return_value = {"name": "relay1"}
        rtt_meta = MagicMock()
        rtt_meta.to_dict.return_value = {"open_rtt": 50}

        result1 = self._make_check_result(nip11=nip11_meta, nip66_rtt=rtt_meta)
        result2 = self._make_check_result(nip11=nip11_meta)

        store = MetadataFlags(
            nip11_info=True,
            nip66_rtt=True,
            nip66_ssl=False,
            nip66_geo=False,
            nip66_net=False,
            nip66_dns=False,
            nip66_http=False,
        )

        metadata = collect_metadata([(relay1, result1), (relay2, result2)], store)

        # relay1: nip11 + rtt = 2, relay2: nip11 = 1 → total 3
        assert len(metadata) == 3
