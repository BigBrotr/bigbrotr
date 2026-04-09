"""Integration tests for the Assertor service."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nostr_sdk import Event as NostrEvent

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import EventRelay, Relay
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.event import Event
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.assertor.configs import AssertorConfig
from bigbrotr.services.assertor.service import Assertor


pytestmark = pytest.mark.integration

VALID_HEX_KEY = (
    "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"  # pragma: allowlist secret
)


def _event_relay(
    event_id: str,
    relay_url: str,
    *,
    kind: int = 1,
    pubkey: str = "bb" * 32,
    created_at: int = 1_700_000_000,
    tags: list[list[str]] | None = None,
) -> EventRelay:
    mock = _make_mock_event(
        event_id=event_id,
        pubkey=pubkey,
        kind=kind,
        created_at=created_at,
        sig="ee" * 64,
        tags=tags or [],
    )
    relay = Relay(relay_url, discovered_at=1_700_000_000)
    return EventRelay(event=Event(mock), relay=relay, seen_at=created_at + 1)


def _make_mock_event(
    *,
    event_id: str,
    pubkey: str,
    created_at: int,
    kind: int,
    tags: list[list[str]],
    sig: str,
    content: str = "Test content",
) -> MagicMock:
    """Create a mock Nostr event compatible with the Event model."""
    mock_event = MagicMock(spec=NostrEvent)
    mock_event.id.return_value.to_hex.return_value = event_id
    mock_event.author.return_value.to_hex.return_value = pubkey
    mock_event.created_at.return_value.as_secs.return_value = created_at
    mock_event.kind.return_value.as_u16.return_value = kind
    mock_event.content.return_value = content
    mock_event.signature.return_value = sig
    mock_event.verify.return_value = True

    mock_tags = []
    for tag in tags:
        mock_tag = MagicMock()
        mock_tag.as_vec.return_value = tag
        mock_tags.append(mock_tag)
    mock_event.tags.return_value.to_vec.return_value = mock_tags

    return mock_event


async def _refresh_assertor_facts(brotr: Brotr, after: int = 0, until: int = 2_000_000_000) -> None:
    """Refresh the summary tables the Assertor reads from."""
    for table in (
        "pubkey_kind_stats",
        "pubkey_relay_stats",
        "relay_kind_stats",
        "pubkey_stats",
        "kind_stats",
        "relay_stats",
        "nip85_pubkey_stats",
        "nip85_event_stats",
        "nip85_addressable_stats",
        "nip85_identifier_stats",
    ):
        await brotr.fetchval(f"SELECT {table}_refresh($1::BIGINT, $2::BIGINT)", after, until)


class TestAssertorIntegration:
    async def test_assertor_v2_run_purges_legacy_and_cleans_stale_checkpoints(
        self,
        brotr: Brotr,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("NOSTR_PRIVATE_KEY_ASSERTOR", VALID_HEX_KEY)

        author = "c1" * 32
        replier = "d1" * 32
        root_event_id = "a0" * 32
        reply_event_id = "a1" * 32
        relay_url = "wss://assertor.example.com"

        await brotr.insert_event_relay(
            [
                _event_relay(
                    root_event_id,
                    relay_url,
                    pubkey=author,
                    created_at=1_700_000_000,
                    tags=[],
                ),
                _event_relay(
                    reply_event_id,
                    relay_url,
                    pubkey=replier,
                    created_at=1_700_000_100,
                    tags=[["e", root_event_id], ["p", author]],
                ),
            ],
            cascade=True,
        )
        await _refresh_assertor_facts(brotr)

        legacy_user_key = f"user:{author}"
        legacy_event_key = f"event:{root_event_id}"
        stale_user_key = f"v2:global-pagerank-v1:30382:{'ef' * 32}"
        stale_event_key = f"v2:global-pagerank-v1:30383:{'fe' * 32}"
        other_algorithm_key = f"v2:other-algo:30382:{'ab' * 32}"

        await brotr.upsert_service_state(
            [
                ServiceState(
                    service_name=ServiceName.ASSERTOR,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key=legacy_user_key,
                    state_value={"hash": "legacy-user", "timestamp": 1},
                ),
                ServiceState(
                    service_name=ServiceName.ASSERTOR,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key=legacy_event_key,
                    state_value={"hash": "legacy-event", "timestamp": 2},
                ),
                ServiceState(
                    service_name=ServiceName.ASSERTOR,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key=stale_user_key,
                    state_value={"hash": "stale-user", "timestamp": 3},
                ),
                ServiceState(
                    service_name=ServiceName.ASSERTOR,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key=stale_event_key,
                    state_value={"hash": "stale-event", "timestamp": 4},
                ),
                ServiceState(
                    service_name=ServiceName.ASSERTOR,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key=other_algorithm_key,
                    state_value={"hash": "other-algo", "timestamp": 5},
                ),
            ]
        )

        config = AssertorConfig.model_validate(
            {
                "algorithm_id": "global-pagerank-v1",
                "keys": {"keys_env": "NOSTR_PRIVATE_KEY_ASSERTOR"},
                "relays": ["wss://relay.damus.io"],
                "min_events": 1,
                "batch_size": 100,
                "metrics": {"enabled": False},
                "provider_profile": {
                    "enabled": True,
                    "kind0_content": {
                        "name": "BigBrotr Global PageRank v1",
                        "about": "NIP-85 trusted assertion provider",
                        "website": "https://bigbrotr.com",
                        "extra_fields": {"algorithm_version": "v1"},
                    },
                },
            }
        )

        client = MagicMock()
        client.add_relay = AsyncMock()
        client.connect = AsyncMock()
        client.unsubscribe_all = AsyncMock()
        client.force_remove_all_relays = AsyncMock()
        client.shutdown = AsyncMock()
        client.database = MagicMock(return_value=SimpleNamespace(wipe=AsyncMock()))

        with (
            patch(
                "bigbrotr.services.assertor.service.create_client",
                new=AsyncMock(return_value=client),
            ),
            patch(
                "bigbrotr.services.assertor.service.broadcast_events",
                new=AsyncMock(return_value=1),
            ),
        ):
            async with Assertor(brotr=brotr, config=config) as service:
                rows_after_enter = await brotr.get_service_state(
                    ServiceName.ASSERTOR,
                    ServiceStateType.CHECKPOINT,
                )
                keys_after_enter = {row.state_key for row in rows_after_enter}

                assert legacy_user_key not in keys_after_enter
                assert legacy_event_key not in keys_after_enter
                assert stale_user_key in keys_after_enter
                assert stale_event_key in keys_after_enter
                assert other_algorithm_key in keys_after_enter

                await service.run()

        rows_after_run = await brotr.get_service_state(
            ServiceName.ASSERTOR,
            ServiceStateType.CHECKPOINT,
        )
        state_by_key = {row.state_key: row for row in rows_after_run}

        user_key = f"v2:global-pagerank-v1:30382:{author}"
        event_key = f"v2:global-pagerank-v1:30383:{root_event_id}"
        profile_key = "v2:global-pagerank-v1:0:provider_profile"

        assert user_key in state_by_key
        assert event_key in state_by_key
        assert profile_key in state_by_key
        assert stale_user_key not in state_by_key
        assert stale_event_key not in state_by_key
        assert other_algorithm_key in state_by_key
        assert not any(key.startswith("user:") for key in state_by_key)
        assert not any(key.startswith("event:") for key in state_by_key)

        for key in (user_key, event_key, profile_key):
            assert "hash" in state_by_key[key].state_value
            assert state_by_key[key].state_value["timestamp"] > 0
