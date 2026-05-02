from pathlib import Path

import pytest

from tests.system.observability.alerts.common import certify_service_down_alert_contract


pytestmark = pytest.mark.system


def test_lilbrotr_service_down_alert_contract(tmp_path: Path) -> None:
    certify_service_down_alert_contract(
        tmp_path,
        profile="lilbrotr",
        run_name="lilbrotr-alert-rule-contract",
        slot=64,
        stopped_service="validator",
    )
