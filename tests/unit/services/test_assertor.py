"""Tests for the Assertor service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from pydantic import ValidationError

from bigbrotr.models.constants import EventKind, ServiceName
from bigbrotr.models.service_state import ServiceStateType
from bigbrotr.services.assertor.configs import AssertorConfig
from bigbrotr.services.assertor.service import Assertor
from bigbrotr.services.common.state_store import ServiceStateStore
from bigbrotr.utils.protocol import (
    BroadcastClientResult,
    ClientConnectResult,
    ClientSession,
    NostrClientManager,
)


VALID_HEX_KEY = (
    "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"  # pragma: allowlist secret
)


def _connect_output() -> ClientConnectResult:
    return ClientConnectResult(connected=("wss://relay.example",), failed={})


def _session_output(mock_client: AsyncMock | MagicMock) -> ClientSession:
    return ClientSession(
        session_id="assertor-publish-relays",
        client=mock_client,
        relay_urls=("wss://relay.example",),
        connect_result=_connect_output(),
    )


def _broadcast_results(
    *,
    successful_relays: tuple[str, ...] = ("wss://relay.example",),
    failed_relays: dict[str, str] | None = None,
) -> list[BroadcastClientResult]:
    return [
        BroadcastClientResult(
            event_ids=("event-id",),
            successful_relays=successful_relays,
            failed_relays=failed_relays or {},
        )
    ]


@pytest.fixture(autouse=True)
def _set_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOSTR_PRIVATE_KEY_ASSERTOR", VALID_HEX_KEY)


def _assertor_harness(
    mock_brotr: MagicMock,
    *,
    config: AssertorConfig | None = None,
    connected: bool = True,
) -> Assertor:
    service = Assertor(
        brotr=mock_brotr,
        config=config or AssertorConfig(metrics={"enabled": False}),
    )
    service._client = MagicMock() if connected else None
    service._logger = MagicMock()
    service.set_gauge = MagicMock()
    service._cycle_seen_state_keys = set()
    return service


class TestAssertorConfig:
    def test_defaults(self) -> None:
        config = AssertorConfig()
        assert config.algorithm_id == "global-pagerank"
        assert config.keys.keys_env == "NOSTR_PRIVATE_KEY_ASSERTOR"
        assert config.keys.keys is not None
        assert config.interval == 3600.0
        assert config.selection.batch_size == 500
        assert config.selection.min_events == 1
        assert config.selection.top_topics == 5
        assert len(config.publishing.relays) == 3
        assert config.selection.kinds == [30382, 30383, 30384, 30385]
        assert config.publishing.allow_insecure is False
        assert config.cleanup.remove_stale_checkpoints is True
        assert config.provider_profile.enabled is False

    def test_custom_values(
        self,
    ) -> None:
        config = AssertorConfig(
            algorithm_id="trust-graph",
            selection={
                "batch_size": 100,
                "min_events": 10,
                "top_topics": 3,
                "kinds": [30382],
            },
            publishing={"allow_insecure": True, "relays": ["wss://relay.example.com"]},
            cleanup={"remove_stale_checkpoints": False},
        )
        assert config.algorithm_id == "trust-graph"
        assert config.selection.batch_size == 100
        assert config.selection.min_events == 10
        assert config.selection.top_topics == 3
        assert config.selection.kinds == [30382]
        assert config.publishing.allow_insecure is True
        assert [relay.url for relay in config.publishing.relays] == ["wss://relay.example.com"]
        assert config.cleanup.remove_stale_checkpoints is False

    def test_batch_size_validation(
        self,
    ) -> None:
        with pytest.raises(ValidationError):
            AssertorConfig(selection={"batch_size": 0})

    def test_kinds_must_not_be_empty(
        self,
    ) -> None:
        with pytest.raises(ValidationError):
            AssertorConfig(selection={"kinds": []})

    def test_relays_must_not_be_empty(
        self,
    ) -> None:
        with pytest.raises(ValidationError):
            AssertorConfig(publishing={"relays": []})

    def test_unsupported_kind_rejected(self) -> None:
        with pytest.raises(ValidationError, match="unsupported assertion kinds"):
            AssertorConfig(selection={"kinds": [42]})

    def test_mixed_valid_invalid_kinds_rejected(self) -> None:
        with pytest.raises(ValidationError, match="unsupported assertion kinds"):
            AssertorConfig(selection={"kinds": [30382, 99999]})

    def test_valid_single_kind(self) -> None:
        config = AssertorConfig(selection={"kinds": [30385]})
        assert config.selection.kinds == [30385]

    def test_invalid_algorithm_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="algorithm_id"):
            AssertorConfig(algorithm_id="Global PageRank")

    def test_duplicate_kinds_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate assertion kinds"):
            AssertorConfig(selection={"kinds": [30382, 30382]})


class TestAssertorInit:
    def test_service_name(self) -> None:
        from bigbrotr.services.assertor.service import Assertor

        assert Assertor.SERVICE_NAME == ServiceName.ASSERTOR

    def test_config_class(self) -> None:
        from bigbrotr.services.assertor.service import Assertor

        assert Assertor.CONFIG_CLASS is AssertorConfig


class TestAssertorRun:
    @pytest.fixture
    def mock_brotr(self) -> MagicMock:
        brotr = MagicMock()
        brotr.get_service_state = AsyncMock(return_value=[])
        brotr.upsert_service_state = AsyncMock()
        brotr.fetch = AsyncMock(return_value=[])
        brotr.fetchval = AsyncMock(return_value=0)
        brotr.execute = AsyncMock()
        return brotr

    async def test_publish_no_client_returns_early(self, mock_brotr: MagicMock) -> None:
        from bigbrotr.services.assertor.service import PublishCycleResult

        service = _assertor_harness(mock_brotr, connected=False)
        result = await service.publish()
        assert result == PublishCycleResult()
        service.set_gauge.assert_not_called()

    async def test_run_delegates_to_publish(self, mock_brotr: MagicMock) -> None:
        from bigbrotr.services.assertor.service import Assertor, PublishCycleResult

        service = Assertor.__new__(Assertor)
        service.publish = AsyncMock(  # type: ignore[method-assign]
            return_value=PublishCycleResult(),
        )

        await service.run()

        service.publish.assert_awaited_once_with()

    async def test_publish_returns_user_assertion_counts(self, mock_brotr: MagicMock) -> None:
        from bigbrotr.services.assertor.service import (
            PublishCycleResult,
            PublishKindResult,
        )

        service = _assertor_harness(
            mock_brotr,
            config=AssertorConfig(
                selection={"kinds": [EventKind.NIP85_USER_ASSERTION]},
                metrics={"enabled": False},
            ),
        )
        service._publish_user_assertions = AsyncMock(return_value=(5, 2, 1))
        service._publish_event_assertions = AsyncMock(return_value=(0, 0, 0))

        result = await service.publish()

        service._publish_user_assertions.assert_awaited_once()
        assert result == PublishCycleResult(
            user=PublishKindResult(
                eligible=8,
                published=5,
                skipped=2,
                failed=1,
                duration_seconds=result.user.duration_seconds,
            )
        )
        assert result.assertions_published == 5
        assert result.assertions_skipped == 2
        assert result.assertions_failed == 1
        service.set_gauge.assert_any_call("assertions_published", 5)
        service.set_gauge.assert_any_call("assertions_skipped", 2)
        service.set_gauge.assert_any_call("assertions_failed", 1)
        service.set_gauge.assert_any_call("user_assertions_eligible", 8)
        service.set_gauge.assert_any_call("user_assertions_published", 5)

    async def test_publish_skips_stale_cleanup_when_disabled(self, mock_brotr: MagicMock) -> None:
        service = _assertor_harness(
            mock_brotr,
            config=AssertorConfig(
                selection={"kinds": [EventKind.NIP85_USER_ASSERTION]},
                cleanup={"remove_stale_checkpoints": False},
                metrics={"enabled": False},
            ),
        )
        service._publish_user_assertions = AsyncMock(return_value=(0, 0, 0))
        service._delete_stale_checkpoints = AsyncMock(return_value=99)

        result = await service.publish()

        assert result.checkpoint_cleanup_removed == 0
        service._delete_stale_checkpoints.assert_not_awaited()

    async def test_run_selected_publishers_only_runs_enabled_kinds(
        self,
        mock_brotr: MagicMock,
    ) -> None:
        from bigbrotr.services.assertor.service import PublishKindResult

        service = _assertor_harness(
            mock_brotr,
            config=AssertorConfig(
                selection={
                    "kinds": [
                        EventKind.NIP85_USER_ASSERTION,
                        EventKind.NIP85_EVENT_ASSERTION,
                    ]
                },
                metrics={"enabled": False},
            ),
        )
        service._publish_user_assertions = AsyncMock()
        service._publish_event_assertions = AsyncMock()
        service._publish_addressable_assertions = AsyncMock()
        service._publish_identifier_assertions = AsyncMock()
        service._publish_provider_profile = AsyncMock()
        service._publish_timed = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                PublishKindResult(published=2),
                PublishKindResult(failed=1),
            ]
        )

        result = await service._run_selected_publishers()

        assert result == (
            PublishKindResult(published=2),
            PublishKindResult(failed=1),
            PublishKindResult(),
            PublishKindResult(),
            PublishKindResult(),
        )
        assert [call.args[0] for call in service._publish_timed.await_args_list] == [
            service._publish_user_assertions,
            service._publish_event_assertions,
        ]

    async def test_run_selected_publishers_runs_provider_profile_when_enabled(
        self,
        mock_brotr: MagicMock,
    ) -> None:
        from bigbrotr.services.assertor.service import PublishKindResult

        service = _assertor_harness(
            mock_brotr,
            config=AssertorConfig(
                selection={"kinds": [EventKind.NIP85_IDENTIFIER_ASSERTION]},
                provider_profile={"enabled": True},
                metrics={"enabled": False},
            ),
        )
        service._publish_user_assertions = AsyncMock()
        service._publish_event_assertions = AsyncMock()
        service._publish_addressable_assertions = AsyncMock()
        service._publish_identifier_assertions = AsyncMock()
        service._publish_provider_profile = AsyncMock()
        service._publish_timed = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                PublishKindResult(skipped=3),
                PublishKindResult(published=1),
            ]
        )

        result = await service._run_selected_publishers()

        assert result == (
            PublishKindResult(),
            PublishKindResult(),
            PublishKindResult(),
            PublishKindResult(skipped=3),
            PublishKindResult(published=1),
        )
        assert [call.args[0] for call in service._publish_timed.await_args_list] == [
            service._publish_identifier_assertions,
            service._publish_provider_profile,
        ]

    async def test_run_checkpoint_cleanup_obeys_cleanup_toggle(self, mock_brotr: MagicMock) -> None:
        disabled_service = _assertor_harness(
            mock_brotr,
            config=AssertorConfig(
                cleanup={"remove_stale_checkpoints": False},
                metrics={"enabled": False},
            ),
        )
        disabled_service._delete_stale_checkpoints = AsyncMock(return_value=99)

        disabled_removed, disabled_duration = await disabled_service._run_checkpoint_cleanup()

        assert disabled_removed == 0
        assert disabled_duration >= 0.0
        disabled_service._delete_stale_checkpoints.assert_not_awaited()

        enabled_service = _assertor_harness(
            mock_brotr,
            config=AssertorConfig(
                cleanup={"remove_stale_checkpoints": True},
                metrics={"enabled": False},
            ),
        )
        enabled_service._delete_stale_checkpoints = AsyncMock(return_value=7)

        enabled_removed, enabled_duration = await enabled_service._run_checkpoint_cleanup()

        assert enabled_removed == 7
        assert enabled_duration >= 0.0
        enabled_service._delete_stale_checkpoints.assert_awaited_once_with()

    def test_state_store_is_initialized_once(self, mock_brotr: MagicMock) -> None:
        service = _assertor_harness(mock_brotr)

        assert isinstance(service._state_store, ServiceStateStore)
        assert service._state_store._brotr is mock_brotr

    def test_mark_seen_state_key_adds_to_existing_set(self, mock_brotr: MagicMock) -> None:
        service = _assertor_harness(mock_brotr)
        service._cycle_seen_state_keys = {"global-pagerank:30382:" + ("bb" * 32)}

        service._mark_seen_state_key("global-pagerank:30382:" + ("aa" * 32))

        assert service._cycle_seen_state_keys == {
            "global-pagerank:30382:" + ("aa" * 32),
            "global-pagerank:30382:" + ("bb" * 32),
        }

    async def test_is_unchanged_no_state(self, mock_brotr: MagicMock) -> None:
        service = _assertor_harness(mock_brotr)
        mock_brotr.get_service_state = AsyncMock(return_value=[])

        result = await service._is_unchanged("test_pubkey", "abc123")
        assert result is False

    async def test_is_unchanged_same_hash(self, mock_brotr: MagicMock) -> None:
        service = _assertor_harness(mock_brotr)

        state = MagicMock()
        state.state_value = {"hash": "abc123", "timestamp": 1234}
        mock_brotr.get_service_state = AsyncMock(return_value=[state])

        result = await service._is_unchanged("test_pubkey", "abc123")
        assert result is True

    async def test_is_unchanged_different_hash(self, mock_brotr: MagicMock) -> None:
        service = _assertor_harness(mock_brotr)

        state = MagicMock()
        state.state_value = {"hash": "old_hash", "timestamp": 1234}
        mock_brotr.get_service_state = AsyncMock(return_value=[state])

        result = await service._is_unchanged("test_pubkey", "new_hash")
        assert result is False

    async def test_save_hash_calls_upsert(self, mock_brotr: MagicMock) -> None:
        service = _assertor_harness(mock_brotr)

        await service._save_hash("test_subject", "abc123")

        mock_brotr.upsert_service_state.assert_awaited_once()
        call_args = mock_brotr.upsert_service_state.call_args[0][0]
        assert len(call_args) == 1
        assert call_args[0].service_name == ServiceName.ASSERTOR
        assert call_args[0].state_key == "test_subject"
        assert call_args[0].state_value["hash"] == "abc123"


class TestAssertorPublishUserFlow:
    """Tests for _publish_user_assertions with mocked DB rows."""

    @pytest.fixture
    def mock_brotr(self) -> MagicMock:
        brotr = MagicMock()
        brotr.get_service_state = AsyncMock(return_value=[])
        brotr.upsert_service_state = AsyncMock()
        brotr.fetch = AsyncMock(return_value=[])
        return brotr

    def _make_service(self, mock_brotr: MagicMock) -> MagicMock:
        return _assertor_harness(
            mock_brotr,
            config=AssertorConfig(
                selection={
                    "kinds": [
                        EventKind.NIP85_USER_ASSERTION,
                        EventKind.NIP85_EVENT_ASSERTION,
                    ],
                    "batch_size": 100,
                    "top_topics": 5,
                },
                metrics={"enabled": False},
            ),
        )

    def _make_row(self, pubkey: str = "aa" * 32, post_count: int = 10) -> dict:
        return {
            "pubkey": pubkey,
            "rank": 42,
            "post_count": post_count,
            "reply_count": 0,
            "reaction_count_recd": 0,
            "reaction_count_sent": 0,
            "repost_count_recd": 0,
            "repost_count_sent": 0,
            "report_count_recd": 0,
            "report_count_sent": 0,
            "zap_count_recd": 0,
            "zap_count_sent": 0,
            "zap_amount_recd": 0,
            "zap_amount_sent": 0,
            "first_created_at": 1700000000,
            "last_event_at": 1710000000,
            "activity_hours": [0] * 24,
            "topic_counts": {},
            "follower_count": 0,
            "following_count": 0,
        }

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_user_rows", new_callable=AsyncMock)
    async def test_publishes_new_assertion(
        self,
        mock_fetch: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        mock_fetch.return_value = [self._make_row()]
        mock_broadcast.return_value = _broadcast_results()
        service = self._make_service(mock_brotr)

        published, skipped, failed = await service._publish_user_assertions()

        assert published == 1
        assert skipped == 0
        assert failed == 0
        mock_broadcast.assert_awaited_once()
        mock_brotr.upsert_service_state.assert_awaited_once()

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_user_rows", new_callable=AsyncMock)
    async def test_skips_unchanged(
        self,
        mock_fetch: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        row = self._make_row()
        mock_fetch.return_value = [row]
        service = self._make_service(mock_brotr)

        # Simulate existing hash matching
        from bigbrotr.nips.nip85.data import UserAssertion

        row["top_topics_limit"] = 5
        assertion = UserAssertion.from_db_row(row)
        state = MagicMock()
        state.state_value = {"hash": assertion.tags_hash()}
        mock_brotr.get_service_state = AsyncMock(return_value=[state])

        published, skipped, _failed = await service._publish_user_assertions()

        assert published == 0
        assert skipped == 1
        mock_broadcast.assert_not_awaited()

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_user_rows", new_callable=AsyncMock)
    async def test_broadcast_failure_counts_as_failed(
        self,
        mock_fetch: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        mock_fetch.return_value = [self._make_row()]
        mock_broadcast.return_value = _broadcast_results(
            successful_relays=(),
            failed_relays={"wss://relay.example": "timeout"},
        )
        service = self._make_service(mock_brotr)

        published, _skipped, failed = await service._publish_user_assertions()

        assert published == 0
        assert failed == 1
        mock_brotr.upsert_service_state.assert_not_awaited()
        service._logger.warning.assert_called_once_with(
            "user_assertion_failed",
            pubkey=self._make_row()["pubkey"],
            algorithm_id=service._config.algorithm_id,
            error="no relays accepted assertion",
            failed_relays={"wss://relay.example": "timeout"},
        )

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_user_rows", new_callable=AsyncMock)
    async def test_empty_batch_returns_zeros(
        self,
        mock_fetch: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        mock_fetch.return_value = []
        service = self._make_service(mock_brotr)

        published, skipped, failed = await service._publish_user_assertions()

        assert published == 0
        assert skipped == 0
        assert failed == 0
        mock_broadcast.assert_not_awaited()

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_user_rows", new_callable=AsyncMock)
    async def test_pagination_stops_on_partial_batch(
        self,
        mock_fetch: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        # Return fewer rows than batch_size -> should stop after first call
        mock_fetch.return_value = [self._make_row(pubkey=f"{i:02x}" * 32) for i in range(3)]
        mock_broadcast.return_value = _broadcast_results()
        service = self._make_service(mock_brotr)
        service._config.selection.batch_size = 100  # 3 < 100 = partial

        await service._publish_user_assertions()

        assert mock_fetch.await_count == 1

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_user_rows", new_callable=AsyncMock)
    async def test_user_pagination_full_batch(
        self,
        mock_fetch: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        batch = [self._make_row(pubkey=f"{i:02x}" * 32) for i in range(100)]
        mock_fetch.side_effect = [batch, []]
        mock_broadcast.return_value = _broadcast_results()
        service = self._make_service(mock_brotr)
        service._config.selection.batch_size = 100

        await service._publish_user_assertions()

        assert mock_fetch.await_count == 2

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_user_rows", new_callable=AsyncMock)
    async def test_os_error_during_publish_counts_as_failed(
        self,
        mock_fetch: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        mock_fetch.return_value = [self._make_row()]
        mock_broadcast.side_effect = OSError("connection lost")
        service = self._make_service(mock_brotr)

        published, _skipped, failed = await service._publish_user_assertions()

        assert published == 0
        assert failed == 1
        service._logger.error.assert_called_once()


class TestAssertorCheckpointNamespacing:
    """Verify checkpoint keys use the algorithm-aware namespace."""

    @pytest.fixture
    def mock_brotr(self) -> MagicMock:
        brotr = MagicMock()
        brotr.get_service_state = AsyncMock(return_value=[])
        brotr.upsert_service_state = AsyncMock()
        brotr.fetch = AsyncMock(return_value=[])
        return brotr

    def _make_service(self, mock_brotr: MagicMock) -> MagicMock:
        return _assertor_harness(
            mock_brotr,
            config=AssertorConfig(
                selection={
                    "kinds": [
                        EventKind.NIP85_USER_ASSERTION,
                        EventKind.NIP85_EVENT_ASSERTION,
                        EventKind.NIP85_ADDRESSABLE_ASSERTION,
                        EventKind.NIP85_IDENTIFIER_ASSERTION,
                    ],
                    "batch_size": 100,
                    "top_topics": 5,
                },
                metrics={"enabled": False},
            ),
        )

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_user_rows", new_callable=AsyncMock)
    async def test_user_assertion_uses_canonical_kind_key(
        self,
        mock_fetch: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        pubkey = "aa" * 32
        mock_fetch.return_value = [
            {
                "pubkey": pubkey,
                "post_count": 10,
                "reply_count": 0,
                "reaction_count_recd": 0,
                "reaction_count_sent": 0,
                "repost_count_recd": 0,
                "repost_count_sent": 0,
                "report_count_recd": 0,
                "report_count_sent": 0,
                "zap_count_recd": 0,
                "zap_count_sent": 0,
                "zap_amount_recd": 0,
                "zap_amount_sent": 0,
                "first_created_at": 1700000000,
                "last_event_at": 1710000000,
                "activity_hours": [0] * 24,
                "topic_counts": {},
                "follower_count": 0,
                "following_count": 0,
            }
        ]
        mock_broadcast.return_value = _broadcast_results()
        service = self._make_service(mock_brotr)

        await service._publish_user_assertions()

        mock_brotr.get_service_state.assert_awaited()
        key_arg = mock_brotr.get_service_state.call_args[0][2]
        assert key_arg == f"global-pagerank:30382:{pubkey}"

        upsert_call = mock_brotr.upsert_service_state.call_args[0][0]
        assert upsert_call[0].state_key == f"global-pagerank:30382:{pubkey}"

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_event_rows", new_callable=AsyncMock)
    async def test_event_assertion_uses_canonical_kind_key(
        self,
        mock_fetch: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        event_id = "bb" * 32
        mock_fetch.return_value = [
            {
                "event_id": event_id,
                "author_pubkey": "cc" * 32,
                "comment_count": 5,
                "quote_count": 0,
                "repost_count": 0,
                "reaction_count": 0,
                "zap_count": 0,
                "zap_amount": 0,
            }
        ]
        mock_broadcast.return_value = _broadcast_results()
        service = self._make_service(mock_brotr)

        await service._publish_event_assertions()

        key_arg = mock_brotr.get_service_state.call_args[0][2]
        assert key_arg == f"global-pagerank:30383:{event_id}"

        upsert_call = mock_brotr.upsert_service_state.call_args[0][0]
        assert upsert_call[0].state_key == f"global-pagerank:30383:{event_id}"

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_addressable_rows", new_callable=AsyncMock)
    async def test_addressable_assertion_uses_canonical_kind_key(
        self,
        mock_fetch: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        event_address = "30023:" + ("aa" * 32) + ":article"
        mock_fetch.return_value = [
            {
                "event_address": event_address,
                "author_pubkey": "bb" * 32,
                "rank": 61,
                "comment_count": 1,
                "quote_count": 0,
                "repost_count": 0,
                "reaction_count": 2,
                "zap_count": 0,
                "zap_amount": 0,
            }
        ]
        mock_broadcast.return_value = _broadcast_results()
        service = self._make_service(mock_brotr)

        await service._publish_addressable_assertions()

        key_arg = mock_brotr.get_service_state.call_args[0][2]
        assert key_arg == f"global-pagerank:30384:{event_address}"

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_identifier_rows", new_callable=AsyncMock)
    async def test_identifier_assertion_uses_canonical_kind_key(
        self,
        mock_fetch: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        identifier = "isbn:9780140328721"
        mock_fetch.return_value = [
            {
                "identifier": identifier,
                "rank": 73,
                "comment_count": 2,
                "reaction_count": 5,
                "k_tags": ["book"],
            }
        ]
        mock_broadcast.return_value = _broadcast_results()
        service = self._make_service(mock_brotr)

        await service._publish_identifier_assertions()

        key_arg = mock_brotr.get_service_state.call_args[0][2]
        assert key_arg == f"global-pagerank:30385:{identifier}"

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_event_rows", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_user_rows", new_callable=AsyncMock)
    async def test_same_hex_different_namespace_no_collision(
        self,
        mock_fetch_user: AsyncMock,
        mock_fetch_event: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        """A 64-char hex string used as both pubkey and event_id must not collide."""
        hex_id = "dd" * 32
        mock_fetch_user.return_value = [
            {
                "pubkey": hex_id,
                "post_count": 10,
                "reply_count": 0,
                "reaction_count_recd": 0,
                "reaction_count_sent": 0,
                "repost_count_recd": 0,
                "repost_count_sent": 0,
                "report_count_recd": 0,
                "report_count_sent": 0,
                "zap_count_recd": 0,
                "zap_count_sent": 0,
                "zap_amount_recd": 0,
                "zap_amount_sent": 0,
                "first_created_at": 1700000000,
                "last_event_at": 1710000000,
                "activity_hours": [0] * 24,
                "topic_counts": {},
                "follower_count": 0,
                "following_count": 0,
            }
        ]
        mock_fetch_event.return_value = [
            {
                "event_id": hex_id,
                "author_pubkey": "ee" * 32,
                "comment_count": 3,
                "quote_count": 0,
                "repost_count": 0,
                "reaction_count": 0,
                "zap_count": 0,
                "zap_amount": 0,
            }
        ]
        mock_broadcast.return_value = _broadcast_results()
        service = self._make_service(mock_brotr)

        from bigbrotr.models.constants import EventKind

        service._config.selection.kinds = [
            EventKind.NIP85_USER_ASSERTION,
            EventKind.NIP85_EVENT_ASSERTION,
        ]
        await service.run()

        saved_keys = [
            call[0][0][0].state_key for call in mock_brotr.upsert_service_state.call_args_list
        ]
        assert f"global-pagerank:30382:{hex_id}" in saved_keys
        assert f"global-pagerank:30383:{hex_id}" in saved_keys
        assert f"global-pagerank:30382:{hex_id}" != f"global-pagerank:30383:{hex_id}"


# ============================================================================
# Lifecycle tests (__aenter__, __aexit__, cleanup)
# ============================================================================


class TestAssertorLifecycle:
    async def test_aenter_creates_client_and_connects(
        self,
    ) -> None:
        from bigbrotr.services.assertor.service import Assertor

        mock_client = AsyncMock()
        mock_manager = MagicMock()
        mock_manager.connect_session = AsyncMock(return_value=_session_output(mock_client))
        with patch.object(Assertor, "__init__", lambda _self, *_a, **_kw: None):
            svc = Assertor.__new__(Assertor)
            svc._brotr = MagicMock()
            svc._brotr.get_service_state = AsyncMock(return_value=[])
            svc._brotr.delete_service_state = AsyncMock(return_value=0)
            svc._config = AssertorConfig()
            svc._client = None
            svc._client_manager = mock_manager
            svc._keys = svc._config.keys.keys
            svc._logger = MagicMock()
            svc._metrics_server = None

            with (
                patch.object(type(svc).__bases__[0], "__aenter__", new_callable=AsyncMock),
            ):
                result = await svc.__aenter__()

            assert svc._client is mock_client
            assert svc._client_manager is mock_manager
            mock_manager.connect_session.assert_awaited_once()
            assert result is svc

    async def test_aexit_shuts_down_client(self) -> None:
        from bigbrotr.services.assertor.service import Assertor

        with patch.object(Assertor, "__init__", lambda _self, *_a, **_kw: None):
            svc = Assertor.__new__(Assertor)
            svc._client = AsyncMock()
            svc._client_manager = MagicMock(disconnect=AsyncMock())
            svc._logger = MagicMock()

            with patch.object(type(svc).__bases__[0], "__aexit__", new_callable=AsyncMock):
                await svc.__aexit__(None, None, None)

            assert svc._client is None
            svc._client_manager.disconnect.assert_awaited_once()
            svc._logger.info.assert_any_call("client_disconnected")

    async def test_aexit_suppresses_ffi_shutdown_error(self) -> None:
        from bigbrotr.services.assertor.service import Assertor

        with patch.object(Assertor, "__init__", lambda _self, *_a, **_kw: None):
            svc = Assertor.__new__(Assertor)
            svc._client = AsyncMock()
            svc._config = AssertorConfig()
            svc._keys = svc._config.keys.keys
            svc._client_manager = NostrClientManager(keys=svc._keys)
            svc._client_manager._sessions["assertor-publish-relays"] = _session_output(svc._client)
            svc._logger = MagicMock()

            with (
                patch.object(type(svc).__bases__[0], "__aexit__", new_callable=AsyncMock),
                patch(
                    "bigbrotr.utils.protocol.shutdown_client",
                    new_callable=AsyncMock,
                    side_effect=RuntimeError("FFI error"),
                ),
            ):
                await svc.__aexit__(None, None, None)

            assert svc._client is None

    async def test_aexit_noop_when_client_is_none(self) -> None:
        from bigbrotr.services.assertor.service import Assertor

        with patch.object(Assertor, "__init__", lambda _self, *_a, **_kw: None):
            svc = Assertor.__new__(Assertor)
            svc._client = None
            svc._logger = MagicMock()

            with patch.object(type(svc).__bases__[0], "__aexit__", new_callable=AsyncMock):
                await svc.__aexit__(None, None, None)

            svc._logger.info.assert_not_called()

    async def test_cleanup_returns_zero(self) -> None:
        from bigbrotr.services.assertor.service import Assertor

        with patch.object(Assertor, "__init__", lambda _self, *_a, **_kw: None):
            svc = Assertor.__new__(Assertor)
            assert await svc.cleanup() == 0


class TestAssertorKeyLifecycle:
    @patch("bigbrotr.services.assertor.service.NostrClientManager")
    def test_init_uses_config_keys_to_create_client_manager(
        self,
        mock_manager_cls: MagicMock,
    ) -> None:
        config = AssertorConfig()
        svc = Assertor(brotr=MagicMock(), config=config)

        mock_manager_cls.assert_called_once_with(
            keys=config.keys.keys,
            allow_insecure=config.publishing.allow_insecure,
        )
        assert svc._client_manager is mock_manager_cls.return_value

    @patch("bigbrotr.services.assertor.service.NostrClientManager")
    def test_init_uses_generated_config_keys_when_env_missing(
        self,
        mock_manager_cls: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("NOSTR_PRIVATE_KEY_ASSERTOR", raising=False)
        svc = Assertor(brotr=MagicMock(), config=AssertorConfig())

        assert svc._keys is svc._config.keys.keys
        mock_manager_cls.assert_called_once_with(
            keys=svc._config.keys.keys,
            allow_insecure=svc._config.publishing.allow_insecure,
        )

    def test_parse_state_key_preserves_subject_colons(self) -> None:
        from bigbrotr.services.assertor.utils import parse_state_key

        assert parse_state_key("global-pagerank:30384:30023:" + ("aa" * 32) + ":article") == (
            "global-pagerank",
            30384,
            "30023:" + ("aa" * 32) + ":article",
        )


class TestAssertorUtils:
    def test_state_key_helpers(self) -> None:
        from bigbrotr.services.assertor.utils import build_state_key

        assert build_state_key(
            algorithm_id="global-pagerank",
            kind=30382,
            subject_id="aa" * 32,
        ) == "global-pagerank:30382:" + ("aa" * 32)

    def test_parse_state_key_rejects_invalid_keys(self) -> None:
        from bigbrotr.services.assertor.utils import parse_state_key

        assert parse_state_key("user:" + ("aa" * 32)) is None
        assert parse_state_key("global-pagerank:not-a-kind:subject") is None

    def test_content_hash_is_stable_for_json_key_order(self) -> None:
        from bigbrotr.services.assertor.utils import content_hash

        assert content_hash({"b": 2, "a": 1}) == content_hash({"a": 1, "b": 2})

    def test_provider_profile_content_merges_extra_fields_without_overrides(self) -> None:
        from bigbrotr.services.assertor.configs import ProviderProfileKind0Content
        from bigbrotr.services.assertor.utils import provider_profile_content

        content = provider_profile_content(
            algorithm_id="global-pagerank",
            kind0_content=ProviderProfileKind0Content(
                name="Provider",
                about="NIP-85 provider",
                website="https://bigbrotr.com",
                picture="https://bigbrotr.com/avatar.png",
                extra_fields={
                    "name": "ignored",
                    "algorithm_id": "ignored",
                    "software": "bigbrotr",
                    "hidden": None,
                },
            ),
        )

        assert content == {
            "name": "Provider",
            "about": "NIP-85 provider",
            "website": "https://bigbrotr.com",
            "algorithm_id": "global-pagerank",
            "picture": "https://bigbrotr.com/avatar.png",
            "software": "bigbrotr",
        }


class TestAssertorProviderProfile:
    @pytest.fixture
    def mock_brotr(self) -> MagicMock:
        brotr = MagicMock()
        brotr.get_service_state = AsyncMock(return_value=[])
        brotr.upsert_service_state = AsyncMock()
        brotr.delete_service_state = AsyncMock(return_value=0)
        return brotr

    def _make_service(self, mock_brotr: MagicMock) -> MagicMock:
        return _assertor_harness(
            mock_brotr,
            config=AssertorConfig(
                provider_profile={
                    "enabled": True,
                    "kind0_content": {
                        "name": "BigBrotr Global PageRank",
                        "about": "NIP-85 trusted assertion provider",
                        "website": "https://bigbrotr.com",
                    },
                },
                metrics={"enabled": False},
            ),
        )

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    async def test_publishes_provider_profile_when_content_changes(
        self,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        mock_broadcast.return_value = _broadcast_results()
        service = self._make_service(mock_brotr)

        published, skipped, failed = await service._publish_provider_profile()

        assert published == 1
        assert skipped == 0
        assert failed == 0
        saved_state = mock_brotr.upsert_service_state.call_args[0][0][0]
        assert saved_state.state_key == "global-pagerank:0:provider_profile"
        assert "global-pagerank:0:provider_profile" in service._cycle_seen_state_keys

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    async def test_skips_unchanged_provider_profile(
        self,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        service = self._make_service(mock_brotr)
        from bigbrotr.services.assertor.utils import content_hash, provider_profile_content

        state = MagicMock()
        state.state_value = {
            "hash": content_hash(
                provider_profile_content(
                    algorithm_id=service._config.algorithm_id,
                    kind0_content=service._config.provider_profile.kind0_content,
                )
            )
        }
        mock_brotr.get_service_state = AsyncMock(return_value=[state])

        published, skipped, failed = await service._publish_provider_profile()

        assert published == 0
        assert skipped == 1
        assert failed == 0
        mock_broadcast.assert_not_awaited()

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    async def test_provider_profile_publish_failure_when_no_relays_accept(
        self,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        mock_broadcast.return_value = _broadcast_results(
            successful_relays=(),
            failed_relays={"wss://relay.example": "timeout"},
        )
        service = self._make_service(mock_brotr)

        published, skipped, failed = await service._publish_provider_profile()

        assert (published, skipped, failed) == (0, 0, 1)
        mock_brotr.upsert_service_state.assert_not_awaited()
        service._logger.warning.assert_called_once_with(
            "provider_profile_publish_failed",
            algorithm_id=service._config.algorithm_id,
            error="no relays accepted provider profile",
            failed_relays={"wss://relay.example": "timeout"},
        )

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    async def test_provider_profile_publish_error_counts_as_failed(
        self,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        mock_broadcast.side_effect = OSError("relay disconnected")
        service = self._make_service(mock_brotr)

        published, skipped, failed = await service._publish_provider_profile()

        assert (published, skipped, failed) == (0, 0, 1)
        mock_brotr.upsert_service_state.assert_not_awaited()
        service._logger.error.assert_called_once()


class TestAssertorCheckpointCleanup:
    async def test_delete_stale_checkpoints_removes_only_current_algorithm_stale_keys(
        self,
    ) -> None:
        from bigbrotr.services.assertor.service import Assertor
        from bigbrotr.services.common.state_store import ServiceStateStore

        keep_key = "global-pagerank:30382:" + ("aa" * 32)
        stale_key = "global-pagerank:30382:" + ("bb" * 32)
        disabled_kind_key = "global-pagerank:30383:" + ("cc" * 32)
        other_algorithm_key = "other-algo:30382:" + ("dd" * 32)
        profile_key = "global-pagerank:0:provider_profile"
        noncanonical_key = "user:" + ("ee" * 32)

        def _state(key: str) -> MagicMock:
            state = MagicMock()
            state.service_name = ServiceName.ASSERTOR
            state.state_type = "checkpoint"
            state.state_key = key
            return state

        with patch.object(Assertor, "__init__", lambda _self, *_a, **_kw: None):
            svc = Assertor.__new__(Assertor)
            svc._brotr = MagicMock()
            svc._config = AssertorConfig(
                selection={"kinds": [30382]},
                provider_profile={
                    "enabled": True,
                    "kind0_content": {
                        "name": "BigBrotr Global PageRank",
                        "about": "NIP-85 trusted assertion provider",
                        "website": "https://bigbrotr.com",
                    },
                },
            )
            svc._logger = MagicMock()
            svc._state_store = ServiceStateStore(svc._brotr)
            svc._cycle_seen_state_keys = {keep_key, profile_key}

            with (
                patch.object(
                    ServiceStateStore,
                    "get",
                    AsyncMock(
                        return_value=[
                            _state(keep_key),
                            _state(stale_key),
                            _state(disabled_kind_key),
                            _state(other_algorithm_key),
                            _state(profile_key),
                            _state(noncanonical_key),
                        ]
                    ),
                ) as mock_get,
                patch.object(
                    ServiceStateStore,
                    "delete_states",
                    AsyncMock(return_value=3),
                ) as mock_delete,
            ):
                removed = await svc._delete_stale_checkpoints()

            assert removed == 3
            mock_get.assert_awaited_once_with(ServiceName.ASSERTOR, ServiceStateType.CHECKPOINT)
            deleted_states = mock_delete.await_args.args[0]
            deleted_keys = [state.state_key for state in deleted_states]
            assert deleted_keys == [stale_key, disabled_kind_key, noncanonical_key]


# ============================================================================
# Event assertion publish flow tests
# ============================================================================


class TestAssertorPublishEventFlow:
    @pytest.fixture
    def mock_brotr(self) -> MagicMock:
        brotr = MagicMock()
        brotr.get_service_state = AsyncMock(return_value=[])
        brotr.upsert_service_state = AsyncMock()
        brotr.fetch = AsyncMock(return_value=[])
        return brotr

    def _make_service(self, mock_brotr: MagicMock) -> MagicMock:
        return _assertor_harness(
            mock_brotr,
            config=AssertorConfig(
                selection={
                    "kinds": [
                        EventKind.NIP85_USER_ASSERTION,
                        EventKind.NIP85_EVENT_ASSERTION,
                    ],
                    "batch_size": 100,
                    "top_topics": 5,
                },
                metrics={"enabled": False},
            ),
        )

    def _make_event_row(self, event_id: str = "ee" * 32) -> dict:
        return {
            "event_id": event_id,
            "author_pubkey": "ff" * 32,
            "rank": 88,
            "comment_count": 5,
            "quote_count": 2,
            "repost_count": 1,
            "reaction_count": 3,
            "zap_count": 0,
            "zap_amount": 0,
        }

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_event_rows", new_callable=AsyncMock)
    async def test_publishes_new_event_assertion(
        self,
        mock_fetch: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        mock_fetch.return_value = [self._make_event_row()]
        mock_broadcast.return_value = _broadcast_results()
        service = self._make_service(mock_brotr)

        published, skipped, failed = await service._publish_event_assertions()

        assert published == 1
        assert skipped == 0
        assert failed == 0
        mock_broadcast.assert_awaited_once()
        mock_brotr.upsert_service_state.assert_awaited_once()

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_event_rows", new_callable=AsyncMock)
    async def test_skips_unchanged_event(
        self,
        mock_fetch: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        row = self._make_event_row()
        mock_fetch.return_value = [row]
        service = self._make_service(mock_brotr)

        from bigbrotr.nips.nip85.data import EventAssertion

        assertion = EventAssertion.from_db_row(row)
        state = MagicMock()
        state.state_value = {"hash": assertion.tags_hash()}
        mock_brotr.get_service_state = AsyncMock(return_value=[state])

        published, skipped, _failed = await service._publish_event_assertions()

        assert published == 0
        assert skipped == 1
        mock_broadcast.assert_not_awaited()

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_event_rows", new_callable=AsyncMock)
    async def test_event_broadcast_failure_counts_as_failed(
        self,
        mock_fetch: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        mock_fetch.return_value = [self._make_event_row()]
        mock_broadcast.return_value = _broadcast_results(
            successful_relays=(),
            failed_relays={"wss://relay.example": "timeout"},
        )
        service = self._make_service(mock_brotr)

        published, _skipped, failed = await service._publish_event_assertions()

        assert published == 0
        assert failed == 1
        service._logger.warning.assert_called_once_with(
            "event_assertion_failed",
            event_id=self._make_event_row()["event_id"],
            algorithm_id=service._config.algorithm_id,
            error="no relays accepted assertion",
            failed_relays={"wss://relay.example": "timeout"},
        )

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_event_rows", new_callable=AsyncMock)
    async def test_event_os_error_counts_as_failed(
        self,
        mock_fetch: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        mock_fetch.return_value = [self._make_event_row()]
        mock_broadcast.side_effect = OSError("connection lost")
        service = self._make_service(mock_brotr)

        published, _skipped, failed = await service._publish_event_assertions()

        assert published == 0
        assert failed == 1
        service._logger.error.assert_called_once()

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_event_rows", new_callable=AsyncMock)
    async def test_event_pagination_full_batch(
        self,
        mock_fetch: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        batch = [self._make_event_row(event_id=f"{i:02x}" * 32) for i in range(100)]
        mock_fetch.side_effect = [batch, []]
        mock_broadcast.return_value = _broadcast_results()
        service = self._make_service(mock_brotr)
        service._config.selection.batch_size = 100

        await service._publish_event_assertions()

        assert mock_fetch.await_count == 2

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_event_rows", new_callable=AsyncMock)
    async def test_event_empty_returns_zeros(
        self,
        mock_fetch: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        mock_fetch.return_value = []
        service = self._make_service(mock_brotr)

        published, skipped, failed = await service._publish_event_assertions()

        assert published == 0
        assert skipped == 0
        assert failed == 0

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_event_rows", new_callable=AsyncMock)
    async def test_event_postgres_error_counts_as_failed(
        self,
        mock_fetch: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        mock_fetch.return_value = [self._make_event_row()]
        mock_broadcast.side_effect = asyncpg.PostgresError("query error")
        service = self._make_service(mock_brotr)

        published, _skipped, failed = await service._publish_event_assertions()

        assert published == 0
        assert failed == 1


class TestAssertorPublishAddressableAndIdentifierFlow:
    @pytest.fixture
    def mock_brotr(self) -> MagicMock:
        brotr = MagicMock()
        brotr.get_service_state = AsyncMock(return_value=[])
        brotr.upsert_service_state = AsyncMock()
        brotr.fetch = AsyncMock(return_value=[])
        return brotr

    def _make_service(self, mock_brotr: MagicMock) -> MagicMock:
        return _assertor_harness(
            mock_brotr,
            config=AssertorConfig(
                selection={
                    "kinds": [
                        EventKind.NIP85_ADDRESSABLE_ASSERTION,
                        EventKind.NIP85_IDENTIFIER_ASSERTION,
                    ],
                    "batch_size": 100,
                },
                metrics={"enabled": False},
            ),
        )

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_addressable_rows", new_callable=AsyncMock)
    async def test_publishes_new_addressable_assertion(
        self,
        mock_fetch: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        mock_fetch.return_value = [
            {
                "event_address": "30023:" + ("aa" * 32) + ":article",
                "author_pubkey": "bb" * 32,
                "rank": 81,
                "comment_count": 5,
                "quote_count": 1,
                "repost_count": 2,
                "reaction_count": 3,
                "zap_count": 1,
                "zap_amount": 21000,
            }
        ]
        mock_broadcast.return_value = _broadcast_results()
        service = self._make_service(mock_brotr)

        published, skipped, failed = await service._publish_addressable_assertions()

        assert published == 1
        assert skipped == 0
        assert failed == 0
        mock_broadcast.assert_awaited_once()
        saved_key = mock_brotr.upsert_service_state.call_args[0][0][0].state_key
        assert saved_key.startswith("global-pagerank:30384:")

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_identifier_rows", new_callable=AsyncMock)
    async def test_publishes_new_identifier_assertion(
        self,
        mock_fetch: AsyncMock,
        mock_broadcast: AsyncMock,
        mock_brotr: MagicMock,
    ) -> None:
        mock_fetch.return_value = [
            {
                "identifier": "isbn:9780140328721",
                "rank": 66,
                "comment_count": 4,
                "reaction_count": 7,
                "k_tags": ["book", "isbn"],
            }
        ]
        mock_broadcast.return_value = _broadcast_results()
        service = self._make_service(mock_brotr)

        published, skipped, failed = await service._publish_identifier_assertions()

        assert published == 1
        assert skipped == 0
        assert failed == 0
        mock_broadcast.assert_awaited_once()
        saved_key = mock_brotr.upsert_service_state.call_args[0][0][0].state_key
        assert saved_key == "global-pagerank:30385:isbn:9780140328721"


# ============================================================================
# Query function tests
# ============================================================================


class TestAssertorQueries:
    async def test_fetch_user_rows(self) -> None:
        from bigbrotr.services.assertor.queries import fetch_user_rows

        mock_brotr = MagicMock()
        mock_brotr.fetch = AsyncMock(return_value=[{"pubkey": "aa" * 32}])

        rows = await fetch_user_rows(
            mock_brotr,
            algorithm_id="global-pagerank",
            min_events=1,
            limit=10,
            offset=0,
        )
        assert len(rows) == 1
        mock_brotr.fetch.assert_awaited_once()

    async def test_fetch_event_rows(self) -> None:
        from bigbrotr.services.assertor.queries import fetch_event_rows

        mock_brotr = MagicMock()
        mock_brotr.fetch = AsyncMock(return_value=[{"event_id": "bb" * 32}])

        rows = await fetch_event_rows(
            mock_brotr,
            algorithm_id="global-pagerank",
            limit=10,
            offset=0,
        )
        assert len(rows) == 1
        mock_brotr.fetch.assert_awaited_once()

    async def test_fetch_addressable_rows(self) -> None:
        from bigbrotr.services.assertor.queries import fetch_addressable_rows

        mock_brotr = MagicMock()
        mock_brotr.fetch = AsyncMock(return_value=[{"event_address": "30023:" + ("aa" * 32)}])

        rows = await fetch_addressable_rows(
            mock_brotr,
            algorithm_id="global-pagerank",
            limit=10,
            offset=0,
        )
        assert len(rows) == 1
        mock_brotr.fetch.assert_awaited_once()

    async def test_fetch_identifier_rows(self) -> None:
        from bigbrotr.services.assertor.queries import fetch_identifier_rows

        mock_brotr = MagicMock()
        mock_brotr.fetch = AsyncMock(return_value=[{"identifier": "isbn:9780140328721"}])

        rows = await fetch_identifier_rows(
            mock_brotr,
            algorithm_id="global-pagerank",
            limit=10,
            offset=0,
        )
        assert len(rows) == 1
        mock_brotr.fetch.assert_awaited_once()


# ============================================================================
# Run method event assertion branch
# ============================================================================


class TestAssertorRunEventBranch:
    async def test_run_event_assertions_only(self) -> None:
        brotr = MagicMock()
        brotr.get_service_state = AsyncMock(return_value=[])
        brotr.delete_service_state = AsyncMock(return_value=0)
        service = _assertor_harness(
            brotr,
            config=AssertorConfig(
                selection={"kinds": [EventKind.NIP85_EVENT_ASSERTION]},
                metrics={"enabled": False},
            ),
        )

        service._publish_user_assertions = AsyncMock(return_value=(0, 0, 0))
        service._publish_event_assertions = AsyncMock(return_value=(3, 1, 0))

        await service.run()

        service._publish_user_assertions.assert_not_awaited()
        service._publish_event_assertions.assert_awaited_once()
        service.set_gauge.assert_any_call("assertions_published", 3)

    async def test_run_both_kinds(self) -> None:
        brotr = MagicMock()
        brotr.get_service_state = AsyncMock(return_value=[])
        brotr.delete_service_state = AsyncMock(return_value=0)
        service = _assertor_harness(
            brotr,
            config=AssertorConfig(
                selection={
                    "kinds": [
                        EventKind.NIP85_USER_ASSERTION,
                        EventKind.NIP85_EVENT_ASSERTION,
                    ]
                },
                metrics={"enabled": False},
            ),
        )

        service._publish_user_assertions = AsyncMock(return_value=(2, 0, 0))
        service._publish_event_assertions = AsyncMock(return_value=(1, 0, 0))
        service._publish_addressable_assertions = AsyncMock(return_value=(0, 0, 0))
        service._publish_identifier_assertions = AsyncMock(return_value=(0, 0, 0))

        await service.run()

        service._publish_user_assertions.assert_awaited_once()
        service._publish_event_assertions.assert_awaited_once()
        service.set_gauge.assert_any_call("assertions_published", 3)

    async def test_run_addressable_and_identifier_kinds(self) -> None:
        brotr = MagicMock()
        brotr.get_service_state = AsyncMock(return_value=[])
        brotr.delete_service_state = AsyncMock(return_value=0)
        service = _assertor_harness(
            brotr,
            config=AssertorConfig(
                selection={
                    "kinds": [
                        EventKind.NIP85_ADDRESSABLE_ASSERTION,
                        EventKind.NIP85_IDENTIFIER_ASSERTION,
                    ]
                },
                metrics={"enabled": False},
            ),
        )

        service._publish_user_assertions = AsyncMock(return_value=(0, 0, 0))
        service._publish_event_assertions = AsyncMock(return_value=(0, 0, 0))
        service._publish_addressable_assertions = AsyncMock(return_value=(4, 1, 0))
        service._publish_identifier_assertions = AsyncMock(return_value=(2, 0, 1))

        await service.run()

        service._publish_user_assertions.assert_not_awaited()
        service._publish_event_assertions.assert_not_awaited()
        service._publish_addressable_assertions.assert_awaited_once()
        service._publish_identifier_assertions.assert_awaited_once()
        service.set_gauge.assert_any_call("assertions_published", 6)
        service.set_gauge.assert_any_call("assertions_skipped", 1)
        service.set_gauge.assert_any_call("assertions_failed", 1)
