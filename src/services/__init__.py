"""
BigBrotr Services Package.

This package contains service implementations that build on the core layer:

- Initializer: Database bootstrap and schema verification
- Finder: Relay discovery from database events and external APIs
- Monitor: Relay health monitoring (pending)
- Synchronizer: Event synchronization (pending)
- PrioritySynchronizer: Priority-based sync (pending)
- API: REST API service (pending)
- DVM: Data Vending Machine (pending)

All services implement either DatabaseService or BackgroundService protocol
for compatibility with the Service wrapper (core.service.Service).
"""

from .finder import (
    FINDER_SERVICE_NAME,
    DiscoveryResult,
    Finder,
    FinderConfig,
    FinderState,
)
from .initializer import (
    INITIALIZER_SERVICE_NAME,
    InitializationResult,
    Initializer,
    InitializerConfig,
    InitializerState,
    VerificationResult,
)

__all__ = [
    "FINDER_SERVICE_NAME",
    "INITIALIZER_SERVICE_NAME",
    # Finder
    "DiscoveryResult",
    "Finder",
    "FinderConfig",
    "FinderState",
    # Initializer
    "InitializationResult",
    "Initializer",
    "InitializerConfig",
    "InitializerState",
    "VerificationResult",
]
