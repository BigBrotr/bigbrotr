"""Refresher service for BigBrotr.

Periodically refreshes materialized views in dependency order. Each view
is refreshed individually via
[Brotr.refresh_materialized_view()][bigbrotr.core.brotr.Brotr.refresh_materialized_view],
providing per-view logging, timing, and error isolation.

The default view list and ordering is defined in
[DEFAULT_VIEWS][bigbrotr.services.refresher.configs.DEFAULT_VIEWS] and
respects the 3-level dependency chain:

1. ``relay_metadata_latest`` (base dependency for software/NIP views)
2. Independent statistics views (``event_stats``, ``relay_stats``, etc.)
3. Views depending on ``relay_metadata_latest`` (``relay_software_counts``,
   ``supported_nip_counts``)

See Also:
    [RefresherConfig][bigbrotr.services.refresher.RefresherConfig]:
        Configuration model for view list and scheduling.
    [BaseService][bigbrotr.core.base_service.BaseService]: Abstract base
        class providing ``run()`` and ``run_forever()`` lifecycle.
    [Brotr.refresh_materialized_view()][bigbrotr.core.brotr.Brotr.refresh_materialized_view]:
        Database method that calls the underlying refresh stored procedure.

Examples:
    ```python
    from bigbrotr.core import Brotr
    from bigbrotr.services import Refresher

    brotr = Brotr.from_yaml("config/brotr.yaml")
    refresher = Refresher.from_yaml("config/services/refresher.yaml", brotr=brotr)

    async with brotr:
        async with refresher:
            await refresher.run_forever()
    ```
"""

from __future__ import annotations

import time
from typing import ClassVar

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName

from .configs import RefresherConfig


class Refresher(BaseService[RefresherConfig]):
    """Materialized view refresh service.

    Iterates over the configured view list and refreshes each view
    individually. Failures on one view do not prevent subsequent views
    from being refreshed.

    See Also:
        [RefresherConfig][bigbrotr.services.refresher.RefresherConfig]:
            Configuration model for this service.
    """

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.REFRESHER
    CONFIG_CLASS: ClassVar[type[RefresherConfig]] = RefresherConfig

    async def run(self) -> None:
        """Execute one refresh cycle over all configured views."""
        views = self._config.refresh.views
        self._logger.info("cycle_started", views=len(views))

        refreshed = 0
        failed = 0

        for view in views:
            try:
                start = time.monotonic()
                await self._brotr.refresh_materialized_view(view)
                elapsed = round(time.monotonic() - start, 2)
                refreshed += 1
                self._logger.info("view_refreshed", view=view, duration=elapsed)
            except Exception as exc:
                failed += 1
                self._logger.error("view_refresh_failed", view=view, error=str(exc))

        self.set_gauge("views_refreshed", refreshed)
        self.set_gauge("views_failed", failed)
        self._logger.info("cycle_completed", refreshed=refreshed, failed=failed)
