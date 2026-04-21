"""One-shot bootstrap of initial relay candidates or stored relays.

Exports the package-level bootstrap surface:

- [Seeder][bigbrotr.services.seeder.service.Seeder]: One-shot seed-file reader
  and relay insertion flow.
- [SeederConfig][bigbrotr.services.seeder.configs.SeederConfig] and
  [SeedConfig][bigbrotr.services.seeder.configs.SeedConfig]: configuration for
  seed-file location and candidate-vs-relay insertion mode.

This package stays intentionally minimal; long-running relay discovery belongs
to the finder service.
"""

from .configs import SeedConfig, SeederConfig
from .service import Seeder


__all__ = [
    "SeedConfig",
    "Seeder",
    "SeederConfig",
]
