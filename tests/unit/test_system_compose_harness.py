from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest

from tests.system.harness.compose import (
    ComposeServiceStatus,
    ComposeStack,
    build_test_env_values,
    parse_compose_ps,
    write_test_env_file,
)


class TestBuildTestEnvValues:
    def test_generates_required_keys_deterministically(self) -> None:
        first = build_test_env_values("bigbrotr", "bb-system-a")
        second = build_test_env_values("bigbrotr", "bb-system-a")

        assert first == second
        assert first["DB_ADMIN_PASSWORD"]
        assert len(first["NOSTR_PRIVATE_KEY_ASSERTOR"]) == 64
        assert len(first["GRAFANA_PASSWORD"]) == 24

    def test_overrides_are_applied(self) -> None:
        expected_password = "override-password"  # pragma: allowlist secret
        values = build_test_env_values(
            "lilbrotr",
            "lb-system-a",
            overrides={"GRAFANA_PASSWORD": expected_password},
        )

        assert values["GRAFANA_PASSWORD"] == expected_password

    def test_rejects_blank_required_override(self) -> None:
        with pytest.raises(ValueError, match="GRAFANA_PASSWORD"):
            build_test_env_values(
                "bigbrotr",
                "bb-system-a",
                overrides={"GRAFANA_PASSWORD": ""},
            )


class TestWriteTestEnvFile:
    def test_renders_required_values_into_template(self, tmp_path: Path) -> None:
        env_path = tmp_path / "runtime" / "bigbrotr.env"

        values = write_test_env_file("bigbrotr", "bb-system-a", env_path)
        rendered = env_path.read_text()

        assert f"DB_ADMIN_PASSWORD={values['DB_ADMIN_PASSWORD']}" in rendered
        assert f"GRAFANA_PASSWORD={values['GRAFANA_PASSWORD']}" in rendered
        assert rendered.endswith("\n")

    def test_appends_unknown_overrides(self, tmp_path: Path) -> None:
        env_path = tmp_path / "runtime" / "bigbrotr.env"

        write_test_env_file(
            "bigbrotr",
            "bb-system-a",
            env_path,
            overrides={"FINDER_METRICS_PORT": "18101"},
        )

        assert "FINDER_METRICS_PORT=18101\n" in env_path.read_text()


class TestParseComposePs:
    def test_accepts_json_array_output(self) -> None:
        statuses = parse_compose_ps(
            """
            [
              {"Service": "postgres", "State": "running", "Health": "healthy", "ExitCode": 0},
              {"Service": "grafana", "State": "running", "Health": ""}
            ]
            """
        )

        assert statuses == (
            ComposeServiceStatus(
                service="postgres",
                state="running",
                health="healthy",
                exit_code=0,
            ),
            ComposeServiceStatus(
                service="grafana",
                state="running",
                health=None,
                exit_code=None,
            ),
        )

    def test_accepts_json_lines_output(self) -> None:
        statuses = parse_compose_ps(
            """
            {"Service": "postgres", "State": "running", "Health": "healthy", "ExitCode": 0}
            {"Service": "prometheus", "State": "exited", "Health": "", "ExitCode": 1}
            """
        )

        assert statuses[0].is_ready is True
        assert statuses[1] == ComposeServiceStatus(
            service="prometheus",
            state="exited",
            health=None,
            exit_code=1,
        )


class TestComposeStack:
    def test_for_profile_writes_env_file_and_defaults_compose_file(self, tmp_path: Path) -> None:
        stack = ComposeStack.for_profile("bigbrotr", tmp_path, "bb-system-a")

        assert stack.env_file.exists()
        assert stack.compose_files == (Path("deployments/bigbrotr/docker-compose.yaml").resolve(),)

    def test_command_includes_project_env_and_files(self, tmp_path: Path) -> None:
        extra_compose = tmp_path / "overlay.yaml"
        extra_compose.write_text("services: {}\n")
        stack = ComposeStack.for_profile(
            "bigbrotr",
            tmp_path,
            "bb-system-a",
            compose_files=(
                Path("deployments/bigbrotr/docker-compose.yaml").resolve(),
                extra_compose,
            ),
        )

        assert stack.command("up", "-d") == (
            "docker",
            "compose",
            "--project-name",
            "bb-system-a",
            "--project-directory",
            str(Path("deployments/bigbrotr").resolve()),
            "--env-file",
            str(stack.env_file),
            "-f",
            str(Path("deployments/bigbrotr/docker-compose.yaml").resolve()),
            "-f",
            str(extra_compose),
            "up",
            "-d",
        )

    def test_run_uses_subprocess_with_text_capture(self, tmp_path: Path) -> None:
        stack = ComposeStack.for_profile("bigbrotr", tmp_path, "bb-system-a")

        with patch("tests.system.harness.compose.subprocess.run") as mock_run:
            stack.run("ps", "--format", "json")

        mock_run.assert_called_once_with(
            stack.command("ps", "--format", "json"),
            cwd=stack.project_dir,
            check=True,
            text=True,
            capture_output=True,
        )

    def test_up_can_force_rebuild(self, tmp_path: Path) -> None:
        stack = ComposeStack.for_profile("bigbrotr", tmp_path, "bb-system-a")

        with patch.object(
            ComposeStack,
            "run",
            return_value=CompletedProcess(args=(), returncode=0, stdout="", stderr=""),
        ) as mock_run:
            stack.up(build=True)

        mock_run.assert_called_once_with("up", "-d", "--build")

    def test_wait_until_ready_requires_service_names(self, tmp_path: Path) -> None:
        stack = ComposeStack.for_profile("bigbrotr", tmp_path, "bb-system-a")

        with pytest.raises(ValueError, match="at least one service"):
            stack.wait_until_ready(())

    def test_wait_until_ready_polls_until_requested_services_are_ready(
        self,
        tmp_path: Path,
    ) -> None:
        stack = ComposeStack.for_profile(
            "bigbrotr",
            tmp_path,
            "bb-system-a",
            poll_interval=0.01,
        )

        with (
            patch.object(
                ComposeStack,
                "ps",
                side_effect=[
                    (ComposeServiceStatus("postgres", "starting", "starting"),),
                    (ComposeServiceStatus("postgres", "running", "healthy"),),
                ],
            ) as mock_ps,
            patch("tests.system.harness.compose.time.sleep") as mock_sleep,
        ):
            statuses = stack.wait_until_ready(("postgres",), timeout=1.0)

        assert statuses == (ComposeServiceStatus("postgres", "running", "healthy"),)
        assert mock_ps.call_count == 2
        mock_sleep.assert_called_once_with(0.01)

    def test_wait_until_ready_times_out_with_last_snapshot(self, tmp_path: Path) -> None:
        stack = ComposeStack.for_profile(
            "bigbrotr",
            tmp_path,
            "bb-system-a",
            poll_interval=0.01,
        )

        monotonic = MagicMock(side_effect=[0.0, 0.4, 1.1])
        with (
            patch.object(
                ComposeStack,
                "ps",
                return_value=(
                    ComposeServiceStatus("postgres", "running", "starting"),
                    ComposeServiceStatus("grafana", "starting", None),
                ),
            ),
            patch("tests.system.harness.compose.time.monotonic", monotonic),
            patch("tests.system.harness.compose.time.sleep"),
            pytest.raises(RuntimeError, match="postgres=running/starting"),
        ):
            stack.wait_until_ready(("postgres", "grafana"), timeout=1.0)

    def test_ps_parses_subprocess_output(self, tmp_path: Path) -> None:
        stack = ComposeStack.for_profile("bigbrotr", tmp_path, "bb-system-a")

        with patch.object(
            ComposeStack,
            "run",
            return_value=CompletedProcess(
                args=(),
                returncode=0,
                stdout='[{"Service":"postgres","State":"running","Health":"healthy"}]',
                stderr="",
            ),
        ):
            statuses = stack.ps()

        assert statuses == (ComposeServiceStatus("postgres", "running", "healthy"),)

    def test_ps_can_include_one_shot_services(self, tmp_path: Path) -> None:
        stack = ComposeStack.for_profile("bigbrotr", tmp_path, "bb-system-a")

        with patch.object(
            ComposeStack,
            "run",
            return_value=CompletedProcess(
                args=(),
                returncode=0,
                stdout='[{"Service":"seeder","State":"exited","ExitCode":0}]',
                stderr="",
            ),
        ) as mock_run:
            statuses = stack.ps(all_services=True)

        mock_run.assert_called_once_with("ps", "--all", "--format", "json")
        assert statuses == (ComposeServiceStatus("seeder", "exited", None, 0),)
