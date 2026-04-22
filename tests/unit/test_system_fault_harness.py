from __future__ import annotations

import io
import json
from subprocess import CompletedProcess
from typing import TYPE_CHECKING
from urllib import error

import pytest

from tests.system.harness import (
    DockerNetworkRuntime,
    FaultControlError,
    FaultControlPortPlan,
    LocalToxiproxyRuntime,
    ProxySpec,
    ToxicSpec,
    ToxiproxyClient,
    build_fault_container_name,
    build_fault_network_name,
    docker_network_exists,
)


if TYPE_CHECKING:
    from pathlib import Path


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def read(self) -> bytes:
        if isinstance(self._payload, bytes):
            return self._payload
        return json.dumps(self._payload).encode()


class TestFaultControlPortPlan:
    def test_port_plan_is_deterministic(self) -> None:
        plan = FaultControlPortPlan.for_slot(2)

        assert plan.admin == 19540
        assert plan.first_proxy == 19541
        assert plan.proxy_port(3) == 19544

    def test_negative_slot_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            FaultControlPortPlan.for_slot(-1)


class TestFaultRuntimeNames:
    def test_network_name_is_deterministic(self, tmp_path: Path) -> None:
        first = build_fault_network_name("relay-path", tmp_path / "runtime")
        second = build_fault_network_name("relay-path", tmp_path / "runtime")

        assert first == second
        assert first.startswith("bigbrotr-fault-net-relay-path-")

    def test_container_name_is_deterministic(self, tmp_path: Path) -> None:
        first = build_fault_container_name("relay-path", tmp_path / "runtime")
        second = build_fault_container_name("relay-path", tmp_path / "runtime")

        assert first == second
        assert first.startswith("bigbrotr-toxiproxy-relay-path-")


class TestDockerNetworkExists:
    def test_returns_true_when_inspect_succeeds(self, mocker: pytest.MockFixture) -> None:
        mocker.patch(
            "tests.system.harness.faults.subprocess.run",
            return_value=CompletedProcess(args=(), returncode=0, stdout="", stderr=""),
        )

        assert docker_network_exists("bb-fault-net") is True

    def test_returns_false_when_inspect_fails(self, mocker: pytest.MockFixture) -> None:
        mocker.patch(
            "tests.system.harness.faults.subprocess.run",
            return_value=CompletedProcess(args=(), returncode=1, stdout="", stderr="missing"),
        )

        assert docker_network_exists("bb-fault-net") is False


class TestProxySpec:
    def test_payload_shape(self) -> None:
        spec = ProxySpec(
            name="relay-main",
            upstream_host="relay",
            upstream_port=7447,
            listen_port=17500,
        )

        assert spec.to_payload() == {
            "name": "relay-main",
            "listen": "0.0.0.0:17500",
            "upstream": "relay:7447",
            "enabled": True,
        }


class TestToxicSpec:
    def test_payload_shape(self) -> None:
        toxic = ToxicSpec(
            name="latency",
            toxic_type="latency",
            attributes={"latency": 250, "jitter": 25},
            stream="upstream",
            toxicity=0.5,
        )

        assert toxic.to_payload() == {
            "name": "latency",
            "type": "latency",
            "stream": "upstream",
            "toxicity": 0.5,
            "attributes": {"latency": 250, "jitter": 25},
        }


class TestToxiproxyClient:
    def test_reset_state_posts_to_reset_endpoint(self, mocker: pytest.MockFixture) -> None:
        client = ToxiproxyClient("http://toxiproxy:8474")
        mock_urlopen = mocker.patch(
            "tests.system.harness.faults.request.urlopen",
            return_value=_FakeResponse({}),
        )

        client.reset_state()

        req = mock_urlopen.call_args.args[0]
        assert req.full_url == "http://toxiproxy:8474/reset"
        assert req.get_method() == "POST"

    def test_create_proxy_posts_payload(self, mocker: pytest.MockFixture) -> None:
        client = ToxiproxyClient("http://toxiproxy:8474")
        mock_urlopen = mocker.patch(
            "tests.system.harness.faults.request.urlopen",
            return_value=_FakeResponse({"name": "relay-main"}),
        )

        payload = client.create_proxy(
            ProxySpec(
                name="relay-main",
                upstream_host="relay",
                upstream_port=7447,
                listen_port=17500,
            )
        )

        req = mock_urlopen.call_args.args[0]
        assert req.full_url == "http://toxiproxy:8474/proxies"
        assert json.loads(req.data.decode())["listen"] == "0.0.0.0:17500"
        assert payload == {"name": "relay-main"}

    def test_set_proxy_enabled_posts_payload(self, mocker: pytest.MockFixture) -> None:
        client = ToxiproxyClient("http://toxiproxy:8474")
        mock_urlopen = mocker.patch(
            "tests.system.harness.faults.request.urlopen",
            return_value=_FakeResponse({"enabled": False}),
        )

        payload = client.set_proxy_enabled("relay-main", enabled=False)

        req = mock_urlopen.call_args.args[0]
        assert req.full_url == "http://toxiproxy:8474/proxies/relay-main"
        assert json.loads(req.data.decode()) == {"enabled": False}
        assert payload == {"enabled": False}

    def test_add_toxic_posts_payload(self, mocker: pytest.MockFixture) -> None:
        client = ToxiproxyClient("http://toxiproxy:8474")
        mock_urlopen = mocker.patch(
            "tests.system.harness.faults.request.urlopen",
            return_value=_FakeResponse({"name": "latency"}),
        )

        payload = client.add_toxic(
            "relay-main",
            ToxicSpec(
                name="latency",
                toxic_type="latency",
                attributes={"latency": 250},
            ),
        )

        req = mock_urlopen.call_args.args[0]
        assert req.full_url == "http://toxiproxy:8474/proxies/relay-main/toxics"
        assert json.loads(req.data.decode())["type"] == "latency"
        assert payload == {"name": "latency"}

    def test_list_proxies_requires_object_payload(self, mocker: pytest.MockFixture) -> None:
        client = ToxiproxyClient("http://toxiproxy:8474")
        mocker.patch(
            "tests.system.harness.faults.request.urlopen",
            return_value=_FakeResponse(["not-an-object"]),
        )

        with pytest.raises(
            RuntimeError,
            match="proxy listing returned a non-object payload",
        ):
            client.list_proxies()

    def test_http_errors_raise_fault_control_error(self, mocker: pytest.MockFixture) -> None:
        client = ToxiproxyClient("http://toxiproxy:8474")
        http_error = error.HTTPError(
            url="http://toxiproxy:8474/proxies",
            code=409,
            msg="conflict",
            hdrs=None,
            fp=io.BytesIO(b"already exists"),
        )
        mocker.patch(
            "tests.system.harness.faults.request.urlopen",
            side_effect=http_error,
        )

        with pytest.raises(RuntimeError, match="HTTP 409: already exists"):
            client.create_proxy(
                ProxySpec(
                    name="relay-main",
                    upstream_host="relay",
                    upstream_port=7447,
                    listen_port=17500,
                )
            )


class TestDockerNetworkRuntime:
    def test_start_and_stop_manage_network_lifecycle(
        self, tmp_path: Path, mocker: pytest.MockFixture
    ) -> None:
        runtime = DockerNetworkRuntime(role="fault-path", runtime_dir=tmp_path / "runtime")
        mock_run = mocker.patch(
            "tests.system.harness.faults.subprocess.run",
            side_effect=[
                CompletedProcess(args=(), returncode=0, stdout="network-id\n", stderr=""),
                CompletedProcess(args=(), returncode=0, stdout="", stderr=""),
            ],
        )

        runtime.start()
        runtime.stop()

        assert runtime.name.startswith("bigbrotr-fault-net-fault-path-")
        assert mock_run.call_args_list[0].args[0][:3] == ("docker", "network", "create")
        assert mock_run.call_args_list[1].args[0][:3] == ("docker", "network", "rm")


class TestLocalToxiproxyRuntime:
    def test_start_and_stop_manage_container_lifecycle(
        self,
        tmp_path: Path,
        mocker: pytest.MockFixture,
    ) -> None:
        runtime = LocalToxiproxyRuntime(
            role="fault-path",
            runtime_dir=tmp_path / "runtime",
            network_name="bb-fault-net",
            port_plan=FaultControlPortPlan.for_slot(0),
            exposed_proxy_ports=(19501,),
        )
        mocker.patch("tests.system.harness.faults.ensure_docker_available")
        mocker.patch("tests.system.harness.faults.ensure_testcontainers_environment")
        mocker.patch("tests.system.harness.faults._ensure_fault_image")
        mock_run = mocker.patch(
            "tests.system.harness.faults.subprocess.run",
            side_effect=[
                CompletedProcess(args=(), returncode=0, stdout="fault-cid\n", stderr=""),
                CompletedProcess(args=(), returncode=0, stdout="", stderr=""),
            ],
        )

        runtime.start()
        runtime.stop()

        assert runtime.admin_url == "http://127.0.0.1:19500"
        assert runtime.proxy_ws_url(19501) == "ws://127.0.0.1:19501"
        assert mock_run.call_args_list[0].args[0][:4] == ("docker", "run", "-d", "--name")
        assert mock_run.call_args_list[1].args[0][:3] == ("docker", "rm", "-f")

    def test_start_includes_network_aliases_when_requested(
        self,
        tmp_path: Path,
        mocker: pytest.MockFixture,
    ) -> None:
        runtime = LocalToxiproxyRuntime(
            role="fault-path",
            runtime_dir=tmp_path / "runtime",
            network_name="bb-fault-net",
            network_aliases=("proxy.monitor.test",),
            port_plan=FaultControlPortPlan.for_slot(0),
            exposed_proxy_ports=(19501,),
        )
        mocker.patch("tests.system.harness.faults.ensure_docker_available")
        mocker.patch("tests.system.harness.faults.ensure_testcontainers_environment")
        mocker.patch("tests.system.harness.faults._ensure_fault_image")
        mock_run = mocker.patch(
            "tests.system.harness.faults.subprocess.run",
            side_effect=[
                CompletedProcess(args=(), returncode=0, stdout="fault-cid\n", stderr=""),
                CompletedProcess(args=(), returncode=0, stdout="", stderr=""),
            ],
        )

        runtime.start()
        runtime.stop()

        command = mock_run.call_args_list[0].args[0]
        assert "--network-alias" in command
        assert "proxy.monitor.test" in command

    def test_wait_until_ready_uses_admin_client(
        self, tmp_path: Path, mocker: pytest.MockFixture
    ) -> None:
        runtime = LocalToxiproxyRuntime(
            role="fault-path",
            runtime_dir=tmp_path / "runtime",
            network_name="bb-fault-net",
            port_plan=FaultControlPortPlan.for_slot(0),
            exposed_proxy_ports=(19501,),
            ready_timeout=0.5,
            poll_interval=0.01,
        )
        mock_list = mocker.patch.object(
            ToxiproxyClient,
            "list_proxies",
            side_effect=[FaultControlError("not ready"), {}],
        )
        mock_sleep = mocker.patch("tests.system.harness.faults.time.sleep")

        runtime.wait_until_ready()

        assert mock_list.call_count == 2
        mock_sleep.assert_called_once_with(0.01)
