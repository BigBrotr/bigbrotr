from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import AsyncMock, patch

import pytest

from tests.system.harness import (
    LocalRelayRuntime,
    RelayEoseFrame,
    RelayEventFrame,
    RelayOkFrame,
    build_relay_container_name,
    build_text_note_event,
    parse_relay_frame,
)


class TestBuildRelayContainerName:
    def test_is_deterministic_for_role_and_runtime_dir(self, tmp_path: Path) -> None:
        first = build_relay_container_name("baseline relay", tmp_path / "runtime")
        second = build_relay_container_name("baseline relay", tmp_path / "runtime")

        assert first == second
        assert first.startswith("bigbrotr-relay-baseline-relay-")
        assert len(first) <= 63


class TestBuildTextNoteEvent:
    def test_returns_signed_event_payload(self) -> None:
        signed = build_text_note_event("relay-harness")

        assert signed.payload["id"] == signed.event_id
        assert signed.payload["pubkey"] == signed.pubkey
        assert signed.payload["content"] == "relay-harness"
        assert signed.payload["kind"] == 1


class TestParseRelayFrame:
    def test_parses_ok_frame(self) -> None:
        assert parse_relay_frame(["OK", "abc", True, ""]) == RelayOkFrame(
            event_id="abc",
            accepted=True,
            message="",
        )

    def test_parses_event_frame(self) -> None:
        assert parse_relay_frame(["EVENT", "sub-1", {"id": "abc"}]) == RelayEventFrame(
            subscription_id="sub-1",
            event={"id": "abc"},
        )

    def test_parses_eose_frame(self) -> None:
        assert parse_relay_frame(["EOSE", "sub-1"]) == RelayEoseFrame(subscription_id="sub-1")

    def test_rejects_unsupported_frame_types(self) -> None:
        with pytest.raises(ValueError, match="Unsupported relay frame type"):
            parse_relay_frame(["NOTICE", "not-supported-here"])


class TestLocalRelayRuntime:
    def test_start_and_stop_manage_container_lifecycle(self, tmp_path: Path) -> None:
        runtime = LocalRelayRuntime(role="baseline", runtime_dir=tmp_path / "relay")

        with (
            patch("tests.system.harness.relay.ensure_docker_available"),
            patch("tests.system.harness.relay.ensure_testcontainers_environment"),
            patch("tests.system.harness.relay._ensure_relay_image"),
            patch(
                "tests.system.harness.relay.subprocess.run",
                side_effect=[
                    CompletedProcess(args=(), returncode=0, stdout="relay-cid\n", stderr=""),
                    CompletedProcess(
                        args=(),
                        returncode=0,
                        stdout=(
                            '[{"NetworkSettings":{"Ports":{"8080/tcp":'
                            '[{"HostIp":"127.0.0.1","HostPort":"53887"}]}}}]'
                        ),
                        stderr="",
                    ),
                    CompletedProcess(args=(), returncode=0, stdout="", stderr=""),
                ],
            ) as mock_run,
        ):
            runtime.start()

            assert runtime.container_id == "relay-cid"
            assert runtime.ws_url == "ws://127.0.0.1:53887"
            assert runtime.data_dir.is_dir()

            runtime.stop()

        assert mock_run.call_args_list[0].args[0][:4] == (
            "docker",
            "run",
            "-d",
            "--platform",
        )
        assert mock_run.call_args_list[1].args[0][:2] == ("docker", "inspect")
        assert mock_run.call_args_list[2].args[0][:3] == ("docker", "rm", "-f")

    async def test_wait_until_ready_uses_runtime_ws_url(self, tmp_path: Path) -> None:
        runtime = LocalRelayRuntime(role="baseline", runtime_dir=tmp_path / "relay")
        runtime.host_port = 18080

        with patch(
            "tests.system.harness.relay.wait_until_relay_ready",
            new=AsyncMock(),
        ) as mock_ready:
            await runtime.wait_until_ready()

        mock_ready.assert_awaited_once_with(
            "ws://127.0.0.1:18080",
            timeout=runtime.ready_timeout,
            poll_interval=runtime.poll_interval,
        )
