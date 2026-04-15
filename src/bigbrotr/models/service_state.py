"""Service state types for database persistence.

Pure data containers representing rows in the ``service_state`` table.
These live in the models layer because they have zero I/O, zero
package dependencies, and are used by both ``bigbrotr.core.brotr`` and
``bigbrotr.services``.

All validation happens in ``__post_init__`` so invalid instances never
escape the constructor. Database parameter containers use ``NamedTuple``
and are cached in ``__post_init__`` to avoid repeated conversions.

See Also:
    [bigbrotr.core.brotr][]: The database facade that consumes
        [ServiceState][bigbrotr.models.service_state.ServiceState] via
        ``upsert_service_state()``, ``get_service_state()``, and
        ``delete_service_state()`` methods.
    [bigbrotr.services][]: Services that persist and restore
        processing cursors using these types.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, NamedTuple

from ._validation import (
    deep_freeze,
    normalize_json_data,
    validate_mapping,
    validate_str_not_empty,
)


if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)


class ServiceStateType(StrEnum):
    """Service state type identifiers for the ``service_state`` table.

    Used as the ``state_type`` discriminator in
    [ServiceState][bigbrotr.models.service_state.ServiceState] rows to
    distinguish between different kinds of persisted state.

    Attributes:
        CHECKPOINT: A timestamp marker recording when an action was last
            performed (e.g., API fetch, relay health check, candidate
            validation attempt).
        CURSOR: A processing cursor marking the last-processed position
            in an ordered data source (e.g., event timestamp, relay index).

    See Also:
        [ServiceState][bigbrotr.models.service_state.ServiceState]: The row
            model that carries this type.
    """

    CHECKPOINT = "checkpoint"
    CURSOR = "cursor"


class ServiceStateDbParams(NamedTuple):
    """Database parameter container for the ``service_state`` table.

    Column order matches the ``service_state_upsert`` stored procedure
    signature: ``(service_names TEXT[], state_types TEXT[], state_keys TEXT[],
    state_values JSONB[])``.

    The ``state_value`` field is pre-serialized to a JSON string, consistent
    with how ``EventDbParams.tags`` and ``MetadataDbParams.data`` handle
    JSONB columns. This allows asyncpg's registered JSONB codec to pass
    the value through without needing explicit ``::jsonb[]`` casts.

    See Also:
        [ServiceState.to_db_params][bigbrotr.models.service_state.ServiceState.to_db_params]:
            Returns a cached instance of this tuple.
    """

    service_name: str
    state_type: str
    state_key: str
    state_value: str


@dataclass(frozen=True, slots=True)
class ServiceState:
    """A single row in the ``service_state`` table.

    Used as input to ``Brotr.upsert_service_state()`` and as return type
    from ``Brotr.get_service_state()``.

    Attributes:
        service_name: Owning service identifier. Built-in services use the
            [ServiceName][bigbrotr.models.constants.ServiceName] catalog, but
            arbitrary non-empty string IDs are accepted for extensibility.
        state_type: Discriminator. Built-in records use the
            [ServiceStateType][bigbrotr.models.service_state.ServiceStateType]
            catalog, but arbitrary non-empty string IDs are accepted.
        state_key: Application-defined key within the service and type
            (e.g., a relay URL for cursor state).
        state_value: Arbitrary normalized JSON-compatible dictionary with
            service-specific data. Each state type stores its own business timestamp inside
            this dict (e.g. ``{"timestamp": 1700000000}`` for checkpoints).

    Examples:
        ```python
        state = ServiceState(
            service_name=ServiceName.SYNCHRONIZER,
            state_type=ServiceStateType.CURSOR,
            state_key="wss://relay.damus.io",
            state_value={"timestamp": 1700000000},
        )
        state.to_db_params()  # ServiceStateDbParams(...)
        ```

    Note:
        Uses ``object.__setattr__`` in ``__post_init__`` to set computed
        fields on frozen dataclasses. This is the standard workaround for
        frozen dataclass initialization and is safe because ``__post_init__``
        runs during ``__init__`` before the instance is exposed to external
        code.

    See Also:
        [ServiceStateType][bigbrotr.models.service_state.ServiceStateType]:
            Enum of valid ``state_type`` values.
        [ServiceStateDbParams][bigbrotr.models.service_state.ServiceStateDbParams]:
            Database parameter container returned by ``to_db_params()``.
    """

    service_name: str
    state_type: str
    state_key: str
    state_value: Mapping[str, Any]
    _json_value: str = field(default="", init=False, repr=False, compare=False)
    _db_params: ServiceStateDbParams = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
        hash=False,  # type: ignore[assignment]  # mypy expects bool literal, field() accepts it at runtime
    )

    def __post_init__(self) -> None:
        normalized_service_name = _normalize_state_token(self.service_name, "service_name")
        normalized_state_type = _normalize_state_token(self.state_type, "state_type")
        object.__setattr__(self, "service_name", normalized_service_name)
        object.__setattr__(self, "state_type", normalized_state_type)
        validate_str_not_empty(self.state_key, "state_key")
        validate_mapping(self.state_value, "state_value")

        normalized = normalize_json_data(self.state_value, "state_value")
        object.__setattr__(self, "_json_value", json.dumps(normalized))
        object.__setattr__(self, "state_value", deep_freeze(normalized))
        object.__setattr__(self, "_db_params", self._compute_db_params())

    def _compute_db_params(self) -> ServiceStateDbParams:
        return ServiceStateDbParams(
            service_name=self.service_name,
            state_type=self.state_type,
            state_key=self.state_key,
            state_value=self._json_value,
        )

    def to_db_params(self) -> ServiceStateDbParams:
        """Return cached database parameters.

        Returns:
            [ServiceStateDbParams][bigbrotr.models.service_state.ServiceStateDbParams]
            with fields in stored procedure column order.
        """
        return self._db_params


def _normalize_state_token(value: str | StrEnum, name: str) -> str:
    """Normalize enum-backed or plain string state identifiers."""
    normalized = value.value if isinstance(value, StrEnum) else value
    validate_str_not_empty(normalized, name)
    return normalized
