"""Built-in read-model registry shared by the API and DVM services.

The current public surfaces are still catalog-backed and table-shaped.
This registry makes that surface explicit without yet changing the
runtime contract of ``Api`` and ``Dvm``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ReadSurface = Literal["api", "dvm"]


@dataclass(frozen=True, slots=True)
class ReadModelEntry:
    """One built-in read model exposed by one or more public surfaces."""

    catalog_name: str
    surfaces: tuple[ReadSurface, ...] = ("api", "dvm")


def _table_read_model(
    name: str,
    *,
    surfaces: tuple[ReadSurface, ...] = ("api", "dvm"),
) -> ReadModelEntry:
    """Build a compatibility read model backed by one catalog table/view."""
    return ReadModelEntry(catalog_name=name, surfaces=surfaces)


READ_MODEL_REGISTRY: dict[str, ReadModelEntry] = {
    "relay": _table_read_model("relay"),
    "event": _table_read_model("event"),
    "event_relay": _table_read_model("event_relay"),
    "metadata": _table_read_model("metadata"),
    "relay_metadata": _table_read_model("relay_metadata"),
    "relay_metadata_current": _table_read_model("relay_metadata_current"),
    "pubkey_stats": _table_read_model("pubkey_stats"),
    "kind_stats": _table_read_model("kind_stats"),
    "relay_stats": _table_read_model("relay_stats"),
    "pubkey_relay_stats": _table_read_model("pubkey_relay_stats"),
    "pubkey_kind_stats": _table_read_model("pubkey_kind_stats"),
    "relay_kind_stats": _table_read_model("relay_kind_stats"),
    "relay_software_counts": _table_read_model("relay_software_counts"),
    "supported_nip_counts": _table_read_model("supported_nip_counts"),
    "daily_counts": _table_read_model("daily_counts"),
    "events_replaceable_current": _table_read_model("events_replaceable_current"),
    "events_addressable_current": _table_read_model("events_addressable_current"),
    "nip85_pubkey_stats": _table_read_model("nip85_pubkey_stats"),
    "nip85_event_stats": _table_read_model("nip85_event_stats"),
    "nip85_addressable_stats": _table_read_model("nip85_addressable_stats"),
    "nip85_identifier_stats": _table_read_model("nip85_identifier_stats"),
}


def read_models_for_surface(surface: ReadSurface) -> dict[str, ReadModelEntry]:
    """Return the built-in read models exposed by one public surface."""
    return {
        read_model_id: entry
        for read_model_id, entry in READ_MODEL_REGISTRY.items()
        if surface in entry.surfaces
    }
