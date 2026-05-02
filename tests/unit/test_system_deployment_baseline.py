from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.system.deployments.baseline import teardown_stack_runtime


def test_teardown_stack_runtime_runs_stop_and_down_after_capture_failure() -> None:
    bundle = object()
    stack = MagicMock()
    relay = MagicMock()

    with (
        patch(
            "tests.system.deployments.baseline.capture_stack_artifacts",
            side_effect=RuntimeError("capture failed"),
        ) as mock_capture,
        pytest.raises(RuntimeError, match="capture_stack_artifacts"),
    ):
        teardown_stack_runtime(bundle, stack, relay=relay, services=("postgres",), down_timeout=30)

    mock_capture.assert_called_once_with(bundle, stack, services=("postgres",))
    relay.stop.assert_called_once_with()
    stack.down.assert_called_once_with(timeout=30)


def test_teardown_stack_runtime_adds_cleanup_note_without_masking_active_failure() -> None:
    stack = MagicMock()
    relay = MagicMock()
    bundle = object()

    with (
        patch(
            "tests.system.deployments.baseline.capture_stack_artifacts",
            side_effect=RuntimeError("capture failed"),
        ),
        pytest.raises(ValueError, match="primary failure") as exc_info,
    ):
        try:
            raise ValueError("primary failure")
        finally:
            teardown_stack_runtime(bundle, stack, relay=relay, services=("postgres",))

    notes = getattr(exc_info.value, "__notes__", [])
    assert any("capture_stack_artifacts" in note for note in notes)
    relay.stop.assert_called_once_with()
    stack.down.assert_called_once_with(timeout=None)
