"""Seeder-specific database queries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bigbrotr.services.common.utils import batched_insert


if TYPE_CHECKING:
    from bigbrotr.core.brotr import Brotr
    from bigbrotr.models import Relay


async def insert_relays(brotr: Brotr, relays: list[Relay]) -> int:
    """Bulk-insert relays directly into the ``relay`` table.

    Delegates to [batched_insert][bigbrotr.services.common.utils.batched_insert]
    to respect the configured batch size. Duplicates are silently skipped
    (``ON CONFLICT DO NOTHING``).

    Args:
        brotr: [Brotr][bigbrotr.core.brotr.Brotr] database interface.
        relays: [Relay][bigbrotr.models.relay.Relay] objects to insert.

    Returns:
        Number of relays actually inserted.
    """
    return await batched_insert(brotr, relays, brotr.insert_relay)
