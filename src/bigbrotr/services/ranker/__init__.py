"""Private ranking service that exports public score outputs.

Exports the package-level ranking surface:

- [Ranker][bigbrotr.services.ranker.service.Ranker]: Cycle runner that syncs
  canonical facts into the private DuckDB store and exports public scores.
- [RankerConfig][bigbrotr.services.ranker.configs.RankerConfig]: Algorithm,
  storage, batching, and cleanup policy.
- [RankCycleResult][bigbrotr.services.ranker.runtime.RankCycleResult],
  [RankPhaseDurations][bigbrotr.services.ranker.runtime.RankPhaseDurations],
  and [RankRowCounts][bigbrotr.services.ranker.runtime.RankRowCounts]: typed
  runtime results for one ranking cycle.

Private ranking state stays in this package; the public contract exported from
here is score data, not internal run bookkeeping.
"""

from .configs import RankerConfig
from .runtime import RankCycleResult, RankPhaseDurations, RankRowCounts
from .service import Ranker


__all__ = [
    "RankCycleResult",
    "RankPhaseDurations",
    "RankRowCounts",
    "Ranker",
    "RankerConfig",
]
