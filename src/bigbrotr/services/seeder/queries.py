"""Seeder-specific database queries."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from bigbrotr.models import Relay

    from .service import Seeder


async def insert_relays(seeder: Seeder, relays: list[Relay]) -> int:
    """Bulk-insert relays directly into the ``relay`` table.

    Respects the configured batch size, splitting large inputs into
    multiple ``insert_relay`` calls. Duplicates are silently skipped
    (``ON CONFLICT DO NOTHING``).

    Args:
        seeder: The [Seeder][bigbrotr.services.seeder.Seeder] instance.
        relays: [Relay][bigbrotr.models.relay.Relay] objects to insert.

    Returns:
        Number of relays actually inserted.
    """
    if not relays:
        return 0
    total = 0
    batch_size = seeder._brotr.config.batch.max_size
    for i in range(0, len(relays), batch_size):
        total += await seeder._brotr.insert_relay(relays[i : i + batch_size])
    return total
