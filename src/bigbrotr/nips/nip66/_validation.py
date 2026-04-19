from __future__ import annotations

import math

from bigbrotr.utils.transport import DEFAULT_TIMEOUT


def normalize_timeout_budget(timeout: float | None) -> float:
    if timeout is None:
        return DEFAULT_TIMEOUT
    if isinstance(timeout, bool) or not isinstance(timeout, int | float):
        raise ValueError("timeout must be a positive finite number")
    normalized = float(timeout)
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError("timeout must be a positive finite number")
    return normalized
