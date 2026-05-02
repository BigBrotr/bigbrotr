from pathlib import Path
from urllib import error, request

import pytest

from tests.system.harness.http import LocalHttpFixtureRuntime


class TestLocalHttpFixtureRuntime:
    def test_serves_json_and_records_requests(self, tmp_path: Path) -> None:
        runtime = LocalHttpFixtureRuntime(runtime_dir=tmp_path / "fixture")
        runtime.set_json_response("/sources.json", ["wss://relay.example.com"])

        with runtime, request.urlopen(f"{runtime.base_url}/sources.json", timeout=1.0) as response:  # noqa: S310
            body = response.read().decode()

        assert body == '["wss://relay.example.com"]'
        assert runtime.requests(path="/sources.json")[0].method == "GET"
        assert runtime.requests_log_path.is_file()

    def test_routes_can_be_replaced_between_requests(self, tmp_path: Path) -> None:
        runtime = LocalHttpFixtureRuntime(runtime_dir=tmp_path / "fixture")
        runtime.set_text_response("/payload.txt", "first")

        with runtime:
            with request.urlopen(f"{runtime.base_url}/payload.txt", timeout=1.0) as response:  # noqa: S310
                first = response.read().decode()
            runtime.set_text_response("/payload.txt", "second")
            with request.urlopen(f"{runtime.base_url}/payload.txt", timeout=1.0) as response:  # noqa: S310
                second = response.read().decode()

        assert first == "first"
        assert second == "second"
        assert len(runtime.requests(path="/payload.txt")) == 2

    def test_missing_route_returns_not_found(self, tmp_path: Path) -> None:
        runtime = LocalHttpFixtureRuntime(runtime_dir=tmp_path / "fixture")

        with runtime, pytest.raises(error.HTTPError, match="HTTP Error 404"):
            request.urlopen(f"{runtime.base_url}/missing.json", timeout=1.0)  # noqa: S310

    def test_requires_positive_timeout(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="timeout must be positive"):
            LocalHttpFixtureRuntime(runtime_dir=tmp_path / "fixture", timeout=0)
