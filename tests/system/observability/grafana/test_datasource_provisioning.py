from pathlib import Path

import pytest

from tests.system.observability.grafana.common import certify_grafana_datasource_contract


pytestmark = pytest.mark.system


@pytest.mark.parametrize(
    ("profile", "run_name", "slot"),
    [
        ("bigbrotr", "bigbrotr-grafana-datasource-contract", 65),
        ("lilbrotr", "lilbrotr-grafana-datasource-contract", 66),
    ],
)
def test_grafana_datasource_provisioning_contract(
    tmp_path: Path,
    profile: str,
    run_name: str,
    slot: int,
) -> None:
    certify_grafana_datasource_contract(
        tmp_path,
        profile=profile,
        run_name=run_name,
        slot=slot,
    )
