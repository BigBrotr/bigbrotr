from unittest.mock import MagicMock, patch

import pytest
from docker.errors import DockerException

from tests.integration.conftest import _DOCKER_REQUIRED_MESSAGE, _ensure_docker_available


class TestEnsureDockerAvailable:
    def test_pings_docker_and_closes_client(self) -> None:
        client = MagicMock()

        with patch(
            "tests.integration.conftest.docker.from_env", return_value=client
        ) as mock_from_env:
            _ensure_docker_available()

        mock_from_env.assert_called_once_with()
        client.ping.assert_called_once_with()
        client.close.assert_called_once_with()

    def test_fails_with_clear_message_when_ping_fails(self) -> None:
        client = MagicMock()
        client.ping.side_effect = DockerException("daemon unavailable")

        with (
            patch("tests.integration.conftest.docker.from_env", return_value=client),
            pytest.raises(pytest.fail.Exception) as excinfo,
        ):
            _ensure_docker_available()

        assert _DOCKER_REQUIRED_MESSAGE in str(excinfo.value)
        assert "daemon unavailable" in str(excinfo.value)
        client.close.assert_called_once_with()

    def test_fails_with_clear_message_when_client_creation_fails(self) -> None:
        with (
            patch(
                "tests.integration.conftest.docker.from_env",
                side_effect=OSError("docker socket missing"),
            ),
            pytest.raises(pytest.fail.Exception) as excinfo,
        ):
            _ensure_docker_available()

        assert _DOCKER_REQUIRED_MESSAGE in str(excinfo.value)
        assert "docker socket missing" in str(excinfo.value)
