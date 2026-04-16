"""End-to-end integration smoke test for the NIP-85 pipeline."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nostr_sdk import Event as NostrEvent

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import EventRelay, Relay
from bigbrotr.models.constants import EventKind, ServiceName
from bigbrotr.models.event import Event
from bigbrotr.models.service_state import ServiceStateType
from bigbrotr.services.assertor import Assertor, AssertorConfig
from bigbrotr.services.ranker import Ranker, RankerConfig
from bigbrotr.services.refresher import Refresher, RefresherConfig
from bigbrotr.utils.protocol import BroadcastClientResult, ClientConnectResult, ClientSession


if TYPE_CHECKING:
    from pathlib import Path


pytestmark = pytest.mark.integration

VALID_HEX_KEY = (
    "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"  # pragma: allowlist secret
)

_RANK_FETCH_QUERIES = {
    "nip85_pubkey_ranks": """
        SELECT subject_id, rank
        FROM nip85_pubkey_ranks
        WHERE algorithm_id = $1
        ORDER BY subject_id
    """,
    "nip85_event_ranks": """
        SELECT subject_id, rank
        FROM nip85_event_ranks
        WHERE algorithm_id = $1
        ORDER BY subject_id
    """,
    "nip85_addressable_ranks": """
        SELECT subject_id, rank
        FROM nip85_addressable_ranks
        WHERE algorithm_id = $1
        ORDER BY subject_id
    """,
    "nip85_identifier_ranks": """
        SELECT subject_id, rank
        FROM nip85_identifier_ranks
        WHERE algorithm_id = $1
        ORDER BY subject_id
    """,
}


def _make_assertor_publish_session(client: MagicMock) -> ClientSession:
    relay_url = "wss://publish-relay.example.com"
    return ClientSession(
        session_id="assertor-publish-relays",
        client=client,
        relay_urls=(relay_url,),
        connect_result=ClientConnectResult(connected=(relay_url,), failed={}),
    )


def _broadcast_results(
    *,
    successful_relays: tuple[str, ...] = ("wss://publish-relay.example.com",),
    failed_relays: dict[str, str] | None = None,
) -> list[BroadcastClientResult]:
    return [
        BroadcastClientResult(
            event_ids=("event-id",),
            successful_relays=successful_relays,
            failed_relays=failed_relays or {},
        )
    ]


def _make_mock_event(
    *,
    event_id: str,
    pubkey: str,
    created_at: int,
    kind: int,
    tags: list[list[str]],
    sig: str,
    content: str = "",
) -> MagicMock:
    """Create a mock nostr_sdk.Event compatible with the Event wrapper."""
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


def _event_relay(
    event_id: str,
    relay_url: str,
    *,
    kind: int = 1,
    pubkey: str = "bb" * 32,
    created_at: int = 1_700_000_000,
    tags: list[list[str]] | None = None,
    content: str = "",
) -> EventRelay:
    mock = _make_mock_event(
        event_id=event_id,
        pubkey=pubkey,
        kind=kind,
        created_at=created_at,
        sig="ee" * 64,
        tags=tags or [],
        content=content,
    )
    relay = Relay(relay_url, discovered_at=1_700_000_000)
    return EventRelay(event=Event(mock), relay=relay, seen_at=created_at + 1)


def _tag_values(event: Any, tag_name: str) -> list[str]:
    values: list[str] = []
    for tag in event.tags().to_vec():
        vec = tag.as_vec()
        if vec and vec[0] == tag_name and len(vec) > 1:
            values.append(vec[1])
    return values


async def _seed_pipeline_events(
    *,
    brotr: Brotr,
    relay_url: str,
    author: str,
    follower_b: str,
    follower_c: str,
    root_event_id: str,
    event_address: str,
    identifier: str,
) -> None:
    """Seed raw events that exercise the full refresher -> ranker -> assertor flow."""
    await brotr.insert_event_relay(
        [
            _event_relay(
                "10" * 32,
                relay_url,
                kind=3,
                pubkey=author,
                created_at=100,
                tags=[["p", follower_b], ["p", follower_c]],
            ),
            _event_relay(
                "11" * 32,
                relay_url,
                kind=3,
                pubkey=follower_b,
                created_at=101,
                tags=[["p", author]],
            ),
            _event_relay(
                "12" * 32,
                relay_url,
                kind=3,
                pubkey=follower_c,
                created_at=102,
                tags=[["p", author]],
            ),
            _event_relay(
                root_event_id,
                relay_url,
                kind=1,
                pubkey=author,
                created_at=200,
                tags=[["t", "nostr"], ["t", "books"]],
                content="Root note",
            ),
            _event_relay(
                "21" * 32,
                relay_url,
                kind=1,
                pubkey=follower_b,
                created_at=201,
                tags=[["e", root_event_id], ["p", author]],
                content="Reply",
            ),
            _event_relay(
                "22" * 32,
                relay_url,
                kind=7,
                pubkey=follower_c,
                created_at=202,
                tags=[["e", root_event_id], ["p", author]],
                content="+",
            ),
            _event_relay(
                "23" * 32,
                relay_url,
                kind=30023,
                pubkey=author,
                created_at=203,
                tags=[["d", "article"], ["t", "nostr"]],
                content="Addressable article",
            ),
            _event_relay(
                "24" * 32,
                relay_url,
                kind=1,
                pubkey=follower_b,
                created_at=204,
                tags=[["a", event_address], ["p", author]],
                content="Addressable comment",
            ),
            _event_relay(
                "25" * 32,
                relay_url,
                kind=1,
                pubkey=follower_b,
                created_at=205,
                tags=[["i", identifier], ["k", "book"], ["k", "isbn"]],
                content="Identifier comment",
            ),
            _event_relay(
                "26" * 32,
                relay_url,
                kind=7,
                pubkey=follower_c,
                created_at=206,
                tags=[["i", identifier], ["k", "isbn"]],
                content="+",
            ),
        ],
        cascade=True,
    )


def _make_refresher_config() -> RefresherConfig:
    return RefresherConfig.model_validate(
        {
            "metrics": {"enabled": False},
            "current": {
                "targets": [
                    "events_replaceable_current",
                    "events_addressable_current",
                    "contact_lists_current",
                    "contact_list_edges_current",
                ],
            },
            "analytics": {
                "targets": [
                    "pubkey_kind_stats",
                    "pubkey_relay_stats",
                    "relay_kind_stats",
                    "pubkey_stats",
                    "nip85_pubkey_stats",
                    "nip85_event_stats",
                    "nip85_addressable_stats",
                    "nip85_identifier_stats",
                ],
            },
        }
    )


def _make_ranker_config(tmp_path: Path, algorithm_id: str) -> RankerConfig:
    return RankerConfig.model_validate(
        {
            "metrics": {"enabled": False},
            "algorithm_id": algorithm_id,
            "storage": {
                "path": tmp_path / "ranker.duckdb",
                "checkpoint_path": tmp_path / "ranker.checkpoint.json",
            },
            "sync": {"batch_size": 100},
            "export": {"batch_size": 100},
        }
    )


def _make_assertor_config(algorithm_id: str) -> AssertorConfig:
    return AssertorConfig.model_validate(
        {
            "metrics": {"enabled": False},
            "algorithm_id": algorithm_id,
            "keys": {"keys_env": "NOSTR_PRIVATE_KEY_ASSERTOR"},
            "publishing": {"relays": ["wss://relay.damus.io"]},
            "selection": {"kinds": [30382, 30383, 30384, 30385]},
            "provider_profile": {
                "enabled": True,
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


async def _fetch_rank_map(
    *,
    brotr: Brotr,
    table_name: str,
    algorithm_id: str,
) -> dict[str, int]:
    assert table_name in _RANK_FETCH_QUERIES
    rows = await brotr.fetch(_RANK_FETCH_QUERIES[table_name], algorithm_id)
    return {str(row["subject_id"]): int(row["rank"]) for row in rows}


async def _assert_refresher_outputs(
    *,
    brotr: Brotr,
    author: str,
    root_event_id: str,
    event_address: str,
    identifier: str,
) -> None:
    user_fact = await brotr.fetchrow(
        "SELECT follower_count, following_count, post_count FROM nip85_pubkey_stats WHERE pubkey = $1",
        author,
    )
    event_fact = await brotr.fetchrow(
        "SELECT comment_count, reaction_count FROM nip85_event_stats WHERE event_id = $1",
        root_event_id,
    )
    addressable_fact = await brotr.fetchrow(
        "SELECT comment_count FROM nip85_addressable_stats WHERE event_address = $1",
        event_address,
    )
    identifier_fact = await brotr.fetchrow(
        "SELECT comment_count, reaction_count, k_tags "
        "FROM nip85_identifier_stats WHERE identifier = $1",
        identifier,
    )

    assert user_fact is not None
    assert user_fact["follower_count"] == 2
    assert user_fact["following_count"] == 2
    assert user_fact["post_count"] >= 1
    assert event_fact is not None
    assert event_fact["comment_count"] == 1
    assert event_fact["reaction_count"] == 1
    assert addressable_fact is not None
    assert addressable_fact["comment_count"] == 1
    assert identifier_fact is not None
    assert identifier_fact["comment_count"] == 1
    assert identifier_fact["reaction_count"] == 1
    assert identifier_fact["k_tags"] == ["book", "isbn"]


def _assert_rank_exports(
    *,
    pubkey_ranks: dict[str, int],
    event_ranks: dict[str, int],
    addressable_ranks: dict[str, int],
    identifier_ranks: dict[str, int],
    author: str,
    root_event_id: str,
    event_address: str,
    identifier: str,
) -> None:
    assert author in pubkey_ranks
    assert root_event_id in event_ranks
    assert event_address in addressable_ranks
    assert identifier in identifier_ranks


def _assert_published_events(
    *,
    config: AssertorConfig,
    published_builders: list[Any],
    pubkey_ranks: dict[str, int],
    event_ranks: dict[str, int],
    addressable_ranks: dict[str, int],
    identifier_ranks: dict[str, int],
    author: str,
    root_event_id: str,
    event_address: str,
    identifier: str,
) -> None:
    signed_events = [builder.sign_with_keys(config.keys.keys) for builder in published_builders]
    assert EventKind.SET_METADATA in {event.kind().as_u16() for event in signed_events}

    def _find_by_kind_and_d(kind: int, subject_id: str) -> Any:
        for event in signed_events:
            if event.kind().as_u16() != kind:
                continue
            if _tag_values(event, "d") == [subject_id]:
                return event
        raise AssertionError(f"missing event for kind={kind} subject={subject_id}")

    user_event = _find_by_kind_and_d(EventKind.NIP85_USER_ASSERTION, author)
    event_event = _find_by_kind_and_d(EventKind.NIP85_EVENT_ASSERTION, root_event_id)
    addressable_event = _find_by_kind_and_d(
        EventKind.NIP85_ADDRESSABLE_ASSERTION,
        event_address,
    )
    identifier_event = _find_by_kind_and_d(EventKind.NIP85_IDENTIFIER_ASSERTION, identifier)

    assert _tag_values(user_event, "rank") == [str(pubkey_ranks[author])]
    assert _tag_values(event_event, "rank") == [str(event_ranks[root_event_id])]
    assert _tag_values(addressable_event, "a") == [event_address]
    assert _tag_values(addressable_event, "rank") == [str(addressable_ranks[event_address])]
    assert _tag_values(identifier_event, "d") == [identifier]
    assert _tag_values(identifier_event, "rank") == [str(identifier_ranks[identifier])]
    assert sorted(_tag_values(identifier_event, "k")) == [
        "book",
        "isbn",
    ]


async def _run_assertor_smoke(
    *,
    brotr: Brotr,
    config: AssertorConfig,
    client: MagicMock,
    pubkey_ranks: dict[str, int],
    event_ranks: dict[str, int],
    addressable_ranks: dict[str, int],
    identifier_ranks: dict[str, int],
    author: str,
    root_event_id: str,
    event_address: str,
    identifier: str,
) -> None:
    published_builders: list[Any] = []

    async def _capture_broadcast(
        builders: list[Any],
        _clients: list[Any],
    ) -> list[BroadcastClientResult]:
        published_builders.extend(builders)
        return _broadcast_results()

    with (
        patch(
            "bigbrotr.services.assertor.service.NostrClientManager.connect_session",
            new=AsyncMock(return_value=_make_assertor_publish_session(client)),
        ),
        patch(
            "bigbrotr.services.assertor.service.broadcast_events",
            new=AsyncMock(side_effect=_capture_broadcast),
        ),
    ):
        async with Assertor(brotr=brotr, config=config) as assertor:
            await assertor.run()
            _assert_published_events(
                config=config,
                published_builders=published_builders,
                pubkey_ranks=pubkey_ranks,
                event_ranks=event_ranks,
                addressable_ranks=addressable_ranks,
                identifier_ranks=identifier_ranks,
                author=author,
                root_event_id=root_event_id,
                event_address=event_address,
                identifier=identifier,
            )

            published_builders.clear()
            await assertor.run()
            assert published_builders == []


class TestNip85PipelineSmoke:
    async def test_refresher_ranker_assertor_pipeline_smoke(
        self,
        brotr: Brotr,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("NOSTR_PRIVATE_KEY_ASSERTOR", VALID_HEX_KEY)

        algorithm_id = "global-pagerank"
        relay_url = "wss://pipeline.example.com"
        author = "a1" * 32
        follower_b = "b2" * 32
        follower_c = "c3" * 32
        root_event_id = "d4" * 32
        event_address = f"30023:{author}:article"
        identifier = "isbn:9780140328721"

        await _seed_pipeline_events(
            brotr=brotr,
            relay_url=relay_url,
            author=author,
            follower_b=follower_b,
            follower_c=follower_c,
            root_event_id=root_event_id,
            event_address=event_address,
            identifier=identifier,
        )

        refresher = Refresher(brotr=brotr, config=_make_refresher_config())
        async with refresher:
            await refresher.run()

        await _assert_refresher_outputs(
            brotr=brotr,
            author=author,
            root_event_id=root_event_id,
            event_address=event_address,
            identifier=identifier,
        )

        ranker = Ranker(
            brotr=brotr,
            config=_make_ranker_config(tmp_path, algorithm_id),
        )
        async with ranker:
            await ranker.run()

        pubkey_ranks = await _fetch_rank_map(
            brotr=brotr,
            table_name="nip85_pubkey_ranks",
            algorithm_id=algorithm_id,
        )
        event_ranks = await _fetch_rank_map(
            brotr=brotr,
            table_name="nip85_event_ranks",
            algorithm_id=algorithm_id,
        )
        addressable_ranks = await _fetch_rank_map(
            brotr=brotr,
            table_name="nip85_addressable_ranks",
            algorithm_id=algorithm_id,
        )
        identifier_ranks = await _fetch_rank_map(
            brotr=brotr,
            table_name="nip85_identifier_ranks",
            algorithm_id=algorithm_id,
        )

        _assert_rank_exports(
            pubkey_ranks=pubkey_ranks,
            event_ranks=event_ranks,
            addressable_ranks=addressable_ranks,
            identifier_ranks=identifier_ranks,
            author=author,
            root_event_id=root_event_id,
            event_address=event_address,
            identifier=identifier,
        )

        config = _make_assertor_config(algorithm_id)
        client = _make_mock_client()
        await _run_assertor_smoke(
            brotr=brotr,
            config=config,
            client=client,
            pubkey_ranks=pubkey_ranks,
            event_ranks=event_ranks,
            addressable_ranks=addressable_ranks,
            identifier_ranks=identifier_ranks,
            author=author,
            root_event_id=root_event_id,
            event_address=event_address,
            identifier=identifier,
        )

        state_rows = await brotr.get_service_state(
            ServiceName.ASSERTOR, ServiceStateType.CHECKPOINT
        )
        state_keys = {row.state_key for row in state_rows}
        assert {
            f"{algorithm_id}:0:provider_profile",
            f"{algorithm_id}:30382:{author}",
            f"{algorithm_id}:30383:{root_event_id}",
            f"{algorithm_id}:30384:{event_address}",
            f"{algorithm_id}:30385:{identifier}",
        }.issubset(state_keys)
