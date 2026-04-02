"""Tests for the Assertor service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from bigbrotr.models.constants import EventKind, ServiceName
from bigbrotr.services.assertor.configs import AssertorConfig


VALID_HEX_KEY = (
    "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"  # pragma: allowlist secret
)


@pytest.fixture(autouse=True)
def _set_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOSTR_PRIVATE_KEY", VALID_HEX_KEY)


class TestAssertorConfig:
    def test_defaults(self) -> None:
        config = AssertorConfig()
        assert config.interval == 3600.0
        assert config.batch_size == 500
        assert config.min_events == 1
        assert config.top_topics == 5
        assert len(config.relays) == 3
        assert config.kinds == [30382, 30383]
        assert config.allow_insecure is False

    def test_custom_values(
        self,
    ) -> None:
        config = AssertorConfig(
            batch_size=100,
            min_events=10,
            top_topics=3,
            kinds=[30382],
        )
        assert config.batch_size == 100
        assert config.min_events == 10
        assert config.top_topics == 3
        assert config.kinds == [30382]

    def test_batch_size_validation(
        self,
    ) -> None:
        with pytest.raises(ValidationError):
            AssertorConfig(batch_size=0)

    def test_kinds_must_not_be_empty(
        self,
    ) -> None:
        with pytest.raises(ValidationError):
            AssertorConfig(kinds=[])

    def test_relays_must_not_be_empty(
        self,
    ) -> None:
        with pytest.raises(ValidationError):
            AssertorConfig(relays=[])


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

    async def test_run_no_client_returns_early(self, mock_brotr: MagicMock) -> None:
        from bigbrotr.services.assertor.service import Assertor

        with patch.object(Assertor, "__init__", lambda _self, *_a, **_kw: None):
            service = Assertor.__new__(Assertor)
            service._client = None
            service._config = MagicMock()
            service._logger = MagicMock()
            service.set_gauge = MagicMock()
            await service.run()
            service.set_gauge.assert_not_called()

    async def test_run_publishes_user_assertions(self, mock_brotr: MagicMock) -> None:
        from bigbrotr.services.assertor.service import Assertor

        with patch.object(Assertor, "__init__", lambda _self, *_a, **_kw: None):
            service = Assertor.__new__(Assertor)
            service._client = MagicMock()
            service._config = MagicMock()
            service._config.kinds = [EventKind.NIP85_USER_ASSERTION]
            service._brotr = mock_brotr
            service._logger = MagicMock()
            service.set_gauge = MagicMock()

            service._publish_user_assertions = AsyncMock(return_value=(5, 2, 1))
            service._publish_event_assertions = AsyncMock(return_value=(0, 0, 0))

            await service.run()

            service._publish_user_assertions.assert_awaited_once()
            service.set_gauge.assert_any_call("assertions_published", 5)
            service.set_gauge.assert_any_call("assertions_skipped", 2)
            service.set_gauge.assert_any_call("assertions_failed", 1)

    async def test_is_unchanged_no_state(self, mock_brotr: MagicMock) -> None:
        from bigbrotr.services.assertor.service import Assertor

        with patch.object(Assertor, "__init__", lambda _self, *_a, **_kw: None):
            service = Assertor.__new__(Assertor)
            service._brotr = mock_brotr
            mock_brotr.get_service_state = AsyncMock(return_value=[])

            result = await service._is_unchanged("test_pubkey", "abc123")
            assert result is False

    async def test_is_unchanged_same_hash(self, mock_brotr: MagicMock) -> None:
        from bigbrotr.services.assertor.service import Assertor

        with patch.object(Assertor, "__init__", lambda _self, *_a, **_kw: None):
            service = Assertor.__new__(Assertor)
            service._brotr = mock_brotr

            state = MagicMock()
            state.state_value = {"hash": "abc123", "timestamp": 1234}
            mock_brotr.get_service_state = AsyncMock(return_value=[state])

            result = await service._is_unchanged("test_pubkey", "abc123")
            assert result is True

    async def test_is_unchanged_different_hash(self, mock_brotr: MagicMock) -> None:
        from bigbrotr.services.assertor.service import Assertor

        with patch.object(Assertor, "__init__", lambda _self, *_a, **_kw: None):
            service = Assertor.__new__(Assertor)
            service._brotr = mock_brotr

            state = MagicMock()
            state.state_value = {"hash": "old_hash", "timestamp": 1234}
            mock_brotr.get_service_state = AsyncMock(return_value=[state])

            result = await service._is_unchanged("test_pubkey", "new_hash")
            assert result is False

    async def test_save_hash_calls_upsert(self, mock_brotr: MagicMock) -> None:
        from bigbrotr.services.assertor.service import Assertor

        with patch.object(Assertor, "__init__", lambda _self, *_a, **_kw: None):
            service = Assertor.__new__(Assertor)
            service._brotr = mock_brotr

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
        from bigbrotr.services.assertor.service import Assertor

        service = Assertor.__new__(Assertor)
        service._brotr = mock_brotr
        service._client = MagicMock()
        service._config = MagicMock()
        service._config.min_events = 1
        service._config.batch_size = 100
        service._config.top_topics = 5
        service._logger = MagicMock()
        return service

    def _make_row(self, pubkey: str = "aa" * 32, post_count: int = 10) -> dict:
        return {
            "pubkey": pubkey,
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
        mock_broadcast.return_value = 1
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
        mock_broadcast.return_value = 0  # No relays accepted
        service = self._make_service(mock_brotr)

        published, _skipped, failed = await service._publish_user_assertions()

        assert published == 0
        assert failed == 1
        mock_brotr.upsert_service_state.assert_not_awaited()

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
        mock_broadcast.return_value = 1
        service = self._make_service(mock_brotr)
        service._config.batch_size = 100  # 3 < 100 = partial

        await service._publish_user_assertions()

        assert mock_fetch.await_count == 1

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
    """Verify checkpoint keys use 'user:' and 'event:' prefixes to prevent collisions."""

    @pytest.fixture
    def mock_brotr(self) -> MagicMock:
        brotr = MagicMock()
        brotr.get_service_state = AsyncMock(return_value=[])
        brotr.upsert_service_state = AsyncMock()
        brotr.fetch = AsyncMock(return_value=[])
        return brotr

    def _make_service(self, mock_brotr: MagicMock) -> MagicMock:
        from bigbrotr.services.assertor.service import Assertor

        service = Assertor.__new__(Assertor)
        service._brotr = mock_brotr
        service._client = MagicMock()
        service._config = MagicMock()
        service._config.min_events = 1
        service._config.batch_size = 100
        service._config.top_topics = 5
        service._logger = MagicMock()
        return service

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_user_rows", new_callable=AsyncMock)
    async def test_user_assertion_uses_user_prefix(
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
        mock_broadcast.return_value = 1
        service = self._make_service(mock_brotr)

        await service._publish_user_assertions()

        # _is_unchanged called with user: prefix
        mock_brotr.get_service_state.assert_awaited()
        key_arg = mock_brotr.get_service_state.call_args[0][2]
        assert key_arg == f"user:{pubkey}"

        # _save_hash called with user: prefix
        upsert_call = mock_brotr.upsert_service_state.call_args[0][0]
        assert upsert_call[0].state_key == f"user:{pubkey}"

    @patch("bigbrotr.services.assertor.service.broadcast_events", new_callable=AsyncMock)
    @patch("bigbrotr.services.assertor.service.fetch_event_rows", new_callable=AsyncMock)
    async def test_event_assertion_uses_event_prefix(
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
        mock_broadcast.return_value = 1
        service = self._make_service(mock_brotr)

        await service._publish_event_assertions()

        key_arg = mock_brotr.get_service_state.call_args[0][2]
        assert key_arg == f"event:{event_id}"

        upsert_call = mock_brotr.upsert_service_state.call_args[0][0]
        assert upsert_call[0].state_key == f"event:{event_id}"

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
        mock_broadcast.return_value = 1
        service = self._make_service(mock_brotr)

        from bigbrotr.models.constants import EventKind

        service._config.kinds = [
            EventKind.NIP85_USER_ASSERTION,
            EventKind.NIP85_EVENT_ASSERTION,
        ]
        await service.run()

        saved_keys = [
            call[0][0][0].state_key for call in mock_brotr.upsert_service_state.call_args_list
        ]
        assert f"user:{hex_id}" in saved_keys
        assert f"event:{hex_id}" in saved_keys
        assert f"user:{hex_id}" != f"event:{hex_id}"
