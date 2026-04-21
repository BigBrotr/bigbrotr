from __future__ import annotations

import io
import json
from urllib import error

import pytest

from tests.system.harness import FaultControlPortPlan, ProxySpec, ToxicSpec, ToxiproxyClient


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
