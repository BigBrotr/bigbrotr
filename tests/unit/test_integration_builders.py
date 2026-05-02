from bigbrotr.models.constants import ServiceName
from bigbrotr.models.document import DocumentType
from bigbrotr.models.service_state import ServiceStateType
from tests.integration.harness.builders import (
    build_document,
    build_event_address,
    build_event_observation,
    build_nip11_relay_document,
    build_nip66_relay_document,
    build_service_state,
)


class TestIntegrationBuilders:
    def test_event_observation_defaults_observed_at_after_event_time(self) -> None:
        observation = build_event_observation(
            "aa" * 32, "wss://builder.example.com", created_at=100
        )

        assert observation.relay.url == "wss://builder.example.com"
        assert observation.relay.stored_at == 1_700_000_000
        assert observation.observed_at == 101

    def test_document_builder_can_wrap_probe_logs(self) -> None:
        document = build_document(
            document_type=DocumentType.NIP11_INFO,
            data={"name": "Relay"},
            wrap_probe_logs=True,
        )

        assert document.type == DocumentType.NIP11_INFO
        assert document.data == {"data": {"name": "Relay"}, "logs": {"success": True}}

    def test_nip_specific_relay_document_builders_use_envelope(self) -> None:
        nip11 = build_nip11_relay_document("wss://builder.example.com", {"name": "Relay"})
        nip66 = build_nip66_relay_document(
            "wss://builder.example.com",
            DocumentType.NIP66_SSL,
            {"issuer": "CA"},
        )

        assert nip11.document.data["logs"]["success"] is True
        assert nip11.document.type == DocumentType.NIP11_INFO
        assert nip66.document.data["data"]["issuer"] == "CA"
        assert nip66.document.type == DocumentType.NIP66_SSL

    def test_service_state_builder_preserves_explicit_contract_fields(self) -> None:
        state = build_service_state(
            owner=ServiceName.SYNCHRONIZER,
            state_type=ServiceStateType.CHECKPOINT,
            state_key="cursor",
            state_value={"ts": 1},
        )

        assert state.owner == ServiceName.SYNCHRONIZER
        assert state.state_type == ServiceStateType.CHECKPOINT
        assert state.state_key == "cursor"
        assert state.state_value == {"ts": 1}

    def test_event_address_builder_normalizes_pubkey_case(self) -> None:
        assert build_event_address(30023, "AA" * 32, "topic") == f"30023:{'aa' * 32}:topic"
