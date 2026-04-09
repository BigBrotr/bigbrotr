"""NIP-85 Trusted Assertion data models.

Provides trusted-provider declaration and assertion data models consumed by the
event builders in
[bigbrotr.nips.event_builders][] and the
[Assertor][bigbrotr.services.assertor.Assertor] service.

See Also:
    [bigbrotr.nips.nip85.data][]: Data models for provider declarations and
        assertion subjects.
    [bigbrotr.nips.event_builders][]: Event builder functions for NIP-85 kinds.
"""

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
]
