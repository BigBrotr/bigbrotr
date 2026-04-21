from tests.integration.harness.doubles import (
    DEFAULT_OUTPUT_EVENT_ID,
    DEFAULT_PUBLISH_RELAY_URL,
    FakeBroadcastRecorder,
    FakePublishClient,
    build_publish_session,
)


class TestIntegrationProtocolDoubles:
    async def test_fake_publish_client_exposes_async_publish_methods(self) -> None:
        client = FakePublishClient()

        connect_result = await client.try_connect()

        assert connect_result.connected == (DEFAULT_PUBLISH_RELAY_URL,)
        assert connect_result.failed == {}
        await client.unsubscribe_all()
        client.unsubscribe_all.assert_awaited_once_with()

    def test_build_publish_session_uses_canonical_defaults(self) -> None:
        client = FakePublishClient()

        session = build_publish_session(client)

        assert session.session_id == "assertor-publish-relays"
        assert session.client is client
        assert session.relay_urls == (DEFAULT_PUBLISH_RELAY_URL,)
        assert session.connect_result.connected == (DEFAULT_PUBLISH_RELAY_URL,)

    async def test_broadcast_recorder_captures_builders_and_returns_protocol_result(self) -> None:
        recorder = FakeBroadcastRecorder()
        builders = ["builder-a", "builder-b"]
        clients = ["client-a"]

        results = await recorder(builders, clients)

        assert recorder.published_builders == builders
        assert recorder.calls[0].clients == clients
        assert results[0].event_ids == (DEFAULT_OUTPUT_EVENT_ID,)
        assert results[0].successful_relays == (DEFAULT_PUBLISH_RELAY_URL,)
