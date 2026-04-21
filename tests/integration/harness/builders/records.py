"""Canonical domain-record builders for integration tests."""

from __future__ import annotations

from typing import Any

from bigbrotr.models import EventObservation, Relay, RelayDocument
from bigbrotr.models.constants import ServiceName
from bigbrotr.models.document import Document, DocumentType
from bigbrotr.models.event import Event
from bigbrotr.models.service_state import ServiceState, ServiceStateType
from tests.conftest import make_mock_event


DEFAULT_STORED_AT = 1_700_000_000
DEFAULT_OBSERVED_AT = 1_700_000_001
DEFAULT_ASSOCIATED_AT = 1_700_000_001
DEFAULT_SIG = "ee" * 64


def build_relay(relay_url: str, *, stored_at: int = DEFAULT_STORED_AT) -> Relay:
    """Build a relay with the canonical integration-test timestamp defaults."""
    return Relay(relay_url, stored_at=stored_at)


def build_event(
    event_id: str,
    *,
    pubkey: str = "bb" * 32,
    kind: int = 1,
    created_at: int = DEFAULT_STORED_AT,
    tags: list[list[str]] | None = None,
    content: str = "",
    sig: str = DEFAULT_SIG,
) -> Event:
    """Build an event from the canonical integration mock-event seam."""
    return Event(
        make_mock_event(
            event_id=event_id,
            pubkey=pubkey,
            kind=kind,
            created_at=created_at,
            tags=tags,
            content=content,
            sig=sig,
        )
    )


def build_event_observation(
    event_id: str,
    relay_url: str,
    *,
    kind: int = 1,
    pubkey: str = "bb" * 32,
    created_at: int = DEFAULT_STORED_AT,
    observed_at: int | None = None,
    tags: list[list[str]] | None = None,
    content: str = "",
    sig: str = DEFAULT_SIG,
    stored_at: int = DEFAULT_STORED_AT,
) -> EventObservation:
    """Build an event observation against a canonical relay and event."""
    return EventObservation(
        event=build_event(
            event_id,
            pubkey=pubkey,
            kind=kind,
            created_at=created_at,
            tags=tags,
            content=content,
            sig=sig,
        ),
        relay=build_relay(relay_url, stored_at=stored_at),
        observed_at=observed_at or created_at + 1,
    )


def build_document(
    *,
    document_type: DocumentType = DocumentType.NIP11_INFO,
    data: dict[str, Any],
    wrap_probe_logs: bool = False,
) -> Document:
    """Build a document, optionally wrapping probe output in the persisted envelope."""
    payload: dict[str, Any] = {"data": data, "logs": {"success": True}} if wrap_probe_logs else data

    return Document(type=document_type, data=payload)


def build_relay_document(
    relay_url: str,
    data: dict[str, Any],
    document_type: DocumentType = DocumentType.NIP11_INFO,
    *,
    associated_at: int = DEFAULT_ASSOCIATED_AT,
    stored_at: int = DEFAULT_STORED_AT,
    wrap_probe_logs: bool = False,
) -> RelayDocument:
    """Build a relay-document association with canonical integration defaults."""
    return RelayDocument(
        relay=build_relay(relay_url, stored_at=stored_at),
        document=build_document(
            document_type=document_type,
            data=data,
            wrap_probe_logs=wrap_probe_logs,
        ),
        associated_at=associated_at,
    )


def build_nip11_relay_document(
    relay_url: str,
    data: dict[str, Any],
    *,
    associated_at: int = DEFAULT_ASSOCIATED_AT,
    stored_at: int = DEFAULT_STORED_AT,
) -> RelayDocument:
    """Build a persisted NIP-11 relay document with the standard envelope."""
    return build_relay_document(
        relay_url,
        data,
        document_type=DocumentType.NIP11_INFO,
        associated_at=associated_at,
        stored_at=stored_at,
        wrap_probe_logs=True,
    )


def build_nip66_relay_document(
    relay_url: str,
    document_type: DocumentType,
    data: dict[str, Any],
    *,
    associated_at: int = DEFAULT_ASSOCIATED_AT,
    stored_at: int = DEFAULT_STORED_AT,
) -> RelayDocument:
    """Build a persisted NIP-66 relay document with the standard envelope."""
    return build_relay_document(
        relay_url,
        data,
        document_type=document_type,
        associated_at=associated_at,
        stored_at=stored_at,
        wrap_probe_logs=True,
    )


def build_service_state(
    *,
    owner: ServiceName = ServiceName.FINDER,
    state_type: ServiceStateType = ServiceStateType.CURSOR,
    state_key: str,
    state_value: dict[str, Any],
) -> ServiceState:
    """Build a service-state row with explicit owner/type/key/value fields."""
    return ServiceState(
        owner=owner,
        state_type=state_type,
        state_key=state_key,
        state_value=state_value,
    )


def build_event_address(kind: int, pubkey: str, d_value: str) -> str:
    """Build the canonical shared event-address string."""
    return f"{kind}:{pubkey.lower()}:{d_value}"
