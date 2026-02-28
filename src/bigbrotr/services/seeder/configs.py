"""Seeder service configuration models.

See Also:
    [Seeder][bigbrotr.services.seeder.Seeder]: The service class
        that consumes these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval``, ``max_consecutive_failures``,
        and ``metrics`` fields.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from bigbrotr.core.base_service import BaseServiceConfig


class SeedConfig(BaseModel):
    """Configuration for seed data source and insertion mode.

    See Also:
        [SeederConfig][bigbrotr.services.seeder.SeederConfig]: Parent
            config that embeds this model.
    """

    file_path: str = Field(default="static/seed_relays.txt", description="Seed file path")
    to_validate: bool = Field(
        default=True,
        description="If True, add as candidates. If False, insert directly into relays.",
    )


class SeederConfig(BaseServiceConfig):
    """Seeder service configuration.

    See Also:
        [Seeder][bigbrotr.services.seeder.Seeder]: The service class
            that consumes this configuration.
        [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
            Base class providing ``interval`` and ``metrics`` fields.
    """

    seed: SeedConfig = Field(default_factory=SeedConfig)
