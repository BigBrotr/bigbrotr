"""Integration tests for the Refresher service."""

from __future__ import annotations

import pytest

from bigbrotr.core.brotr import Brotr
from bigbrotr.models import EventObservation, Relay, RelayDocument
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.document import Document, DocumentType
from bigbrotr.models.event import Event
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from bigbrotr.services.refresher import Refresher, RefresherConfig
from tests.conftest import make_mock_event


pytestmark = pytest.mark.integration


def _event_observation(
    event_id: str,
    relay_url: str,
    *,
    kind: int = 1,
    pubkey: str = "aa" * 32,
    created_at: int = 1700000000,
    observed_at: int | None = None,
    tags: list[list[str]] | None = None,
) -> EventObservation:
    event = Event(
        make_mock_event(
            event_id=event_id,
            pubkey=pubkey,
            kind=kind,
            created_at=created_at,
            sig="ee" * 64,
            tags=tags,
        )
    )
    relay = Relay(relay_url, stored_at=1700000000)
    return EventObservation(event=event, relay=relay, observed_at=observed_at or created_at + 1)


def _config(
    *,
    current: list[str] | None = None,
    analytics: list[str] | None = None,
    periodic: bool = False,
) -> RefresherConfig:
    return RefresherConfig.model_validate(
        {
            "metrics": {"enabled": False},
            "current": {"targets": [] if current is None else current},
            "analytics": {"targets": [] if analytics is None else analytics},
            "periodic": {
                "rolling_windows": periodic,
                "relay_stats_document": periodic,
                "nip85_followers": periodic,
            },
        }
    )


def _relay_document(
    relay_url: str,
    data: dict,
    *,
    document_type: DocumentType = DocumentType.NIP11_INFO,
    associated_at: int = 1700000001,
) -> RelayDocument:
    relay = Relay(relay_url, stored_at=1700000000)
    document = Document(type=document_type, data=data)
    return RelayDocument(relay=relay, document=document, associated_at=associated_at)


class TestRefresherIntegration:
    async def test_current_tables_only(self, brotr: Brotr) -> None:
        await brotr.insert_event_observation(
            [
                _event_observation(
                    "10" * 32,
                    "wss://refresher-current.example.com",
                    kind=0,
                    pubkey="11" * 32,
                )
            ],
            cascade=True,
        )
        refresher = Refresher(
            brotr=brotr,
            config=_config(current=["replaceable_event_current"]),
        )

        result = await refresher.refresh()

        row = await brotr.fetchrow(
            "SELECT pubkey, kind FROM replaceable_event_current WHERE pubkey = $1",
            bytes.fromhex("11" * 32),
        )
        assert row is not None
        assert row["kind"] == 0
        assert result.targets_current_total == 1
        assert result.targets_analytics_total == 0
        assert result.targets_refreshed == 1

    async def test_analytics_tables_only(self, brotr: Brotr) -> None:
        await brotr.insert_event_observation(
            [
                _event_observation(
                    "20" * 32,
                    "wss://refresher-analytics.example.com",
                    kind=7,
                    pubkey="22" * 32,
                )
            ],
            cascade=True,
        )
        refresher = Refresher(
            brotr=brotr,
            config=_config(analytics=["pubkey_kind_stats"]),
        )

        result = await refresher.refresh()

        row = await brotr.fetchrow(
            "SELECT event_count FROM pubkey_kind_stats WHERE pubkey = $1 AND kind = $2",
            "22" * 32,
            7,
        )
        assert row is not None
        assert row["event_count"] == 1
        assert result.targets_current_total == 0
        assert result.targets_analytics_total == 1
        assert result.rows_refreshed >= 1

    async def test_mixed_cycle_with_periodic_disabled(self, brotr: Brotr) -> None:
        await brotr.insert_event_observation(
            [
                _event_observation(
                    "30" * 32,
                    "wss://refresher-mixed.example.com",
                    kind=0,
                    pubkey="33" * 32,
                )
            ],
            cascade=True,
        )
        refresher = Refresher(
            brotr=brotr,
            config=_config(
                current=["replaceable_event_current"],
                analytics=["pubkey_kind_stats"],
                periodic=False,
            ),
        )

        result = await refresher.refresh()

        assert result.targets_total == 2
        assert result.targets_periodic_total == 0
        assert result.targets_refreshed == 2

    async def test_periodic_enabled_cycle(self, brotr: Brotr) -> None:
        refresher = Refresher(brotr=brotr, config=_config(periodic=True))

        result = await refresher.refresh()

        assert result.targets_total == 3
        assert result.targets_periodic_total == 3
        assert result.targets_refreshed == 3

    async def test_checkpoint_cleanup_removes_stale_targets(self, brotr: Brotr) -> None:
        await brotr.upsert_service_state(
            [
                ServiceState(
                    owner=ServiceName.REFRESHER,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key="old_target",
                    state_value={"timestamp": 100},
                ),
                ServiceState(
                    owner=ServiceName.REFRESHER,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key="pubkey_kind_stats",
                    state_value={"timestamp": 100},
                ),
            ]
        )
        refresher = Refresher(
            brotr=brotr,
            config=_config(analytics=["pubkey_kind_stats"]),
        )

        removed = await refresher.cleanup()

        states = await brotr.get_service_state(ServiceName.REFRESHER, ServiceStateType.CHECKPOINT)
        assert removed == 1
        assert {state.state_key for state in states} == {"pubkey_kind_stats"}

    async def test_idempotent_second_run_uses_checkpoint(self, brotr: Brotr) -> None:
        await brotr.insert_event_observation(
            [
                _event_observation(
                    "40" * 32,
                    "wss://refresher-idempotent.example.com",
                    kind=1,
                    pubkey="44" * 32,
                )
            ],
            cascade=True,
        )
        refresher = Refresher(
            brotr=brotr,
            config=_config(analytics=["pubkey_kind_stats"]),
        )

        first = await refresher.refresh()
        second = await refresher.refresh()

        row = await brotr.fetchrow(
            "SELECT event_count FROM pubkey_kind_stats WHERE pubkey = $1 AND kind = $2",
            "44" * 32,
            1,
        )
        assert row is not None
        assert row["event_count"] == 1
        assert first.rows_refreshed >= 1
        assert second.rows_refreshed == 0

    async def test_resume_after_stored_checkpoint(self, brotr: Brotr) -> None:
        await brotr.insert_event_observation(
            [
                _event_observation(
                    "50" * 32,
                    "wss://refresher-resume.example.com",
                    kind=1,
                    pubkey="55" * 32,
                    observed_at=100,
                ),
                _event_observation(
                    "51" * 32,
                    "wss://refresher-resume.example.com",
                    kind=1,
                    pubkey="66" * 32,
                    observed_at=200,
                ),
            ],
            cascade=True,
        )
        await brotr.upsert_service_state(
            [
                ServiceState(
                    owner=ServiceName.REFRESHER,
                    state_type=ServiceStateType.CHECKPOINT,
                    state_key="pubkey_kind_stats",
                    state_value={"timestamp": 150},
                )
            ]
        )
        refresher = Refresher(
            brotr=brotr,
            config=_config(analytics=["pubkey_kind_stats"]),
        )

        result = await refresher.refresh()

        old_row = await brotr.fetchrow(
            "SELECT event_count FROM pubkey_kind_stats WHERE pubkey = $1",
            "55" * 32,
        )
        new_row = await brotr.fetchrow(
            "SELECT event_count FROM pubkey_kind_stats WHERE pubkey = $1",
            "66" * 32,
        )
        assert old_row is None
        assert new_row is not None
        assert new_row["event_count"] == 1
        assert result.rows_refreshed >= 1

    async def test_incremental_checkpoints_track_consumed_source_max(self, brotr: Brotr) -> None:
        refresher = Refresher(
            brotr=brotr,
            config=_config(analytics=["pubkey_kind_stats"]),
        )
        await brotr.insert_event_observation(
            [
                _event_observation(
                    "60" * 32,
                    "wss://refresher-source-max.example.com",
                    kind=1,
                    pubkey="77" * 32,
                    observed_at=100,
                )
            ],
            cascade=True,
        )

        first = await refresher.refresh()
        state_after_first = await brotr.get_service_state(
            ServiceName.REFRESHER,
            ServiceStateType.CHECKPOINT,
            "pubkey_kind_stats",
        )
        assert state_after_first
        assert state_after_first[0].state_value["timestamp"] == 100

        await brotr.insert_event_observation(
            [
                _event_observation(
                    "61" * 32,
                    "wss://refresher-source-max.example.com",
                    kind=1,
                    pubkey="88" * 32,
                    observed_at=150,
                )
            ],
            cascade=True,
        )

        second = await refresher.refresh()

        first_row = await brotr.fetchrow(
            "SELECT event_count FROM pubkey_kind_stats WHERE pubkey = $1 AND kind = $2",
            "77" * 32,
            1,
        )
        second_row = await brotr.fetchrow(
            "SELECT event_count FROM pubkey_kind_stats WHERE pubkey = $1 AND kind = $2",
            "88" * 32,
            1,
        )
        state_after_second = await brotr.get_service_state(
            ServiceName.REFRESHER,
            ServiceStateType.CHECKPOINT,
            "pubkey_kind_stats",
        )

        assert first.rows_refreshed >= 1
        assert second.rows_refreshed >= 1
        assert first_row is not None
        assert first_row["event_count"] == 1
        assert second_row is not None
        assert second_row["event_count"] == 1
        assert state_after_second
        assert state_after_second[0].state_value["timestamp"] == 150

    async def test_document_checkpoints_track_consumed_source_max(self, brotr: Brotr) -> None:
        refresher = Refresher(
            brotr=brotr,
            config=_config(current=["relay_document_current"]),
        )
        first_document = _relay_document(
            "wss://refresher-document-source-max.example.com",
            {"name": "First"},
            associated_at=100,
        )
        await brotr.insert_relay_document([first_document], cascade=True)

        first = await refresher.refresh()
        state_after_first = await brotr.get_service_state(
            ServiceName.REFRESHER,
            ServiceStateType.CHECKPOINT,
            "relay_document_current",
        )
        assert state_after_first
        assert state_after_first[0].state_value["timestamp"] == 100

        second_document = _relay_document(
            "wss://refresher-document-source-max.example.com",
            {"name": "Second"},
            associated_at=150,
        )
        await brotr.insert_relay_document([second_document], cascade=True)

        second = await refresher.refresh()

        current_row = await brotr.fetchrow(
            """
            SELECT document_id, associated_at
            FROM relay_document_current
            WHERE relay_url = $1 AND role = $2
            """,
            "wss://refresher-document-source-max.example.com",
            DocumentType.NIP11_INFO.value,
        )
        state_after_second = await brotr.get_service_state(
            ServiceName.REFRESHER,
            ServiceStateType.CHECKPOINT,
            "relay_document_current",
        )

        assert first.rows_refreshed >= 1
        assert second.rows_refreshed >= 1
        assert current_row is not None
        assert current_row["document_id"] == second_document.document.content_hash
        assert current_row["associated_at"] == 150
        assert state_after_second
        assert state_after_second[0].state_value["timestamp"] == 150

    async def test_max_targets_budget_can_stop_cycle(self, brotr: Brotr) -> None:
        refresher = Refresher(
            brotr=brotr,
            config=RefresherConfig.model_validate(
                {
                    "metrics": {"enabled": False},
                    "processing": {"max_targets_per_cycle": 1},
                    "current": {"targets": ["replaceable_event_current"]},
                    "analytics": {"targets": ["pubkey_kind_stats"]},
                    "periodic": {
                        "rolling_windows": False,
                        "relay_stats_document": False,
                        "nip85_followers": False,
                    },
                }
            ),
        )

        result = await refresher.refresh()

        assert result.targets_attempted == 1
        assert result.targets_skipped == 1
        assert result.cutoff_reason == "max_targets_per_cycle"
