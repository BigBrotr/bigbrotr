"""Unit tests for the dvm service module."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from nostr_sdk import Keys

from bigbrotr.core.base_service import BaseService
from bigbrotr.core.brotr import Brotr
from bigbrotr.models import Relay
from bigbrotr.models.constants import ServiceName
from bigbrotr.services.common.catalog import (
    Catalog,
    CatalogError,
    ColumnSchema,
    QueryResult,
    TableSchema,
)
from bigbrotr.services.common.configs import ReadModelPolicy
from bigbrotr.services.common.state_store import ServiceStateStore
from bigbrotr.services.common.types import DvmRequestCursor
from bigbrotr.services.dvm.configs import DvmConfig
from bigbrotr.services.dvm.service import Dvm
from bigbrotr.services.dvm.utils import (
    JobPreparationContext,
    PreparedJobRequest,
    RejectedJobRequest,
    ResultEventRequest,
    build_announcement_event,
    build_error_event,
    build_payment_required_event,
    build_result_event,
    parse_job_params,
    prepare_job_request,
)
from bigbrotr.utils.protocol import ClientConnectResult, ClientSession, NostrClientManager


# Valid secp256k1 test key (DO NOT USE IN PRODUCTION)
VALID_HEX_KEY = (
    "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"  # pragma: allowlist secret
)


# ============================================================================
# Fixtures & Helpers
# ============================================================================


@pytest.fixture(autouse=True)
def _set_private_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOSTR_PRIVATE_KEY_DVM", VALID_HEX_KEY)


@pytest.fixture
def dvm_config() -> DvmConfig:
    return DvmConfig(
        interval=60.0,
        relays=["wss://relay.example.com"],
        kind=5050,
        max_page_size=100,
        read_models={
            "relays": ReadModelPolicy(enabled=True),
            "events": ReadModelPolicy(enabled=True, price=5000),
        },
    )


@pytest.fixture
def sample_dvm_catalog() -> Catalog:
    catalog = Catalog()
    catalog._tables = {
        "relay": TableSchema(
            name="relay",
            columns=(
                ColumnSchema(name="url", pg_type="text", nullable=False),
                ColumnSchema(name="network", pg_type="text", nullable=False),
            ),
            primary_key=("url",),
            is_view=False,
        ),
        "service_state": TableSchema(
            name="service_state",
            columns=(ColumnSchema(name="service_name", pg_type="text", nullable=False),),
            primary_key=("service_name",),
            is_view=False,
        ),
        "event": TableSchema(
            name="event",
            columns=(ColumnSchema(name="id", pg_type="text", nullable=False),),
            primary_key=("id",),
            is_view=False,
        ),
    }
    return catalog


@pytest.fixture
def dvm_service(mock_brotr: Brotr, dvm_config: DvmConfig, sample_dvm_catalog: Catalog) -> Dvm:
    service = Dvm(brotr=mock_brotr, config=dvm_config)
    service._read_models.catalog = sample_dvm_catalog
    return service


def _make_mock_event(
    event_id: str = "abc123",
    author_hex: str = "author_pubkey_hex",
    tags: list[list[str]] | None = None,
    created_at: int = 1234,
) -> MagicMock:
    event = MagicMock()
    event.id.return_value.to_hex.return_value = event_id
    event.author.return_value.to_hex.return_value = author_hex
    event.created_at.return_value.as_secs.return_value = created_at

    if tags is None:
        tags = [
            ["param", "read_model", "relays"],
            ["param", "limit", "10"],
        ]

    mock_tags = []
    for tag_values in tags:
        mock_tag = MagicMock()
        mock_tag.as_vec.return_value = tag_values
        mock_tags.append(mock_tag)

    tag_list = MagicMock()
    tag_list.to_vec.return_value = mock_tags
    event.tags.return_value = tag_list

    return event


def _make_client_with_events(events: list[MagicMock]) -> MagicMock:
    mock_client = MagicMock()
    mock_client.send_event_builder = AsyncMock(return_value=_make_send_output())
    mock_client.subscribe_to = AsyncMock(
        return_value=SimpleNamespace(
            id="sub-1",
            success=["wss://relay.example.com"],
            failed={},
        )
    )
    mock_client.handle_notifications = AsyncMock()
    return mock_client


async def _seed_request_events(service: Dvm, events: list[MagicMock]) -> None:
    service._request_events = asyncio.Queue()
    for event in events:
        service._request_events.put_nowait(event)


def _make_send_output(
    success_relays: tuple[str, ...] = ("wss://relay.example.com",),
    failed_relays: dict[str, str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="event-id",
        success=list(success_relays),
        failed=failed_relays or {},
    )


# ============================================================================
# Configs
# ============================================================================


class TestDvmConfig:
    def test_default_values(self) -> None:
        config = DvmConfig(relays=["wss://relay.example.com"])
        assert config.keys.keys_env == "NOSTR_PRIVATE_KEY_DVM"
        assert config.keys.keys is not None
        assert config.name == "BigBrotr DVM"
        assert config.about == "Read-only access to BigBrotr relay monitoring data"
        assert config.d_tag == "bigbrotr-dvm"
        assert config.kind == 5050
        assert config.default_page_size == 100
        assert config.max_page_size == 1000
        assert config.announce is True
        assert config.read_models == {}
        assert config.fetch_timeout == 30.0
        assert config.allow_insecure is False

    def test_custom_branding(self) -> None:
        config = DvmConfig(
            relays=["wss://relay.example.com"],
            name="LilBrotr DVM",
            about="LilBrotr relay data",
            d_tag="lilbrotr-dvm",
        )
        assert config.name == "LilBrotr DVM"
        assert config.about == "LilBrotr relay data"
        assert config.d_tag == "lilbrotr-dvm"

    def test_custom_fetch_timeout(self) -> None:
        config = DvmConfig(relays=["wss://relay.example.com"], fetch_timeout=60.0)
        assert config.fetch_timeout == 60.0

    def test_requires_relays(self) -> None:
        with pytest.raises(ValueError):
            DvmConfig(relays=[])

    def test_kind_range(self) -> None:
        with pytest.raises(ValueError):
            DvmConfig(relays=["wss://relay.example.com"], kind=4000)

    def test_custom_read_models(self) -> None:
        config = DvmConfig(
            relays=["wss://relay.example.com"],
            read_models={"relays": ReadModelPolicy(enabled=True, price=1000)},
        )
        assert config.read_models["relays"].price == 1000
        assert config.read_models["relays"].enabled is True

    def test_read_models_require_canonical_names(self) -> None:
        with pytest.raises(
            ValueError,
            match=r"read_models contains non-public DVM read models: relay",
        ):
            DvmConfig(
                relays=["wss://relay.example.com"],
                read_models={"relay": ReadModelPolicy(enabled=True, price=1000)},
            )

    def test_tables_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="Use read_models instead of tables"):
            DvmConfig(
                relays=["wss://relay.example.com"],
                tables={"relay": ReadModelPolicy(enabled=True)},
            )

    def test_inherits_base_service_config(self) -> None:
        config = DvmConfig(relays=["wss://relay.example.com"], interval=120.0)
        assert config.interval == 120.0

    def test_invalid_relay_url_rejected(self) -> None:
        with pytest.raises(ValueError):
            DvmConfig(relays=["not_a_url"])

    def test_valid_relay_urls_accepted(self) -> None:
        config = DvmConfig(relays=["wss://relay.damus.io", "wss://nos.lol"])
        assert len(config.relays) == 2
        assert all(isinstance(r, Relay) for r in config.relays)

    def test_default_page_size_exceeds_max_rejected(self) -> None:
        with pytest.raises(ValueError, match="default_page_size"):
            DvmConfig(
                relays=["wss://relay.example.com"],
                default_page_size=500,
                max_page_size=100,
            )

    def test_default_page_size_equals_max_accepted(self) -> None:
        config = DvmConfig(
            relays=["wss://relay.example.com"],
            default_page_size=100,
            max_page_size=100,
        )
        assert config.default_page_size == config.max_page_size

    def test_internal_read_model_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"non-public DVM read models: service_state"):
            DvmConfig(
                relays=["wss://relay.example.com"],
                read_models={"service_state": ReadModelPolicy(enabled=True)},
            )


# ============================================================================
# Service Init
# ============================================================================


class TestDvm:
    def test_service_name(self) -> None:
        assert Dvm.SERVICE_NAME == ServiceName.DVM

    def test_config_class(self) -> None:
        assert Dvm.CONFIG_CLASS is DvmConfig

    def test_init(self, dvm_service: Dvm) -> None:
        assert dvm_service._client is None
        assert isinstance(dvm_service._client_manager, NostrClientManager)
        assert dvm_service._notification_task is None
        assert dvm_service._request_events is None
        assert dvm_service._request_subscription_id is None
        assert dvm_service._last_fetch_ts == 0
        assert dvm_service._last_fetch_id == "0" * 64
        assert dvm_service._processed_ids == set()


# ============================================================================
# Read Model Access Policy
# ============================================================================


class TestDvmReadModelAccessPolicy:
    def test_enabled_in_config(self, dvm_service: Dvm) -> None:
        assert dvm_service._read_models.resolve("dvm", "relays") is not None

    def test_not_in_config_disabled(self, dvm_service: Dvm) -> None:
        assert dvm_service._read_models.resolve("dvm", "service_state") is None

    def test_configured_internal_read_model_still_disabled(self, mock_brotr: Brotr) -> None:
        with pytest.raises(ValueError, match=r"non-public DVM read models: service_state"):
            DvmConfig(
                interval=60.0,
                relays=["wss://relay.example.com"],
                read_models={
                    "relays": ReadModelPolicy(enabled=True),
                    "service_state": ReadModelPolicy(enabled=True),
                },
            )

    def test_unknown_read_model_disabled(self, dvm_service: Dvm) -> None:
        assert dvm_service._read_models.resolve("dvm", "nonexistent") is None

    def test_free_price_default(self, dvm_service: Dvm) -> None:
        assert dvm_service._config.read_models["relays"].price == 0

    def test_paid_price(self, dvm_service: Dvm) -> None:
        assert dvm_service._config.read_models["events"].price == 5000

    def test_unknown_read_model_price_returns_zero(self, dvm_service: Dvm) -> None:
        assert (
            dvm_service._config.read_models.get("nonexistent-read-model", ReadModelPolicy()).price
            == 0
        )


class TestPrepareJobRequest:
    def test_accepts_canonical_read_model(
        self,
        dvm_config: DvmConfig,
        sample_dvm_catalog: Catalog,
    ) -> None:
        prepared = prepare_job_request(
            "relays",
            {"limit": "5"},
            context=JobPreparationContext(
                policies=dvm_config.read_models,
                available_catalog_names=set(sample_dvm_catalog.tables),
                default_page_size=dvm_config.default_page_size,
                max_page_size=dvm_config.max_page_size,
            ),
        )

        assert isinstance(prepared, PreparedJobRequest)
        assert prepared.read_model_id == "relays"
        assert prepared.read_model.read_model_id == "relays"
        assert prepared.query.limit == 5
        assert prepared.price == 0

    def test_rejects_disabled_read_model(
        self, dvm_config: DvmConfig, sample_dvm_catalog: Catalog
    ) -> None:
        rejected = prepare_job_request(
            "service_state",
            {},
            context=JobPreparationContext(
                policies=dvm_config.read_models,
                available_catalog_names=set(sample_dvm_catalog.tables),
                default_page_size=dvm_config.default_page_size,
                max_page_size=dvm_config.max_page_size,
            ),
        )

        assert isinstance(rejected, RejectedJobRequest)
        assert rejected.error_message == "Invalid or disabled read model: service_state"
        assert rejected.required_price is None

    def test_requires_payment_when_bid_too_low(
        self, dvm_config: DvmConfig, sample_dvm_catalog: Catalog
    ) -> None:
        rejected = prepare_job_request(
            "events",
            {"bid": 1000},
            context=JobPreparationContext(
                policies=dvm_config.read_models,
                available_catalog_names=set(sample_dvm_catalog.tables),
                default_page_size=dvm_config.default_page_size,
                max_page_size=dvm_config.max_page_size,
            ),
        )

        assert isinstance(rejected, RejectedJobRequest)
        assert rejected.required_price == 5000
        assert rejected.bid == 1000
        assert rejected.error_message is None

    def test_returns_client_error_for_invalid_query(
        self, dvm_config: DvmConfig, sample_dvm_catalog: Catalog
    ) -> None:
        rejected = prepare_job_request(
            "relays",
            {"limit": "not-a-number"},
            context=JobPreparationContext(
                policies=dvm_config.read_models,
                available_catalog_names=set(sample_dvm_catalog.tables),
                default_page_size=dvm_config.default_page_size,
                max_page_size=dvm_config.max_page_size,
            ),
        )

        assert isinstance(rejected, RejectedJobRequest)
        assert rejected.error_message == "Invalid limit or offset value"
        assert rejected.required_price is None


# ============================================================================
# Lifecycle
# ============================================================================


class TestDvmLifecycle:
    async def test_aenter_creates_client_and_connects(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        mock_client.send_event_builder = AsyncMock(return_value=_make_send_output())
        mock_manager = MagicMock()
        mock_manager.connect_session = AsyncMock(
            return_value=ClientSession(
                session_id="dvm-read-relays",
                client=mock_client,
                relay_urls=("wss://relay.example.com",),
                connect_result=ClientConnectResult(
                    connected=("wss://relay.example.com",),
                    failed={},
                ),
            )
        )
        mock_state_store = MagicMock()
        mock_state_store.fetch_cursors = AsyncMock(
            return_value=[DvmRequestCursor(key="job_requests", timestamp=1234, id="ab" * 32)]
        )
        dvm_service._client_manager = mock_manager
        dvm_service._state_store = mock_state_store

        with (
            patch.object(dvm_service, "_start_request_subscription", new_callable=AsyncMock),
            patch.object(dvm_service, "set_gauge"),
            patch.object(type(dvm_service), "__aexit__", new_callable=AsyncMock),
        ):
            await dvm_service.__aenter__()

            assert dvm_service._client is mock_client
            assert dvm_service._client_manager is mock_manager
            assert dvm_service._last_fetch_ts == 1234
            assert dvm_service._last_fetch_id == "ab" * 32
            mock_manager.connect_session.assert_awaited_once_with(
                "dvm-read-relays",
                dvm_service._config.relays,
                timeout=dvm_service._config.fetch_timeout,
            )
            mock_client.send_event_builder.assert_called_once()

    async def test_aenter_initializes_request_cursor_when_missing(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        mock_client.send_event_builder = AsyncMock(return_value=_make_send_output())
        mock_manager = MagicMock()
        mock_manager.connect_session = AsyncMock(
            return_value=ClientSession(
                session_id="dvm-read-relays",
                client=mock_client,
                relay_urls=("wss://relay.example.com",),
                connect_result=ClientConnectResult(
                    connected=("wss://relay.example.com",),
                    failed={},
                ),
            )
        )
        mock_state_store = MagicMock()
        mock_state_store.fetch_cursors = AsyncMock(
            return_value=[DvmRequestCursor(key="job_requests")]
        )
        mock_state_store.upsert_cursors = AsyncMock(return_value=1)
        dvm_service._client_manager = mock_manager
        dvm_service._state_store = mock_state_store

        with (
            patch.object(dvm_service, "_start_request_subscription", new_callable=AsyncMock),
            patch("bigbrotr.services.dvm.service.time") as mock_time,
            patch.object(dvm_service, "set_gauge"),
            patch.object(type(dvm_service), "__aexit__", new_callable=AsyncMock),
        ):
            mock_time.time.return_value = 4321
            await dvm_service.__aenter__()

        assert dvm_service._last_fetch_ts == 4321
        assert dvm_service._last_fetch_id == "0" * 64
        mock_state_store.upsert_cursors.assert_awaited_once()

    async def test_aenter_skips_announcement_when_disabled(self, mock_brotr: Brotr) -> None:
        config = DvmConfig(
            interval=60.0,
            relays=["wss://relay.example.com"],
            announce=False,
            read_models={"relays": ReadModelPolicy(enabled=True)},
        )
        service = Dvm(brotr=mock_brotr, config=config)
        service._read_models.catalog = Catalog()
        service._read_models.catalog._tables = {
            "relay": TableSchema(
                name="relay",
                columns=(ColumnSchema(name="url", pg_type="text", nullable=False),),
                primary_key=("url",),
                is_view=False,
            ),
        }

        mock_client = MagicMock()
        mock_client.send_event_builder = AsyncMock(return_value=_make_send_output())
        mock_manager = MagicMock()
        mock_manager.connect_session = AsyncMock(
            return_value=ClientSession(
                session_id="dvm-read-relays",
                client=mock_client,
                relay_urls=("wss://relay.example.com",),
                connect_result=ClientConnectResult(
                    connected=("wss://relay.example.com",),
                    failed={},
                ),
            )
        )
        service._client_manager = mock_manager

        with (
            patch.object(service, "_start_request_subscription", new_callable=AsyncMock),
            patch.object(service, "set_gauge"),
            patch.object(type(service), "__aexit__", new_callable=AsyncMock),
        ):
            await service.__aenter__()

            mock_client.send_event_builder.assert_not_called()

    async def test_aenter_fails_fast_when_no_relays_connect(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        mock_manager = MagicMock()
        mock_manager.connect_session = AsyncMock(
            return_value=ClientSession(
                session_id="dvm-read-relays",
                client=mock_client,
                relay_urls=("wss://relay.example.com",),
                connect_result=ClientConnectResult(
                    connected=(),
                    failed={"wss://relay.example.com": "timeout"},
                ),
            )
        )
        mock_manager.disconnect = AsyncMock()
        mock_state_store = MagicMock()
        mock_state_store.fetch_cursors = AsyncMock(
            return_value=[DvmRequestCursor(key="job_requests", timestamp=1234, id="ab" * 32)]
        )
        dvm_service._client_manager = mock_manager
        dvm_service._state_store = mock_state_store

        with (
            patch.object(dvm_service, "_start_request_subscription", new_callable=AsyncMock),
            patch.object(dvm_service, "set_gauge"),
            patch.object(type(dvm_service), "__aexit__", new_callable=AsyncMock),
            pytest.raises(TimeoutError, match="dvm could not connect to any relay"),
        ):
            await dvm_service.__aenter__()

        mock_manager.disconnect.assert_awaited_once()
        assert dvm_service._client is None

    async def test_aenter_disconnects_if_announcement_fails_after_subscription_start(
        self, dvm_service: Dvm
    ) -> None:
        mock_client = MagicMock()
        mock_manager = MagicMock()
        mock_manager.connect_session = AsyncMock(
            return_value=ClientSession(
                session_id="dvm-read-relays",
                client=mock_client,
                relay_urls=("wss://relay.example.com",),
                connect_result=ClientConnectResult(
                    connected=("wss://relay.example.com",),
                    failed={},
                ),
            )
        )
        mock_manager.disconnect = AsyncMock()
        mock_state_store = MagicMock()
        mock_state_store.fetch_cursors = AsyncMock(
            return_value=[DvmRequestCursor(key="job_requests", timestamp=1234, id="ab" * 32)]
        )
        dvm_service._stop_request_subscription = AsyncMock()  # type: ignore[method-assign]
        dvm_service._client_manager = mock_manager
        dvm_service._state_store = mock_state_store

        with (
            patch.object(dvm_service, "_start_request_subscription", new_callable=AsyncMock),
            patch.object(dvm_service, "_publish_announcement", new_callable=AsyncMock) as announce,
            patch.object(dvm_service, "set_gauge"),
            patch.object(type(dvm_service), "__aexit__", new_callable=AsyncMock),
            pytest.raises(OSError, match="announce failed"),
        ):
            announce.side_effect = OSError("announce failed")
            await dvm_service.__aenter__()

        dvm_service._stop_request_subscription.assert_awaited_once()  # type: ignore[attr-defined]
        mock_manager.disconnect.assert_awaited_once()
        assert dvm_service._client is None

    async def test_aexit_shuts_down_client(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        dvm_service._client_manager = MagicMock(disconnect=AsyncMock())
        dvm_service._stop_request_subscription = AsyncMock()  # type: ignore[method-assign]
        dvm_service._client = mock_client

        with patch.object(BaseService, "__aexit__", new_callable=AsyncMock):
            await dvm_service.__aexit__(None, None, None)

        dvm_service._stop_request_subscription.assert_awaited_once()  # type: ignore[attr-defined]
        dvm_service._client_manager.disconnect.assert_awaited_once()
        assert dvm_service._client is None

    async def test_aexit_handles_shutdown_error(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        dvm_service._client_manager = NostrClientManager(keys=dvm_service._keys)
        dvm_service._client_manager._sessions["dvm-read-relays"] = ClientSession(
            session_id="dvm-read-relays",
            client=mock_client,
            relay_urls=("wss://relay.example.com",),
            connect_result=ClientConnectResult(
                connected=("wss://relay.example.com",),
                failed={},
            ),
        )
        dvm_service._client = mock_client
        dvm_service._stop_request_subscription = AsyncMock()  # type: ignore[method-assign]

        with (
            patch.object(BaseService, "__aexit__", new_callable=AsyncMock),
            patch(
                "bigbrotr.utils.protocol.shutdown_client",
                new_callable=AsyncMock,
                side_effect=RuntimeError("FFI"),
            ),
        ):
            await dvm_service.__aexit__(None, None, None)

        dvm_service._stop_request_subscription.assert_awaited_once()  # type: ignore[attr-defined]
        assert dvm_service._client is None

    async def test_aexit_noop_when_no_client(self, dvm_service: Dvm) -> None:
        dvm_service._client = None

        with patch.object(BaseService, "__aexit__", new_callable=AsyncMock):
            await dvm_service.__aexit__(None, None, None)

    async def test_cleanup_returns_zero(self, dvm_service: Dvm) -> None:
        result = await dvm_service.cleanup()
        assert result == 0

    def test_state_store_is_initialized_once(self, dvm_service: Dvm) -> None:
        assert isinstance(dvm_service._state_store, ServiceStateStore)
        assert dvm_service._state_store._brotr is dvm_service._brotr


# ============================================================================
# Run
# ============================================================================


class TestDvmRun:
    async def test_run_no_client(self, dvm_service: Dvm) -> None:
        await dvm_service.run()

    async def test_run_no_events(self, dvm_service: Dvm) -> None:
        mock_client = _make_client_with_events([])
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [])

        with (
            patch.object(dvm_service, "set_gauge") as mock_gauge,
            patch.object(dvm_service, "inc_counter"),
        ):
            await dvm_service.run()

        mock_gauge.assert_any_call(
            "read_models_exposed",
            len(dvm_service._read_models.enabled_names("dvm")),
        )

    async def test_run_no_events_does_not_advance_cursor(self, dvm_service: Dvm) -> None:
        mock_client = _make_client_with_events([])
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [])
        mock_state_store = MagicMock()
        mock_state_store.upsert_cursors = AsyncMock(return_value=1)
        dvm_service._state_store = mock_state_store

        with (
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter"),
        ):
            await dvm_service.run()

        assert dvm_service._last_fetch_ts == 0
        assert dvm_service._last_fetch_id == "0" * 64
        mock_state_store.upsert_cursors.assert_not_awaited()

    async def test_run_processes_job(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(
            tags=[["param", "read_model", "relays"], ["param", "limit", "10"]],
            created_at=2000,
        )
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [event])
        mock_state_store = MagicMock()
        mock_state_store.upsert_cursors = AsyncMock(return_value=1)

        mock_result = QueryResult(
            rows=[{"url": "wss://x", "network": "clearnet"}],
            total=1,
            limit=10,
            offset=0,
        )
        dvm_service._state_store = mock_state_store
        with (
            patch.object(
                dvm_service._read_models.catalog,
                "query",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter"),
        ):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()
        builder = mock_client.send_event_builder.await_args.args[0]
        published = builder.sign_with_keys(_KEYS)
        assert json.loads(published.content())["meta"]["read_model"] == "relays"
        assert dvm_service._last_fetch_ts == 2000
        assert dvm_service._last_fetch_id == "abc123"
        mock_state_store.upsert_cursors.assert_awaited_once()

    async def test_run_dedup(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(
            event_id="dedup_id",
            tags=[["param", "read_model", "relays"]],
        )
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [event])
        dvm_service._processed_ids.add("dedup_id")

        with patch.object(dvm_service, "set_gauge"), patch.object(dvm_service, "inc_counter"):
            await dvm_service.run()

        mock_client.send_event_builder.assert_not_called()

    async def test_run_disabled_read_model(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["param", "read_model", "service_state"]])
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [event])

        with patch.object(dvm_service, "set_gauge"), patch.object(dvm_service, "inc_counter"):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()

    async def test_run_empty_read_model_name(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["param", "read_model", ""]])
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [event])

        with patch.object(dvm_service, "set_gauge"), patch.object(dvm_service, "inc_counter"):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()

    async def test_run_missing_read_model_param(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["param", "limit", "10"]])
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [event])

        with patch.object(dvm_service, "set_gauge"), patch.object(dvm_service, "inc_counter"):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()

    async def test_run_payment_required(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["param", "read_model", "events"]])
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [event])

        with patch.object(dvm_service, "set_gauge"), patch.object(dvm_service, "inc_counter"):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()

    async def test_run_sufficient_bid(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["param", "read_model", "events"], ["bid", "10000"]])
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [event])

        mock_result = QueryResult(rows=[], total=0, limit=100, offset=0)
        with (
            patch.object(
                dvm_service._read_models.catalog,
                "query",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_query,
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter"),
        ):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()
        _, kwargs = mock_query.call_args
        assert kwargs["include_total"] is False

    async def test_run_include_total_opt_in(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(
            tags=[["param", "read_model", "relays"], ["param", "include_total", "true"]]
        )
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [event])

        mock_result = QueryResult(rows=[], total=1, limit=100, offset=0)
        with (
            patch.object(
                dvm_service._read_models.catalog,
                "query",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_query,
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter"),
        ):
            await dvm_service.run()

        _, kwargs = mock_query.call_args
        assert kwargs["include_total"] is True

    async def test_run_cursor_opt_in(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(
            tags=[["param", "read_model", "relays"], ["param", "cursor", "opaque-token"]]
        )
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [event])

        mock_result = QueryResult(rows=[], total=None, limit=100, offset=0)
        with (
            patch.object(
                dvm_service._read_models.catalog,
                "query",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_query,
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter"),
        ):
            await dvm_service.run()

        _, kwargs = mock_query.call_args
        assert kwargs["cursor"] == "opaque-token"

    async def test_run_rejects_cursor_with_offset(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(
            tags=[
                ["param", "read_model", "relays"],
                ["param", "cursor", "opaque-token"],
                ["param", "offset", "1"],
            ]
        )
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [event])

        with patch.object(dvm_service, "set_gauge"), patch.object(dvm_service, "inc_counter"):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()

    async def test_run_invalid_limit(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(
            tags=[["param", "read_model", "relays"], ["param", "limit", "not_a_number"]]
        )
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [event])

        with patch.object(dvm_service, "set_gauge"), patch.object(dvm_service, "inc_counter"):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()

    async def test_run_updates_request_cursor_after_processing(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["param", "read_model", "relays"]], created_at=1000)
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [event])
        mock_state_store = MagicMock()
        mock_state_store.upsert_cursors = AsyncMock(return_value=1)

        mock_result = QueryResult(rows=[], total=0, limit=100, offset=0)
        dvm_service._state_store = mock_state_store
        with (
            patch.object(
                dvm_service._read_models.catalog,
                "query",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter"),
        ):
            await dvm_service.run()

        assert dvm_service._last_fetch_ts == 1000
        assert dvm_service._last_fetch_id == "abc123"
        mock_state_store.upsert_cursors.assert_awaited_once()

    async def test_run_publish_error_failure_does_not_abort_batch(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        mock_client.send_event_builder = AsyncMock(
            side_effect=[OSError("relay offline"), _make_send_output(), _make_send_output()],
        )

        event1 = _make_mock_event(
            event_id="fail_pub",
            tags=[["param", "read_model", "service_state"]],
        )
        event2 = _make_mock_event(
            event_id="ok_pub",
            tags=[["param", "read_model", "relays"]],
        )
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [event1, event2])

        mock_result = QueryResult(rows=[], total=0, limit=100, offset=0)
        with (
            patch.object(
                dvm_service._read_models.catalog,
                "query",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter"),
        ):
            await dvm_service.run()

        assert mock_client.send_event_builder.call_count == 3

    async def test_processed_ids_reset(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(
            event_id="trigger",
            tags=[["param", "read_model", "relays"]],
        )
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [event])

        dvm_service._processed_ids = {str(i) for i in range(10_001)}

        mock_result = QueryResult(rows=[], total=0, limit=100, offset=0)
        with (
            patch.object(
                dvm_service._read_models.catalog,
                "query",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter"),
        ):
            await dvm_service.run()

        assert len(dvm_service._processed_ids) == 0


# ============================================================================
# P-tag Targeting
# ============================================================================


class TestDvmPtagTargeting:
    async def test_p_tag_for_other_pubkey_skips_event(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(
            tags=[["p", "other_pubkey_hex"], ["param", "read_model", "relays"]]
        )
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [event])

        with patch.object(dvm_service, "set_gauge"), patch.object(dvm_service, "inc_counter"):
            await dvm_service.run()

        mock_client.send_event_builder.assert_not_called()

    async def test_no_p_tag_processes_event(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["param", "read_model", "relays"]])
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [event])

        mock_result = QueryResult(rows=[], total=0, limit=100, offset=0)
        with (
            patch.object(
                dvm_service._read_models.catalog,
                "query",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter"),
        ):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()


# ============================================================================
# Error Handling
# ============================================================================


class TestDvmJobErrorHandling:
    @pytest.mark.parametrize(
        "error",
        [
            CatalogError("query failed"),
            OSError("network error"),
            TimeoutError("timed out"),
            asyncpg.PostgresError("operator does not exist"),
        ],
        ids=["CatalogError", "OSError", "TimeoutError", "PostgresError"],
    )
    async def test_caught_error_publishes_error_and_increments_failed(
        self, dvm_service: Dvm, error: Exception
    ) -> None:
        event = _make_mock_event(tags=[["param", "read_model", "relays"]])
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [event])

        with (
            patch.object(
                dvm_service._read_models.catalog,
                "query",
                new_callable=AsyncMock,
                side_effect=error,
            ),
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter") as mock_counter,
        ):
            await dvm_service.run()

        mock_counter.assert_any_call("requests_failed", 1)
        mock_client.send_event_builder.assert_called_once()

    async def test_result_publish_without_success_counts_as_failed(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["param", "read_model", "relays"]])
        mock_client = _make_client_with_events([event])
        mock_client.send_event_builder = AsyncMock(
            side_effect=[
                _make_send_output(
                    success_relays=(),
                    failed_relays={"wss://relay.example.com": "rejected"},
                ),
                _make_send_output(),
            ]
        )
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [event])

        mock_result = QueryResult(rows=[], total=0, limit=100, offset=0)
        with (
            patch.object(
                dvm_service._read_models.catalog,
                "query",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter") as mock_counter,
        ):
            await dvm_service.run()

        mock_counter.assert_any_call("requests_failed", 1)
        assert mock_client.send_event_builder.call_count == 2

    async def test_error_event_publish_failure_suppressed(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["param", "read_model", "relays"]])
        mock_client = _make_client_with_events([event])
        mock_client.send_event_builder = AsyncMock(side_effect=OSError("relay down"))
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [event])

        with (
            patch.object(
                dvm_service._read_models.catalog,
                "query",
                new_callable=AsyncMock,
                side_effect=CatalogError("query failed"),
            ),
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter") as mock_counter,
        ):
            await dvm_service.run()

        mock_counter.assert_any_call("requests_failed", 1)


# ============================================================================
# Metrics
# ============================================================================


class TestDvmMetrics:
    async def test_report_metrics_emits_requests_total(self, dvm_service: Dvm) -> None:
        event = _make_mock_event(tags=[["param", "read_model", "relays"], ["param", "limit", "5"]])
        mock_client = _make_client_with_events([event])
        dvm_service._client = mock_client
        await _seed_request_events(dvm_service, [event])

        mock_result = QueryResult(
            rows=[{"url": "wss://x", "network": "clearnet"}],
            total=1,
            limit=5,
            offset=0,
        )

        with (
            patch.object(
                dvm_service._read_models.catalog,
                "query",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter") as mock_counter,
        ):
            await dvm_service.run()

        mock_counter.assert_any_call("requests_total", 1)


# ============================================================================
# Publishing Guards (client is None)
# ============================================================================


class TestDvmPublishingGuards:
    async def test_send_event_no_client(self, dvm_service: Dvm) -> None:
        dvm_service._client = None
        assert await dvm_service._send_event(build_error_event("eid", "pk", "err")) == ((), {})

    async def test_publish_announcement_no_client(self, dvm_service: Dvm) -> None:
        dvm_service._client = None
        await dvm_service._publish_announcement()

    async def test_publish_announcement_sends_event(self, dvm_service: Dvm) -> None:
        mock_client = MagicMock()
        mock_client.send_event_builder = AsyncMock(return_value=_make_send_output())
        dvm_service._client = mock_client

        await dvm_service._publish_announcement()

        mock_client.send_event_builder.assert_called_once()

    def test_enabled_read_model_names_follow_registry(self, dvm_service: Dvm) -> None:
        assert dvm_service._read_models.enabled_names("dvm") == ["events", "relays"]

    async def test_publish_announcement_logs_warning_when_unaccepted(
        self, dvm_service: Dvm
    ) -> None:
        mock_client = MagicMock()
        mock_client.send_event_builder = AsyncMock(
            return_value=_make_send_output(
                success_relays=(),
                failed_relays={"wss://relay.example.com": "rejected"},
            )
        )
        dvm_service._client = mock_client

        with patch.object(dvm_service._logger, "warning") as mock_warning:
            await dvm_service._publish_announcement()

        mock_warning.assert_called_once_with(
            "announcement_publish_failed",
            kind=31990,
            error="no relays accepted announcement",
            failed_relays={"wss://relay.example.com": "rejected"},
        )

    async def test_run_skips_events_at_or_before_persisted_cursor(self, dvm_service: Dvm) -> None:
        older = _make_mock_event(event_id="aa", created_at=900)
        same_position = _make_mock_event(event_id="bb", created_at=1000)
        newer = _make_mock_event(event_id="cc", created_at=1000)
        mock_client = _make_client_with_events([older, same_position, newer])
        dvm_service._client = mock_client
        dvm_service._last_fetch_ts = 1000
        dvm_service._last_fetch_id = "bb"
        await _seed_request_events(dvm_service, [newer, older, same_position])

        mock_result = QueryResult(rows=[], total=0, limit=100, offset=0)
        with (
            patch.object(
                dvm_service._read_models.catalog,
                "query",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter"),
        ):
            await dvm_service.run()

        mock_client.send_event_builder.assert_called_once()
        assert dvm_service._last_fetch_id == "cc"

    async def test_run_processes_buffered_events_in_cursor_order(self, dvm_service: Dvm) -> None:
        older = _make_mock_event(event_id="bb", created_at=1000)
        newer = _make_mock_event(event_id="aa", created_at=2000)
        same_ts_lower_id = _make_mock_event(event_id="aa", created_at=1000)
        dvm_service._client = _make_client_with_events([])
        await _seed_request_events(dvm_service, [newer, older, same_ts_lower_id])

        processed_ids: list[str] = []
        mock_state_store = MagicMock()
        mock_state_store.upsert_cursors = AsyncMock(return_value=1)
        dvm_service._state_store = mock_state_store

        async def process_event(event: MagicMock, _pubkey_hex: str) -> tuple[int, int, int, int]:
            processed_ids.append(event.id().to_hex())
            return 1, 1, 0, 0

        with (
            patch.object(dvm_service, "_process_event", side_effect=process_event),
            patch.object(dvm_service, "set_gauge"),
            patch.object(dvm_service, "inc_counter"),
        ):
            await dvm_service.run()

        assert processed_ids == ["aa", "bb", "aa"]
        mock_state_store.upsert_cursors.assert_awaited_once()


# ============================================================================
# Parse Job Params
# ============================================================================

_KEYS = Keys.generate()


def _make_utils_mock_event(tags: list[list[str]]) -> MagicMock:
    event = MagicMock()
    mock_tags = []
    for tag_values in tags:
        mock_tag = MagicMock()
        mock_tag.as_vec.return_value = tag_values
        mock_tags.append(mock_tag)
    tag_list = MagicMock()
    tag_list.to_vec.return_value = mock_tags
    event.tags.return_value = tag_list
    return event


def _tags_dict(event) -> dict[str, list[list[str]]]:
    result: dict[str, list[list[str]]] = {}
    for tag in event.tags().to_vec():
        vec = tag.as_vec()
        result.setdefault(vec[0], []).append(vec)
    return result


class TestParseJobParams:
    def test_basic_params(self) -> None:
        event = _make_utils_mock_event(
            tags=[
                ["param", "read_model", "relays"],
                ["param", "limit", "50"],
                ["param", "offset", "10"],
            ]
        )
        params = parse_job_params(event)
        assert params["read_model"] == "relays"
        assert params["limit"] == "50"
        assert params["offset"] == "10"

    def test_bid_tag(self) -> None:
        event = _make_utils_mock_event(
            tags=[
                ["param", "read_model", "relays"],
                ["bid", "5000"],
            ]
        )
        params = parse_job_params(event)
        assert params["bid"] == 5000

    def test_invalid_bid_ignored(self) -> None:
        event = _make_utils_mock_event(
            tags=[
                ["param", "read_model", "relays"],
                ["bid", "not_a_number"],
            ]
        )
        params = parse_job_params(event)
        assert "bid" not in params

    def test_empty_tags(self) -> None:
        event = _make_utils_mock_event(tags=[])
        assert parse_job_params(event) == {}

    def test_filter_and_sort(self) -> None:
        event = _make_utils_mock_event(
            tags=[
                ["param", "read_model", "relays"],
                ["param", "filter", "network=clearnet"],
                ["param", "sort", "url:asc"],
            ]
        )
        params = parse_job_params(event)
        assert params["filter"] == "network=clearnet"
        assert params["sort"] == "url:asc"

    def test_short_tags_ignored(self) -> None:
        event = _make_utils_mock_event(tags=[["param"], ["bid"], ["x"]])
        assert parse_job_params(event) == {}

    def test_param_with_only_two_elements_ignored(self) -> None:
        event = _make_utils_mock_event(tags=[["param", "read_model"]])
        assert parse_job_params(event) == {}


# ============================================================================
# Build Result Event
# ============================================================================


class TestBuildResultEvent:
    def test_result_kind_is_request_plus_1000(self) -> None:
        result = QueryResult(rows=[], total=0, limit=10, offset=0)
        event = build_result_event(
            ResultEventRequest(5050, "eid", "pk", "relays"),
            result,
            0,
        ).sign_with_keys(_KEYS)
        assert event.kind().as_u16() == 6050

    def test_content_contains_data_and_meta(self) -> None:
        result = QueryResult(
            rows=[{"url": "wss://r.io"}],
            total=1,
            limit=10,
            offset=0,
            next_cursor="opaque-token",
        )
        event = build_result_event(
            ResultEventRequest(5050, "eid", "pk", "relays"),
            result,
            0,
        ).sign_with_keys(_KEYS)
        content = json.loads(event.content())
        assert content["data"] == [{"url": "wss://r.io"}]
        assert content["meta"] == {
            "total": 1,
            "limit": 10,
            "offset": 0,
            "next_cursor": "opaque-token",
            "read_model": "relays",
        }

    def test_content_omits_total_when_not_requested(self) -> None:
        result = QueryResult(rows=[{"url": "wss://r.io"}], total=None, limit=10, offset=0)
        event = build_result_event(
            ResultEventRequest(5050, "eid", "pk", "relays"),
            result,
            0,
        ).sign_with_keys(_KEYS)
        content = json.loads(event.content())
        assert content["meta"] == {
            "limit": 10,
            "offset": 0,
            "read_model": "relays",
        }

    def test_amount_tag_included_when_price_positive(self) -> None:
        result = QueryResult(rows=[], total=0, limit=10, offset=0)
        event = build_result_event(
            ResultEventRequest(5050, "eid", "pk", "relays"),
            result,
            500,
        ).sign_with_keys(_KEYS)
        tags = _tags_dict(event)
        assert tags["amount"] == [["amount", "500"]]

    def test_no_amount_tag_when_price_zero(self) -> None:
        result = QueryResult(rows=[], total=0, limit=10, offset=0)
        event = build_result_event(
            ResultEventRequest(5050, "eid", "pk", "relays"),
            result,
            0,
        ).sign_with_keys(_KEYS)
        tags = _tags_dict(event)
        assert "amount" not in tags


# ============================================================================
# Build Error Event
# ============================================================================


class TestBuildErrorEvent:
    def test_kind_7000(self) -> None:
        event = build_error_event("eid", "pk", "something broke").sign_with_keys(_KEYS)
        assert event.kind().as_u16() == 7000

    def test_status_tag_contains_error_message(self) -> None:
        event = build_error_event("eid", "pk", "something broke").sign_with_keys(_KEYS)
        tags = _tags_dict(event)
        assert tags["status"] == [["status", "error", "something broke"]]


# ============================================================================
# Build Payment Required Event
# ============================================================================


class TestBuildPaymentRequiredEvent:
    def test_kind_7000(self) -> None:
        event = build_payment_required_event("eid", "pk", 5000).sign_with_keys(_KEYS)
        assert event.kind().as_u16() == 7000

    def test_amount_tag_present(self) -> None:
        event = build_payment_required_event("eid", "pk", 5000).sign_with_keys(_KEYS)
        tags = _tags_dict(event)
        assert tags["amount"] == [["amount", "5000"]]

    def test_status_tag_payment_required(self) -> None:
        event = build_payment_required_event("eid", "pk", 5000).sign_with_keys(_KEYS)
        tags = _tags_dict(event)
        assert len(tags["status"]) == 1
        assert tags["status"][0][1] == "payment-required"


# ============================================================================
# Build Announcement Event
# ============================================================================


class TestBuildAnnouncementEvent:
    def test_kind_31990(self) -> None:
        event = build_announcement_event("dtag", 5050, "DVM", "about", ["relays"]).sign_with_keys(
            _KEYS
        )
        assert event.kind().as_u16() == 31990

    def test_content_contains_name_about_read_models(self) -> None:
        event = build_announcement_event("dtag", 5050, "MyDVM", "desc", ["a", "b"]).sign_with_keys(
            _KEYS
        )
        content = json.loads(event.content())
        assert content["name"] == "MyDVM"
        assert content["about"] == "desc"
        assert content["read_models"] == ["a", "b"]

    def test_d_and_k_tags(self) -> None:
        event = build_announcement_event("my-d", 5050, "n", "a", []).sign_with_keys(_KEYS)
        tags = _tags_dict(event)
        assert tags["d"] == [["d", "my-d"]]
        assert tags["k"] == [["k", "5050"]]
