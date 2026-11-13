"""Moving-block bootstrap over valid days (docs/01 section 7).

Errors of one valid day are resampled together (cross-station correlation kept); blocks
of consecutive days keep the temporal autocorrelation. A fixed seed makes results
reproducible (docs/06 section 3, acceptance criterion 2).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

DayValues = list[NDArray[np.float64]]


def moving_block_ci(
    per_day: DayValues,
    stat: Callable[[NDArray[np.float64]], float],
    block_days: int,
    n_boot: int = 2000,
    level: float = 0.95,
    seed: int = 20261113,
) -> tuple[float, float]:
    """Percentile CI of ``stat`` over concatenated day arrays.

    ``per_day`` holds one array per consecutive valid day (empty days allowed). Returns
    ``(nan, nan)`` when there are fewer days than two blocks.
    """
    n_days = len(per_day)
    block = max(1, min(block_days, n_days))
    if n_days < 2 * block:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n_days / block))
    starts_max = n_days - block + 1
    out = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.integers(0, starts_max, size=n_blocks)
        days = np.concatenate([np.arange(s, s + block) for s in starts])[:n_days]
        sample = np.concatenate([per_day[d] for d in days])
        out[i] = stat(sample) if sample.size else np.nan
    alpha = (1.0 - level) / 2.0
    lo, hi = np.nanquantile(out, [alpha, 1.0 - alpha])
    return float(lo), float(hi)
