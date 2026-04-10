"""Integration tests for the Assertor service."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nostr_sdk import Event as NostrEvent

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import EventRelay, Relay
from bigbrotr.models.constants import EventKind, ServiceName
from bigbrotr.models.event import Event
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.assertor.configs import AssertorConfig
from bigbrotr.services.assertor.service import Assertor


pytestmark = pytest.mark.integration

VALID_HEX_KEY = (
    "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"  # pragma: allowlist secret
)

_RANK_INSERT_QUERIES = {
    "nip85_pubkey_ranks": """
        INSERT INTO nip85_pubkey_ranks (algorithm_id, subject_id, raw_score, rank, computed_at)
        VALUES ($1, $2, $3, $4, $5)
    """,
    "nip85_event_ranks": """
        INSERT INTO nip85_event_ranks (algorithm_id, subject_id, raw_score, rank, computed_at)
        VALUES ($1, $2, $3, $4, $5)
    """,
    "nip85_addressable_ranks": """
        INSERT INTO nip85_addressable_ranks (algorithm_id, subject_id, raw_score, rank, computed_at)
        VALUES ($1, $2, $3, $4, $5)
    """,
    "nip85_identifier_ranks": """
        INSERT INTO nip85_identifier_ranks (algorithm_id, subject_id, raw_score, rank, computed_at)
        VALUES ($1, $2, $3, $4, $5)
    """,
}


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


async def _seed_addressable_stats(
    *,
    brotr: Brotr,
    event_address: str,
    author_pubkey: str,
    comment_count: int,
    quote_count: int,
    repost_count: int,
    reaction_count: int,
    zap_count: int,
    zap_amount: int,
) -> None:
    await brotr.execute(
        """
        INSERT INTO nip85_addressable_stats (
            event_address,
            author_pubkey,
            comment_count,
            quote_count,
            repost_count,
            reaction_count,
            zap_count,
            zap_amount
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        event_address,
        author_pubkey,
        comment_count,
        quote_count,
        repost_count,
        reaction_count,
        zap_count,
        zap_amount,
    )


async def _seed_identifier_stats(
    *,
    brotr: Brotr,
    identifier: str,
    comment_count: int,
    reaction_count: int,
    k_tags: list[str],
) -> None:
    await brotr.execute(
        """
        INSERT INTO nip85_identifier_stats (identifier, comment_count, reaction_count, k_tags)
        VALUES ($1, $2, $3, $4::TEXT[])
        """,
        identifier,
        comment_count,
        reaction_count,
        k_tags,
    )


async def _seed_rank_row(
    *,
    brotr: Brotr,
    table_name: str,
    algorithm_id: str,
    subject_id: str,
    raw_score: float,
    rank: int,
    computed_at: int,
) -> None:
    assert table_name in _RANK_INSERT_QUERIES
    await brotr.execute(
        _RANK_INSERT_QUERIES[table_name],
        algorithm_id,
        subject_id,
        raw_score,
        rank,
        computed_at,
    )


def _tag_values(event: Any, tag_name: str) -> list[str]:
    tags: list[str] = []
    for tag in event.tags().to_vec():
        vec = tag.as_vec()
        if vec and vec[0] == tag_name and len(vec) > 1:
            tags.append(vec[1])
    return tags


def _checkpoint_state(*, state_key: str, hash_value: str, timestamp: int) -> ServiceState:
    return ServiceState(
        service_name=ServiceName.ASSERTOR,
        state_type=ServiceStateType.CHECKPOINT,
        state_key=state_key,
        state_value={"hash": hash_value, "timestamp": timestamp},
    )


async def _seed_full_kind_assertor_data(
    *,
    brotr: Brotr,
    algorithm_id: str,
    author: str,
    replier: str,
    root_event_id: str,
    reply_event_id: str,
    event_address: str,
    identifier: str,
    relay_url: str,
) -> None:
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
    await _seed_addressable_stats(
        brotr=brotr,
        event_address=event_address,
        author_pubkey=author,
        comment_count=2,
        quote_count=1,
        repost_count=0,
        reaction_count=4,
        zap_count=1,
        zap_amount=2000,
    )
    await _seed_identifier_stats(
        brotr=brotr,
        identifier=identifier,
        comment_count=3,
        reaction_count=5,
        k_tags=["book", "isbn"],
    )
    for table_name, subject_id, raw_score, rank in (
        ("nip85_pubkey_ranks", author, 0.41, 89),
        ("nip85_event_ranks", root_event_id, 7.30, 81),
        ("nip85_addressable_ranks", event_address, 8.70, 84),
        ("nip85_identifier_ranks", identifier, 5.20, 73),
    ):
        await _seed_rank_row(
            brotr=brotr,
            table_name=table_name,
            algorithm_id=algorithm_id,
            subject_id=subject_id,
            raw_score=raw_score,
            rank=rank,
            computed_at=1_700_000_200,
        )


async def _seed_checkpoint_states(
    *,
    brotr: Brotr,
    noncanonical_user_key: str,
    noncanonical_event_key: str,
    stale_user_key: str,
    stale_event_key: str,
    stale_addressable_key: str,
    stale_identifier_key: str,
    other_algorithm_key: str,
) -> None:
    await brotr.upsert_service_state(
        [
            _checkpoint_state(
                state_key=noncanonical_user_key,
                hash_value="noncanonical-user",
                timestamp=1,
            ),
            _checkpoint_state(
                state_key=noncanonical_event_key,
                hash_value="noncanonical-event",
                timestamp=2,
            ),
            _checkpoint_state(state_key=stale_user_key, hash_value="stale-user", timestamp=3),
            _checkpoint_state(state_key=stale_event_key, hash_value="stale-event", timestamp=4),
            _checkpoint_state(
                state_key=stale_addressable_key,
                hash_value="stale-addressable",
                timestamp=5,
            ),
            _checkpoint_state(
                state_key=stale_identifier_key,
                hash_value="stale-identifier",
                timestamp=6,
            ),
            _checkpoint_state(state_key=other_algorithm_key, hash_value="other-algo", timestamp=7),
        ]
    )


def _make_assertor_config(
    algorithm_id: str,
    *,
    provider_profile_enabled: bool = True,
) -> AssertorConfig:
    return AssertorConfig.model_validate(
        {
            "algorithm_id": algorithm_id,
            "keys": {"keys_env": "NOSTR_PRIVATE_KEY_ASSERTOR"},
            "publishing": {"relays": ["wss://relay.damus.io"]},
            "selection": {
                "min_events": 1,
                "batch_size": 100,
                "kinds": [30382, 30383, 30384, 30385],
            },
            "metrics": {"enabled": False},
            "provider_profile": {
                "enabled": provider_profile_enabled,
                "kind0_content": {
                    "name": "BigBrotr Global PageRank",
                    "about": "NIP-85 trusted assertion provider",
                    "website": "https://bigbrotr.com",
                },
            },
        }
    )


def _make_mock_client() -> MagicMock:
    client = MagicMock()
    client.add_relay = AsyncMock()
    client.connect = AsyncMock()
    client.try_connect = AsyncMock(
        return_value=SimpleNamespace(success={"wss://relay.damus.io"}, failed={})
    )
    client.unsubscribe_all = AsyncMock()
    client.force_remove_all_relays = AsyncMock()
    client.shutdown = AsyncMock()
    client.database = MagicMock(return_value=SimpleNamespace(wipe=AsyncMock()))
    return client


def _assert_final_checkpoint_state(
    state_by_key: dict[str, ServiceState],
    *,
    user_key: str,
    event_key: str,
    addressable_key: str,
    identifier_key: str,
    profile_key: str,
    stale_user_key: str,
    stale_event_key: str,
    stale_addressable_key: str,
    stale_identifier_key: str,
    other_algorithm_key: str,
) -> None:
    assert user_key in state_by_key
    assert event_key in state_by_key
    assert addressable_key in state_by_key
    assert identifier_key in state_by_key
    assert profile_key in state_by_key
    assert stale_user_key not in state_by_key
    assert stale_event_key not in state_by_key
    assert stale_addressable_key not in state_by_key
    assert stale_identifier_key not in state_by_key
    assert other_algorithm_key in state_by_key
    assert not any(key.startswith("user:") for key in state_by_key)
    assert not any(key.startswith("event:") for key in state_by_key)

    for key in (user_key, event_key, addressable_key, identifier_key, profile_key):
        assert "hash" in state_by_key[key].state_value
        assert state_by_key[key].state_value["timestamp"] > 0


def _assert_published_event_payloads(
    published_builders: list[Any],
    *,
    config: AssertorConfig,
    event_address: str,
    identifier: str,
) -> None:
    signed_events = [builder.sign_with_keys(config.keys.keys) for builder in published_builders]
    events_by_kind = {event.kind().as_u16(): event for event in signed_events}

    assert set(events_by_kind) == {
        EventKind.SET_METADATA,
        EventKind.NIP85_USER_ASSERTION,
        EventKind.NIP85_EVENT_ASSERTION,
        EventKind.NIP85_ADDRESSABLE_ASSERTION,
        EventKind.NIP85_IDENTIFIER_ASSERTION,
    }
    assert _tag_values(events_by_kind[EventKind.NIP85_USER_ASSERTION], "rank") == ["89"]
    assert _tag_values(events_by_kind[EventKind.NIP85_EVENT_ASSERTION], "rank") == ["81"]
    assert _tag_values(events_by_kind[EventKind.NIP85_ADDRESSABLE_ASSERTION], "a") == [
        event_address
    ]
    assert _tag_values(events_by_kind[EventKind.NIP85_ADDRESSABLE_ASSERTION], "rank") == ["84"]
    assert _tag_values(events_by_kind[EventKind.NIP85_IDENTIFIER_ASSERTION], "d") == [identifier]
    assert _tag_values(events_by_kind[EventKind.NIP85_IDENTIFIER_ASSERTION], "rank") == ["73"]
    assert sorted(_tag_values(events_by_kind[EventKind.NIP85_IDENTIFIER_ASSERTION], "k")) == [
        "book",
        "isbn",
    ]


class TestAssertorIntegration:
    async def test_assertor_run_publishes_all_kinds_and_prunes_stale_state(
        self,
        brotr: Brotr,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("NOSTR_PRIVATE_KEY_ASSERTOR", VALID_HEX_KEY)

        algorithm_id = "global-pagerank"
        author = "c1" * 32
        replier = "d1" * 32
        root_event_id = "a0" * 32
        reply_event_id = "a1" * 32
        event_address = f"30023:{author}:article"
        identifier = "isbn:9780140328721"
        relay_url = "wss://assertor.example.com"

        await _seed_full_kind_assertor_data(
            brotr=brotr,
            algorithm_id=algorithm_id,
            author=author,
            replier=replier,
            root_event_id=root_event_id,
            reply_event_id=reply_event_id,
            event_address=event_address,
            identifier=identifier,
            relay_url=relay_url,
        )

        noncanonical_user_key = f"user:{author}"
        noncanonical_event_key = f"event:{root_event_id}"
        stale_user_key = f"{algorithm_id}:30382:{'ef' * 32}"
        stale_event_key = f"{algorithm_id}:30383:{'fe' * 32}"
        stale_addressable_key = f"{algorithm_id}:30384:30023:{'ab' * 32}:stale"
        stale_identifier_key = f"{algorithm_id}:30385:isbn:stale"
        other_algorithm_key = f"other-algo:30382:{'ab' * 32}"

        await _seed_checkpoint_states(
            brotr=brotr,
            noncanonical_user_key=noncanonical_user_key,
            noncanonical_event_key=noncanonical_event_key,
            stale_user_key=stale_user_key,
            stale_event_key=stale_event_key,
            stale_addressable_key=stale_addressable_key,
            stale_identifier_key=stale_identifier_key,
            other_algorithm_key=other_algorithm_key,
        )

        config = _make_assertor_config(algorithm_id)
        client = _make_mock_client()

        published_builders: list[Any] = []

        async def _capture_broadcast(builders: list[Any], _clients: list[Any]) -> int:
            published_builders.extend(builders)
            return 1

        with (
            patch(
                "bigbrotr.services.assertor.service.create_client",
                new=AsyncMock(return_value=client),
            ),
            patch(
                "bigbrotr.services.assertor.service.broadcast_events",
                new=AsyncMock(side_effect=_capture_broadcast),
            ),
        ):
            async with Assertor(brotr=brotr, config=config) as service:
                await service.run()

        rows_after_run = await brotr.get_service_state(
            ServiceName.ASSERTOR,
            ServiceStateType.CHECKPOINT,
        )
        state_by_key = {row.state_key: row for row in rows_after_run}

        user_key = f"{algorithm_id}:30382:{author}"
        event_key = f"{algorithm_id}:30383:{root_event_id}"
        addressable_key = f"{algorithm_id}:30384:{event_address}"
        identifier_key = f"{algorithm_id}:30385:{identifier}"
        profile_key = f"{algorithm_id}:0:provider_profile"

        _assert_final_checkpoint_state(
            state_by_key,
            user_key=user_key,
            event_key=event_key,
            addressable_key=addressable_key,
            identifier_key=identifier_key,
            profile_key=profile_key,
            stale_user_key=stale_user_key,
            stale_event_key=stale_event_key,
            stale_addressable_key=stale_addressable_key,
            stale_identifier_key=stale_identifier_key,
            other_algorithm_key=other_algorithm_key,
        )
        _assert_published_event_payloads(
            published_builders,
            config=config,
            event_address=event_address,
            identifier=identifier,
        )

        second_published_builders: list[Any] = []

        async def _capture_second_broadcast(builders: list[Any], _clients: list[Any]) -> int:
            second_published_builders.extend(builders)
            return 1

        with (
            patch(
                "bigbrotr.services.assertor.service.create_client",
                new=AsyncMock(return_value=_make_mock_client()),
            ),
            patch(
                "bigbrotr.services.assertor.service.broadcast_events",
                new=AsyncMock(side_effect=_capture_second_broadcast),
            ),
        ):
            async with Assertor(brotr=brotr, config=config) as service:
                second_result = await service.publish()

        assert second_result.assertions_published == 0
        assert second_result.assertions_skipped == 4
        assert second_result.provider_profiles_published == 0
        assert second_result.provider_profiles_skipped == 1
        assert second_result.checkpoint_cleanup_removed == 0
        assert second_published_builders == []

    async def test_assertor_publish_noops_without_subjects_or_provider_profile(
        self,
        brotr: Brotr,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("NOSTR_PRIVATE_KEY_ASSERTOR", VALID_HEX_KEY)
        config = _make_assertor_config(
            "no-eligible-pagerank",
            provider_profile_enabled=False,
        )
        mock_broadcast = AsyncMock(return_value=1)

        with (
            patch(
                "bigbrotr.services.assertor.service.create_client",
                new=AsyncMock(return_value=_make_mock_client()),
            ),
            patch(
                "bigbrotr.services.assertor.service.broadcast_events",
                new=mock_broadcast,
            ),
        ):
            async with Assertor(brotr=brotr, config=config) as service:
                result = await service.publish()

        assert result.assertions_published == 0
        assert result.assertions_skipped == 0
        assert result.provider_profiles_published == 0
        assert result.provider_profiles_skipped == 0
        assert result.checkpoint_cleanup_removed == 0
        mock_broadcast.assert_not_awaited()
