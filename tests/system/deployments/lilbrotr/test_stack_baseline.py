from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.system.deployments.baseline import (
    ALL_SERVICES,
    CONTINUOUS_SERVICES,
    assert_expected_baseline,
    capture_stack_artifacts,
    create_bundle,
    create_stack,
    record_runtime_plan,
)
from tests.system.deployments.runtime_overrides import (
    BOOTSTRAP_SERVICES,
    configure_runtime_relay_targets,
    prepare_runtime_compose_config,
    start_baseline_relay,
)
from tests.system.harness import RuntimeAddressPlan


if TYPE_CHECKING:
    from pathlib import Path


pytestmark = pytest.mark.system


@pytest.mark.timeout(900)
def test_lilbrotr_stack_reaches_expected_baseline(tmp_path: Path) -> None:
    bundle = create_bundle(tmp_path, "lilbrotr-stack-baseline")
    plan = RuntimeAddressPlan.create("lilbrotr", tmp_path / "runtime", "lilbrotr-stack-baseline")
    prepare_runtime_compose_config(plan)
    stack = create_stack(plan)
    record_runtime_plan(bundle, plan)

    relay = None
    try:
        stack.up(*BOOTSTRAP_SERVICES, build=True)
        relay = start_baseline_relay(plan)
        configure_runtime_relay_targets(plan, relay)
        stack.up(build=True)
        ready = stack.wait_until_ready(CONTINUOUS_SERVICES)
        snapshot = {status.service: status for status in stack.ps(all_services=True)}
        capture_stack_artifacts(bundle, stack, services=ALL_SERVICES)
    finally:
        if relay is not None:
            relay.stop()
        stack.down()

    assert_expected_baseline(bundle, ready, snapshot)
