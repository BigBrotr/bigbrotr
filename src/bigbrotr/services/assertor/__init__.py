"""NIP-85 provider-package publisher.

Exports the package-level publication surface:

- [Assertor][bigbrotr.services.assertor.service.Assertor]: Cycle runner for
  trusted assertions, optional provider profile publication, and optional
  trusted-provider list publication.
- [AssertorConfig][bigbrotr.services.assertor.configs.AssertorConfig] plus the
  provider-profile and trusted-provider-list config models: publication-policy
  surface for the algorithm-scoped service key.
- [PublishCycleResult][bigbrotr.services.assertor.service.PublishCycleResult]
  and [PublishKindResult][bigbrotr.services.assertor.service.PublishKindResult]:
  typed runtime results for one publication cycle.

This package owns the published provider package and consumes shared facts plus
public score outputs rather than private ranker state.
"""

from .configs import (
    AssertorCleanupConfig,
    AssertorConfig,
    AssertorPublishingConfig,
    AssertorSelectionConfig,
    ProviderProfileConfig,
    ProviderProfileKind0Content,
    TrustedProviderListConfig,
)
from .service import Assertor, PublishCycleResult, PublishKindResult


__all__ = [
    "Assertor",
    "AssertorCleanupConfig",
    "AssertorConfig",
    "AssertorPublishingConfig",
    "AssertorSelectionConfig",
    "ProviderProfileConfig",
    "ProviderProfileKind0Content",
    "PublishCycleResult",
    "PublishKindResult",
    "TrustedProviderListConfig",
]
