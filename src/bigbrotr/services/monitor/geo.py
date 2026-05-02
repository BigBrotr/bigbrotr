"""GeoIP database coordination for the monitor service."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from bigbrotr.core.logger import Logger

    from .configs import MonitorConfig


_SECONDS_PER_DAY = 86_400


async def update_geo_databases(
    *,
    config: MonitorConfig,
    logger: Logger,
    download: Callable[[str, Path, int], Awaitable[None]],
) -> None:
    """Download or refresh configured GeoLite2 databases when needed."""
    compute = config.processing.compute
    geo = config.geo
    max_age_days = geo.max_age_days

    updates: list[tuple[Path, str, str]] = []
    if compute.nip66_geo:
        updates.append((Path(geo.city_database_path), geo.city_download_url, "city"))
    if compute.nip66_net:
        updates.append((Path(geo.asn_database_path), geo.asn_download_url, "asn"))

    for path, url, name in updates:
        try:
            if await asyncio.to_thread(path.exists):
                if max_age_days is None:
                    continue
                age = time.time() - (await asyncio.to_thread(path.stat)).st_mtime
                if age <= max_age_days * _SECONDS_PER_DAY:
                    continue
                logger.info(
                    "updating_geo_db",
                    db=name,
                    age_days=round(age / _SECONDS_PER_DAY, 1),
                )
            else:
                logger.info("downloading_geo_db", db=name)
            await download(url, path, geo.max_download_size)
        except (OSError, ValueError) as e:
            logger.warning("geo_db_update_failed", db=name, error=str(e))
