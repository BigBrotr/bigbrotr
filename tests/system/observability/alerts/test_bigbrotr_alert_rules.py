from pathlib import Path

import pytest

from tests.system.observability.alerts.common import certify_service_down_alert_contract


pytestmark = pytest.mark.system


def test_bigbrotr_service_down_alert_contract(tmp_path: Path) -> None:
    certify_service_down_alert_contract(
        tmp_path,
        profile="bigbrotr",
        run_name="bigbrotr-alert-rule-contract",
        slot=63,
        stopped_service="validator",
    )
