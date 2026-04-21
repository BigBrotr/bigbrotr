"""Named doubles for integration test external boundaries."""

from tests.integration.harness.doubles.protocol import (
    DEFAULT_OUTPUT_EVENT_ID,
    DEFAULT_PUBLISH_RELAY_URL,
    FakeBroadcastRecorder,
    FakePublishClient,
    build_publish_session,
)


__all__ = [
    "DEFAULT_OUTPUT_EVENT_ID",
    "DEFAULT_PUBLISH_RELAY_URL",
    "FakeBroadcastRecorder",
    "FakePublishClient",
    "build_publish_session",
]
