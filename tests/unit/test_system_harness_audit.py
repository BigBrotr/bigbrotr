from __future__ import annotations

import json
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

from tests.system.harness import (
    ComposeStack,
    FaultControlPortPlan,
    GrafanaApi,
    PrometheusApi,
    RuntimeAddressPlan,
    ToxiproxyClient,
)
from tests.system.harness.compose import deployment_dir


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def read(self) -> bytes:
        if isinstance(self._payload, str):
            return self._payload.encode()
        return json.dumps(self._payload).encode()


class TestSystemHarnessAudit:
    def test_runtime_addressing_is_idempotent_and_does_not_mutate_base_compose(
        self, tmp_path: Path
    ) -> None:
        base_compose = (deployment_dir("bigbrotr") / "docker-compose.yaml").read_text()

        first = RuntimeAddressPlan.create("bigbrotr", tmp_path, "audit-run", slot=2)
        second = RuntimeAddressPlan.create("bigbrotr", tmp_path, "audit-run", slot=2)

        assert first.project_name == second.project_name
        assert first.ports == second.ports
        assert first.compose_file.read_text() == second.compose_file.read_text()
        assert (deployment_dir("bigbrotr") / "docker-compose.yaml").read_text() == base_compose

    def test_compose_stack_and_runtime_plan_stay_aligned_across_repeated_cycles(
        self,
        tmp_path: Path,
    ) -> None:
        commands: list[tuple[str, ...]] = []

        for cycle in range(3):
            plan = RuntimeAddressPlan.create("lilbrotr", tmp_path, "cycle-run", slot=cycle)
            stack = ComposeStack(
                profile=plan.profile,
                project_name=plan.project_name,
                project_dir=deployment_dir(plan.profile),
                env_file=plan.env_file,
                compose_files=(plan.compose_file,),
            )
            commands.append(stack.command("ps", "--format", "json"))

        assert commands[0][0:2] == ("docker", "compose")
        assert commands[0][2:4] == ("--project-name", commands[0][3])
        assert len({command[3] for command in commands}) == 3
        assert all(command[-2:] == ("--format", "json") for command in commands)

    def test_artifact_bundles_stay_isolated_across_repeated_runs(self, tmp_path: Path) -> None:
        first = RuntimeAddressPlan.create("bigbrotr", tmp_path, "artifact-audit", slot=0)
        second = RuntimeAddressPlan.create("bigbrotr", tmp_path, "artifact-audit", slot=1)

        assert first.runtime_root != second.runtime_root
        assert first.postgres_data_dir != second.postgres_data_dir
        assert first.monitoring_network_name != second.monitoring_network_name

    def test_fault_and_observability_clients_remain_stateless_across_repeated_calls(
        self,
        mocker,
    ) -> None:
        prometheus = PrometheusApi("http://prometheus:9090")
        grafana = GrafanaApi("http://grafana:3000")
        toxiproxy = ToxiproxyClient("http://toxiproxy:8474")
        mock_urlopen = mocker.patch(
            "urllib.request.urlopen",
            side_effect=[
                _FakeResponse({"status": "success"}),
                _FakeResponse({"database": "ok"}),
                _FakeResponse({"relay-a": {}}),
                _FakeResponse({"status": "success"}),
                _FakeResponse({"database": "ok"}),
                _FakeResponse({"relay-b": {}}),
                _FakeResponse({"status": "success"}),
                _FakeResponse({"database": "ok"}),
                _FakeResponse({"relay-c": {}}),
            ],
        )

        observed_queries: list[object] = []
        for cycle in range(3):
            observed_queries.append(prometheus.query(f'up{{job="cycle-{cycle}"}}'))
            assert grafana.health() == {"database": "ok"}
            assert toxiproxy.list_proxies() == {f"relay-{chr(ord('a') + cycle)}": {}}

        assert len(observed_queries) == 3
        assert mock_urlopen.call_count == 9

    def test_fault_control_port_plan_stays_unique_per_slot(self) -> None:
        ports = [FaultControlPortPlan.for_slot(slot) for slot in range(3)]

        assert [plan.admin for plan in ports] == [19500, 19520, 19540]
        assert len({plan.proxy_port(0) for plan in ports}) == 3
