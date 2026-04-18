"""NIP-85 public-score and provider-package surface.

Provides the trusted-provider declaration and assertion data models consumed
by the [Ranker][bigbrotr.services.ranker.Ranker] and
[Assertor][bigbrotr.services.assertor.Assertor] services, together with the
NIP-85 event builders used to publish the provider package.

See Also:
    [bigbrotr.nips.nip85.data][]: Data models for provider declarations and
        assertion subjects.
    [bigbrotr.nips.event_builders][]: Shared builder implementations for NIP-aware
        event construction.
"""

from bigbrotr.nips.event_builders import (
    build_addressable_assertion,
    build_event_assertion,
    build_identifier_assertion,
    build_trusted_provider_list,
    build_user_assertion,
)
from bigbrotr.nips.event_builders import (
    build_profile_event as build_provider_profile,
)

from .data import (
    AddressableAssertion,
    EventAssertion,
    IdentifierAssertion,
    TrustedProviderDeclaration,
    UserAssertion,
)


__all__ = [
    "AddressableAssertion",
    "EventAssertion",
    "IdentifierAssertion",
    "TrustedProviderDeclaration",
    "UserAssertion",
    "build_addressable_assertion",
    "build_event_assertion",
    "build_identifier_assertion",
    "build_provider_profile",
    "build_trusted_provider_list",
    "build_user_assertion",
]
