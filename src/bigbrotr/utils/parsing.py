"""Tolerant parsing of raw data into validated model instances.

Provides generic factory-based converters that iterate over sequences of raw
data (DB param tuples or row dictionaries), call a user-supplied
factory for each element, and collect only the successfully parsed results.
Invalid entries are logged at WARNING level and skipped.

The module depends only on :mod:`bigbrotr.models` and the standard library,
keeping it safe to import from any layer above ``models``.

Examples:
    ```python
    from bigbrotr.models import Relay
    from bigbrotr.models.relay import RelayDbParams
    from bigbrotr.utils.parsing import models_from_db_params, models_from_dict

    relays = models_from_db_params(params_list, Relay.from_db_params)
    relays = models_from_dict(rows, lambda r: Relay(r["url"], discovered_at=r["discovered_at"]))
    ```
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, TypeVar


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

logger = logging.getLogger(__name__)

_P = TypeVar("_P")
_M = TypeVar("_M")
_T = TypeVar("_T")


def models_from_db_params(
    params_list: Sequence[_P],
    factory: Callable[[_P], _M],
) -> list[_M]:
    """Parse db param objects into model instances, skipping invalid entries.

    Calls ``factory(params)`` for each element.  Items that raise
    ``ValueError`` or ``TypeError`` are logged and discarded.
    """
    results: list[_M] = []
    for params in params_list:
        try:
            results.append(factory(params))
        except (ValueError, TypeError):
            logger.warning("parse_failed params=%s", params)
    return results


def models_from_dict(
    rows: Sequence[dict[str, Any]],
    factory: Callable[[dict[str, Any]], _T],
) -> list[_T]:
    """Parse row dictionaries into model instances, skipping invalid entries.

    Calls ``factory(row)`` for each dictionary.  Items that raise
    ``ValueError`` or ``TypeError`` are logged and discarded.
    """
    results: list[_T] = []
    for row in rows:
        try:
            results.append(factory(row))
        except (ValueError, TypeError):
            logger.warning("parse_failed row=%s", row)
    return results


__all__ = [
    "models_from_db_params",
    "models_from_dict",
]
