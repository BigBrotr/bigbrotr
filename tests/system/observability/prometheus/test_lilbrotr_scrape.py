from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .common import certify_prometheus_scrape_contract


if TYPE_CHECKING:
    from pathlib import Path


pytestmark = pytest.mark.system


@pytest.mark.timeout(1200)
def test_lilbrotr_prometheus_scrapes_all_expected_targets_with_required_series(
    tmp_path: Path,
) -> None:
    certify_prometheus_scrape_contract(
        tmp_path,
        profile="lilbrotr",
        run_name="lilbrotr-prometheus-scrape-contract",
        slot=62,
    )
