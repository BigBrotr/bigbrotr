from pathlib import Path

import pytest

from tests.system.observability.alertmanager.common import certify_alertmanager_routing_contract


pytestmark = pytest.mark.system


@pytest.mark.parametrize(
    ("profile", "run_name", "slot"),
    [
        ("bigbrotr", "bigbrotr-alertmanager-routing-contract", 67),
        ("lilbrotr", "lilbrotr-alertmanager-routing-contract", 68),
    ],
)
def test_alertmanager_routing_contract(
    tmp_path: Path,
    profile: str,
    run_name: str,
    slot: int,
) -> None:
    certify_alertmanager_routing_contract(
        tmp_path,
        profile=profile,
        run_name=run_name,
        slot=slot,
    )
