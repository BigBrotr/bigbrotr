"""Unit tests for the refresher service package."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from bigbrotr.core.brotr import Brotr, BrotrConfig
from bigbrotr.services.refresher import RefreshConfig, Refresher, RefresherConfig
from bigbrotr.services.refresher.configs import DEFAULT_MATVIEWS, DEFAULT_SUMMARIES


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_refresher_brotr(mock_brotr: Brotr) -> Brotr:
    mock_brotr.refresh_materialized_view = AsyncMock()  # type: ignore[method-assign]
    mock_brotr.get_service_state = AsyncMock(return_value=[])  # type: ignore[method-assign]
    mock_brotr.upsert_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]
    mock_brotr.delete_service_state = AsyncMock(return_value=0)  # type: ignore[method-assign]
    mock_brotr.fetchval = AsyncMock(return_value=0)  # type: ignore[method-assign]
    mock_brotr.execute = AsyncMock()  # type: ignore[method-assign]

    mock_config = MagicMock(spec=BrotrConfig)
    mock_config.timeouts = MagicMock()
    mock_config.timeouts.refresh = None
    mock_brotr._config = mock_config

    return mock_brotr


# ============================================================================
# Configs — RefreshConfig
# ============================================================================


class TestRefreshConfig:
    def test_default_values(self) -> None:
        config = RefreshConfig()

        assert config.matviews == DEFAULT_MATVIEWS
        assert config.summaries == DEFAULT_SUMMARIES
        assert len(config.matviews) == 4
        assert len(config.summaries) == 12

    def test_default_matviews_dependency_order(self) -> None:
        config = RefreshConfig()
        matviews = config.matviews

        # relay_metadata_latest must come before dependent views
        rml_idx = matviews.index("relay_metadata_latest")
        rsc_idx = matviews.index("relay_software_counts")
        snc_idx = matviews.index("supported_nip_counts")
        assert rml_idx < rsc_idx
        assert rml_idx < snc_idx

    def test_default_summaries_dependency_order(self) -> None:
        config = RefreshConfig()
        summaries = config.summaries

        # Cross-tabs must come before entity tables
        pks_idx = summaries.index("pubkey_kind_stats")
        prs_idx = summaries.index("pubkey_relay_stats")
        rks_idx = summaries.index("relay_kind_stats")
        ps_idx = summaries.index("pubkey_stats")
        ks_idx = summaries.index("kind_stats")
        rs_idx = summaries.index("relay_stats")

        assert pks_idx < ps_idx
        assert pks_idx < ks_idx
        assert prs_idx < ps_idx
        assert prs_idx < rs_idx
        assert rks_idx < ks_idx
        assert rks_idx < rs_idx

    def test_custom_matviews(self) -> None:
        config = RefreshConfig(matviews=["relay_metadata_latest"])
        assert config.matviews == ["relay_metadata_latest"]

    def test_custom_summaries(self) -> None:
        config = RefreshConfig(summaries=["pubkey_stats"])
        assert config.summaries == ["pubkey_stats"]

    def test_empty_matviews_rejected(self) -> None:
        with pytest.raises(ValueError, match="matviews list must not be empty"):
            RefreshConfig(matviews=[])

    def test_empty_summaries_rejected(self) -> None:
        with pytest.raises(ValueError, match="summaries list must not be empty"):
            RefreshConfig(summaries=[])

    @pytest.mark.parametrize(
        "name",
        [
            "relay_stats",
            "daily_counts",
            "a",
            "_private_view",
            "view123",
        ],
    )
    def test_valid_names_accepted(self, name: str) -> None:
        config = RefreshConfig(matviews=[name], summaries=[name])
        assert config.matviews == [name]
        assert config.summaries == [name]

    @pytest.mark.parametrize(
        "name",
        [
            "relay-stats",
            "UPPERCASE",
            "DROP TABLE",
            "123starts_with_digit",
            "has.dot",
            "semi;colon",
        ],
    )
    def test_invalid_names_rejected(self, name: str) -> None:
        with pytest.raises(ValueError, match="invalid"):
            RefreshConfig(matviews=[name])
        with pytest.raises(ValueError, match="invalid"):
            RefreshConfig(summaries=[name])

    def test_default_lists_are_independent_copies(self) -> None:
        config1 = RefreshConfig()
        config2 = RefreshConfig()
        assert config1.matviews is not config2.matviews
        assert config1.summaries is not config2.summaries


# ============================================================================
# Configs — RefresherConfig
# ============================================================================


class TestRefresherConfig:
    def test_default_values(self) -> None:
        config = RefresherConfig()

        assert config.refresh.matviews == DEFAULT_MATVIEWS
        assert config.refresh.summaries == DEFAULT_SUMMARIES
        assert config.interval == 86400.0
        assert config.max_consecutive_failures == 5

    def test_custom_nested_config(self) -> None:
        config = RefresherConfig(
            refresh=RefreshConfig(matviews=["relay_metadata_latest"], summaries=["pubkey_stats"]),
        )
        assert config.refresh.matviews == ["relay_metadata_latest"]
        assert config.refresh.summaries == ["pubkey_stats"]

    def test_from_dict_nested(self) -> None:
        data = {
            "refresh": {
                "matviews": ["relay_metadata_latest"],
                "summaries": ["pubkey_stats", "kind_stats"],
            },
            "interval": 1800.0,
        }
        config = RefresherConfig(**data)
        assert config.refresh.matviews == ["relay_metadata_latest"]
        assert config.refresh.summaries == ["pubkey_stats", "kind_stats"]
        assert config.interval == 1800.0


# ============================================================================
# Service — Init
# ============================================================================


class TestRefresherInit:
    def test_init_with_defaults(self, mock_refresher_brotr: Brotr) -> None:
        refresher = Refresher(brotr=mock_refresher_brotr)

        assert refresher._brotr is mock_refresher_brotr
        assert refresher.SERVICE_NAME == "refresher"
        assert refresher.config.refresh.matviews == DEFAULT_MATVIEWS
        assert refresher.config.refresh.summaries == DEFAULT_SUMMARIES
        assert refresher._logger is not None

    def test_init_with_custom_config(self, mock_refresher_brotr: Brotr) -> None:
        config = RefresherConfig(
            refresh=RefreshConfig(
                matviews=["relay_metadata_latest"],
                summaries=["pubkey_kind_stats"],
            ),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        assert refresher.config.refresh.matviews == ["relay_metadata_latest"]
        assert refresher.config.refresh.summaries == ["pubkey_kind_stats"]

    def test_init_reorders_known_objects_canonically(self, mock_refresher_brotr: Brotr) -> None:
        config = RefresherConfig(
            refresh=RefreshConfig(
                matviews=["supported_nip_counts", "relay_metadata_latest"],
                summaries=[
                    "contact_list_edges_current",
                    "events_replaceable_current",
                    "contact_lists_current",
                ],
            ),
        )

        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        assert refresher.config.refresh.matviews == [
            "relay_metadata_latest",
            "supported_nip_counts",
        ]
        assert refresher.config.refresh.summaries == [
            "events_replaceable_current",
            "contact_lists_current",
            "contact_list_edges_current",
        ]

    def test_init_rejects_missing_summary_dependencies(self, mock_refresher_brotr: Brotr) -> None:
        config = RefresherConfig(
            refresh=RefreshConfig(
                matviews=["relay_metadata_latest"],
                summaries=["contact_list_edges_current"],
            ),
        )

        with pytest.raises(ValueError, match="contact_list_edges_current requires"):
            Refresher(brotr=mock_refresher_brotr, config=config)

    def test_init_rejects_contact_lists_without_replaceable_current(
        self, mock_refresher_brotr: Brotr
    ) -> None:
        config = RefresherConfig(
            refresh=RefreshConfig(
                matviews=["relay_metadata_latest"],
                summaries=["contact_lists_current"],
            ),
        )

        with pytest.raises(ValueError, match="contact_lists_current requires"):
            Refresher(brotr=mock_refresher_brotr, config=config)

    def test_config_class_attribute(self) -> None:
        assert Refresher.CONFIG_CLASS is RefresherConfig


# ============================================================================
# Service — cleanup
# ============================================================================


class TestRefresherCleanup:
    async def test_cleanup_no_stale(self, mock_refresher_brotr: Brotr) -> None:
        mock_refresher_brotr.get_service_state = AsyncMock(return_value=[])  # type: ignore[method-assign]
        refresher = Refresher(brotr=mock_refresher_brotr)

        result = await refresher.cleanup()

        assert result == 0

    async def test_cleanup_removes_stale_checkpoints(self, mock_refresher_brotr: Brotr) -> None:
        from bigbrotr.models.constants import ServiceName
        from bigbrotr.models.service_state import ServiceState, ServiceStateType

        stale = ServiceState(
            service_name=ServiceName.REFRESHER,
            state_type=ServiceStateType.CHECKPOINT,
            state_key="old_removed_table",
            state_value={"timestamp": 100},
        )
        current = ServiceState(
            service_name=ServiceName.REFRESHER,
            state_type=ServiceStateType.CHECKPOINT,
            state_key="pubkey_kind_stats",
            state_value={"timestamp": 200},
        )
        mock_refresher_brotr.get_service_state = AsyncMock(  # type: ignore[method-assign]
            return_value=[stale, current]
        )
        mock_refresher_brotr.delete_service_state = AsyncMock(return_value=1)  # type: ignore[method-assign]

        config = RefresherConfig(
            refresh=RefreshConfig(
                matviews=["relay_metadata_latest"],
                summaries=["pubkey_kind_stats"],
            ),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        result = await refresher.cleanup()

        assert result == 1
        mock_refresher_brotr.delete_service_state.assert_called_once()
        call_kwargs = mock_refresher_brotr.delete_service_state.call_args[1]
        assert call_kwargs["state_keys"] == ["old_removed_table"]


# ============================================================================
# Service — run (matviews)
# ============================================================================


class TestRefresherRunMatviews:
    async def test_refreshes_matviews(self, mock_refresher_brotr: Brotr) -> None:
        config = RefresherConfig(
            refresh=RefreshConfig(
                matviews=["relay_metadata_latest", "daily_counts"],
                summaries=["pubkey_kind_stats"],
            ),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        await refresher.run()

        assert mock_refresher_brotr.refresh_materialized_view.call_count == 2
        calls = [
            call[0][0] for call in mock_refresher_brotr.refresh_materialized_view.call_args_list
        ]
        assert calls == ["relay_metadata_latest", "daily_counts"]

    @pytest.mark.parametrize(
        "error",
        [
            asyncpg.PostgresError("db_error"),
            OSError("connection_reset"),
        ],
        ids=["postgres_error", "os_error"],
    )
    async def test_continues_on_matview_failure(
        self, mock_refresher_brotr: Brotr, error: Exception
    ) -> None:
        mock_refresher_brotr.refresh_materialized_view = AsyncMock(  # type: ignore[method-assign]
            side_effect=[None, error, None]
        )

        config = RefresherConfig(
            refresh=RefreshConfig(
                matviews=["relay_metadata_latest", "daily_counts", "supported_nip_counts"],
                summaries=["pubkey_kind_stats"],
            ),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        await refresher.run()

        assert mock_refresher_brotr.refresh_materialized_view.call_count == 3


# ============================================================================
# Service — run (summaries)
# ============================================================================


class TestRefresherRunSummaries:
    async def test_no_new_data_skips_refresh(self, mock_refresher_brotr: Brotr) -> None:
        # EXISTS returns False -> no new data
        mock_refresher_brotr.fetchval = AsyncMock(return_value=False)  # type: ignore[method-assign]

        config = RefresherConfig(
            refresh=RefreshConfig(
                matviews=["relay_metadata_latest"],
                summaries=["pubkey_kind_stats"],
            ),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        await refresher.run()

        # Should not call any summary refresh (no new data)
        fetchval_calls = mock_refresher_brotr.fetchval.call_args_list
        # Only get_max_seen_at EXISTS check is called, not the refresh function
        assert all("_refresh" not in str(c) for c in fetchval_calls)

    async def test_new_data_triggers_refresh(self, mock_refresher_brotr: Brotr) -> None:
        fetchval_side_effect: list[object] = []
        for i in range(len(DEFAULT_SUMMARIES)):
            fetchval_side_effect.extend([True, i + 1])
        mock_refresher_brotr.fetchval = AsyncMock(  # type: ignore[method-assign]
            side_effect=fetchval_side_effect
        )

        config = RefresherConfig(
            refresh=RefreshConfig(
                matviews=["relay_metadata_latest"],
                summaries=DEFAULT_SUMMARIES,
            ),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        await refresher.run()

        # Should upsert checkpoint for each summary
        assert mock_refresher_brotr.upsert_service_state.call_count == len(DEFAULT_SUMMARIES)

    async def test_summary_failure_continues(self, mock_refresher_brotr: Brotr) -> None:
        mock_refresher_brotr.fetchval = AsyncMock(  # type: ignore[method-assign]
            side_effect=[True, asyncpg.PostgresError("error"), True, 5]
        )

        config = RefresherConfig(
            refresh=RefreshConfig(
                matviews=["relay_metadata_latest"],
                summaries=["pubkey_relay_stats", "pubkey_kind_stats"],
            ),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        with patch.object(refresher._logger, "error") as mock_error:
            await refresher.run()

            error_calls = [
                c for c in mock_error.call_args_list if c[0][0] == "summary_refresh_failed"
            ]
            assert len(error_calls) == 1


# ============================================================================
# Service — run (completion counts)
# ============================================================================


class TestRefresherRunCounts:
    async def test_refresh_completed_counts(self, mock_refresher_brotr: Brotr) -> None:
        # 1 matview success, 1 summary with new data (EXISTS=True, row count=5)
        mock_refresher_brotr.fetchval = AsyncMock(side_effect=[True, 5])  # type: ignore[method-assign]

        config = RefresherConfig(
            refresh=RefreshConfig(
                matviews=["relay_metadata_latest"],
                summaries=["pubkey_kind_stats"],
            ),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        with patch.object(refresher._logger, "info") as mock_log:
            await refresher.run()

            cycle_calls = [c for c in mock_log.call_args_list if c[0][0] == "refresh_completed"]
            assert len(cycle_calls) == 1
            # 1 matview + 1 summary + 3 periodic = 5 refreshed
            assert cycle_calls[0][1]["refreshed"] == 5
            assert cycle_calls[0][1]["failed"] == 0

    async def test_all_fail(self, mock_refresher_brotr: Brotr) -> None:
        mock_refresher_brotr.refresh_materialized_view = AsyncMock(  # type: ignore[method-assign]
            side_effect=asyncpg.PostgresError("error")
        )
        mock_refresher_brotr.fetchval = AsyncMock(  # type: ignore[method-assign]
            side_effect=asyncpg.PostgresError("error")
        )
        mock_refresher_brotr.execute = AsyncMock(  # type: ignore[method-assign]
            side_effect=asyncpg.PostgresError("error")
        )

        config = RefresherConfig(
            refresh=RefreshConfig(
                matviews=["relay_metadata_latest"],
                summaries=["pubkey_kind_stats"],
            ),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        with patch.object(refresher._logger, "info") as mock_log:
            await refresher.run()

            cycle_calls = [c for c in mock_log.call_args_list if c[0][0] == "refresh_completed"]
            assert cycle_calls[0][1]["refreshed"] == 0
            # 1 matview + 1 summary + 3 periodic = 5 failed
            assert cycle_calls[0][1]["failed"] == 5


# ============================================================================
# Metrics
# ============================================================================


class TestRefresherMetrics:
    async def test_gauges_reset_at_start(self, mock_refresher_brotr: Brotr) -> None:
        config = RefresherConfig(
            refresh=RefreshConfig(
                matviews=["relay_metadata_latest"],
                summaries=["pubkey_kind_stats"],
            ),
        )
        refresher = Refresher(brotr=mock_refresher_brotr, config=config)

        with patch.object(refresher, "set_gauge") as mock_gauge:
            await refresher.run()

            first_three = mock_gauge.call_args_list[:3]
            # 1 matview + 1 summary + 3 periodic tasks = 5
            assert first_three[0] == (("views_total", 5),)
            assert first_three[1] == (("views_refreshed", 0),)
            assert first_three[2] == (("views_failed", 0),)
