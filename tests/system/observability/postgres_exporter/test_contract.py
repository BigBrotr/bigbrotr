from pathlib import Path

import pytest

from tests.system.observability.postgres_exporter.common import certify_postgres_exporter_contract


pytestmark = pytest.mark.system


@pytest.mark.parametrize(
    ("profile", "run_name", "slot"),
    [
        ("bigbrotr", "bigbrotr-postgres-exporter-contract", 73),
        ("lilbrotr", "lilbrotr-postgres-exporter-contract", 74),
    ],
)
def test_postgres_exporter_contract(
    tmp_path: Path,
    profile: str,
    run_name: str,
    slot: int,
) -> None:
    certify_postgres_exporter_contract(
        tmp_path,
        profile=profile,
        run_name=run_name,
        slot=slot,
    )
