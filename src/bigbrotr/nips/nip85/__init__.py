"""NIP-85 Trusted Assertion data models.

Provides assertion data models consumed by the event builders in
[bigbrotr.nips.event_builders][] and the
[Assertor][bigbrotr.services.assertor.Assertor] service.

See Also:
    [bigbrotr.nips.nip85.data][]: Data models for user and event assertions.
    [bigbrotr.nips.event_builders][]: Event builder functions for NIP-85 kinds.
"""

from .data import EventAssertion, UserAssertion


__all__ = ["EventAssertion", "UserAssertion"]
