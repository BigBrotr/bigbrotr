"""Tests for assertor runtime helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bigbrotr.models.constants import EventKind
from bigbrotr.services.assertor.configs import AssertorConfig
from bigbrotr.services.assertor.runtime import (
    PublishCycleResult,
    PublishKindResult,
    emit_publish_metrics,
    publish_timed,
    run_checkpoint_cleanup,
    run_selected_publishers,
)


VALID_HEX_KEY = (
    "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"  # pragma: allowlist secret
)


@pytest.fixture(autouse=True)
def _set_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOSTR_PRIVATE_KEY_ASSERTOR", VALID_HEX_KEY)


class TestPublishTimed:
    async def test_builds_kind_result(self) -> None:
        async def _publish() -> tuple[int, int, int]:
            return (2, 3, 1)

        result = await publish_timed(_publish)

        assert result == PublishKindResult(
            eligible=6,
            published=2,
            skipped=3,
            failed=1,
            duration_seconds=result.duration_seconds,
        )
        assert result.duration_seconds >= 0.0


class TestRunSelectedPublishers:
    async def test_runs_only_enabled_publishers(self) -> None:
        config = AssertorConfig(
            selection={
                "kinds": [
                    EventKind.NIP85_USER_ASSERTION,
                    EventKind.NIP85_EVENT_ASSERTION,
                ]
            },
            metrics={"enabled": False},
        )
        publish_timed_func = AsyncMock(
            side_effect=[
                PublishKindResult(published=2),
                PublishKindResult(failed=1),
            ]
        )
        publish_user_assertions = AsyncMock()
        publish_event_assertions = AsyncMock()
        publish_addressable_assertions = AsyncMock()
        publish_identifier_assertions = AsyncMock()
        publish_provider_profile = AsyncMock()

        result = await run_selected_publishers(
            config=config,
            publish_timed_func=publish_timed_func,
            publish_user_assertions=publish_user_assertions,
            publish_event_assertions=publish_event_assertions,
            publish_addressable_assertions=publish_addressable_assertions,
            publish_identifier_assertions=publish_identifier_assertions,
            publish_provider_profile=publish_provider_profile,
        )

        assert result == (
            PublishKindResult(published=2),
            PublishKindResult(failed=1),
            PublishKindResult(),
            PublishKindResult(),
            PublishKindResult(),
        )
        assert [call.args[0] for call in publish_timed_func.await_args_list] == [
            publish_user_assertions,
            publish_event_assertions,
        ]

    async def test_runs_provider_profile_when_enabled(self) -> None:
        config = AssertorConfig(
            selection={"kinds": [EventKind.NIP85_IDENTIFIER_ASSERTION]},
            provider_profile={"enabled": True},
            metrics={"enabled": False},
        )
        publish_timed_func = AsyncMock(
            side_effect=[
                PublishKindResult(skipped=3),
                PublishKindResult(published=1),
            ]
        )

        result = await run_selected_publishers(
            config=config,
            publish_timed_func=publish_timed_func,
            publish_user_assertions=AsyncMock(),
            publish_event_assertions=AsyncMock(),
            publish_addressable_assertions=AsyncMock(),
            publish_identifier_assertions=AsyncMock(),
            publish_provider_profile=AsyncMock(),
        )

        assert result == (
            PublishKindResult(),
            PublishKindResult(),
            PublishKindResult(),
            PublishKindResult(skipped=3),
            PublishKindResult(published=1),
        )


class TestRunCheckpointCleanup:
    async def test_obeys_cleanup_toggle(self) -> None:
        delete_stale_checkpoints = AsyncMock(return_value=7)

        disabled_removed, disabled_duration = await run_checkpoint_cleanup(
            cleanup_enabled=False,
            delete_stale_checkpoints=delete_stale_checkpoints,
        )
        assert disabled_removed == 0
        assert disabled_duration >= 0.0
        delete_stale_checkpoints.assert_not_awaited()

        enabled_removed, enabled_duration = await run_checkpoint_cleanup(
            cleanup_enabled=True,
            delete_stale_checkpoints=delete_stale_checkpoints,
        )
        assert enabled_removed == 7
        assert enabled_duration >= 0.0
        delete_stale_checkpoints.assert_awaited_once_with()


class TestEmitPublishMetrics:
    def test_emits_expected_gauges(self) -> None:
        service = MagicMock()
        result = PublishCycleResult(
            user=PublishKindResult(eligible=3, published=2, skipped=1, duration_seconds=1.5),
            provider_profile=PublishKindResult(published=1, duration_seconds=0.25),
            checkpoint_cleanup_removed=4,
        )

        emit_publish_metrics(service, result, cleanup_duration=0.5)

        service.set_gauge.assert_any_call("assertions_published", 2)
        service.set_gauge.assert_any_call("assertions_skipped", 1)
        service.set_gauge.assert_any_call("assertions_failed", 0)
        service.set_gauge.assert_any_call("provider_profiles_published", 1)
        service.set_gauge.assert_any_call("checkpoint_cleanup_removed", 4)
        service.set_gauge.assert_any_call("user_assertions_eligible", 3)
        service.set_gauge.assert_any_call("phase_duration_user_seconds", 1.5)
        service.set_gauge.assert_any_call("phase_duration_cleanup_seconds", 0.5)
        service.set_gauge.assert_any_call("provider_profile_published", 1)
