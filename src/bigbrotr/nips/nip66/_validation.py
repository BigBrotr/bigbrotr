from __future__ import annotations

import math

from bigbrotr.utils.transport import DEFAULT_TIMEOUT


_MIN_GEOHASH_PRECISION = 1
_MAX_GEOHASH_PRECISION = 12


def normalize_timeout_budget(timeout: float | None) -> float:
    if timeout is None:
        return DEFAULT_TIMEOUT
    if isinstance(timeout, bool) or not isinstance(timeout, int | float):
        raise ValueError("timeout must be a positive finite number")
    normalized = float(timeout)
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError("timeout must be a positive finite number")
    return normalized


def normalize_geohash_precision(geohash_precision: int) -> int:
    if isinstance(geohash_precision, bool) or not isinstance(geohash_precision, int):
        raise ValueError(
            "geohash_precision must be an integer "
            f"between {_MIN_GEOHASH_PRECISION} and {_MAX_GEOHASH_PRECISION}"
        )
    if not _MIN_GEOHASH_PRECISION <= geohash_precision <= _MAX_GEOHASH_PRECISION:
        raise ValueError(
            "geohash_precision must be an integer "
            f"between {_MIN_GEOHASH_PRECISION} and {_MAX_GEOHASH_PRECISION}"
        )
    return geohash_precision
