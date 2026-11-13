"""Scores for continuous variables and wind (docs/01 sections 3-4).

All functions take forecast ``f`` and observation ``o`` arrays of equal length and ignore
pairs where either value is NaN. Known-value tests: docs/06 section 1.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

FloatArray = NDArray[np.float64]


def _pairs(f: ArrayLike, o: ArrayLike) -> tuple[FloatArray, FloatArray]:
    fa = np.asarray(f, dtype=np.float64)
    oa = np.asarray(o, dtype=np.float64)
    if fa.shape != oa.shape:
        raise ValueError(f"shape mismatch: {fa.shape} vs {oa.shape}")
    ok = np.isfinite(fa) & np.isfinite(oa)
    return fa[ok], oa[ok]


def me(f: ArrayLike, o: ArrayLike) -> float:
    """Mean error (bias), mean(f - o)."""
    fa, oa = _pairs(f, o)
    return float(np.mean(fa - oa)) if fa.size else float("nan")


def mae(f: ArrayLike, o: ArrayLike) -> float:
    """Mean absolute error."""
    fa, oa = _pairs(f, o)
    return float(np.mean(np.abs(fa - oa))) if fa.size else float("nan")


def rmse(f: ArrayLike, o: ArrayLike) -> float:
    """Root mean squared error."""
    fa, oa = _pairs(f, o)
    return float(np.sqrt(np.mean((fa - oa) ** 2))) if fa.size else float("nan")


def corr(f: ArrayLike, o: ArrayLike, min_n: int = 3) -> float:
    """Pearson correlation; NaN for fewer than ``min_n`` pairs or zero variance."""
    fa, oa = _pairs(f, o)
    if fa.size < min_n or np.std(fa) == 0.0 or np.std(oa) == 0.0:
        return float("nan")
    return float(np.corrcoef(fa, oa)[0, 1])


def skill_score(score: float, score_ref: float, perfect: float = 0.0) -> float:
    """Return the skill score ``(S - S_ref) / (S_perfect - S_ref)``; for MSE: 1 - MSE/MSE_ref."""
    denom = perfect - score_ref
    if not np.isfinite(score) or not np.isfinite(score_ref) or denom == 0.0:
        return float("nan")
    return float((score - score_ref) / denom)


def circular_diff_deg(f: ArrayLike, o: ArrayLike) -> FloatArray:
    """Signed direction difference in [-180, 180): ``((f - o + 180) mod 360) - 180``."""
    fa = np.asarray(f, dtype=np.float64)
    oa = np.asarray(o, dtype=np.float64)
    return np.mod(fa - oa + 180.0, 360.0) - 180.0


def circular_mae_deg(f: ArrayLike, o: ArrayLike) -> float:
    """Mean absolute direction error (degrees)."""
    fa, oa = _pairs(f, o)
    return float(np.mean(np.abs(circular_diff_deg(fa, oa)))) if fa.size else float("nan")


def wind_uv(speed: ArrayLike, direction_deg: ArrayLike) -> tuple[FloatArray, FloatArray]:
    """Wind components from speed and meteorological (coming-from) direction."""
    s = np.asarray(speed, dtype=np.float64)
    d = np.deg2rad(np.asarray(direction_deg, dtype=np.float64))
    return -s * np.sin(d), -s * np.cos(d)


def vector_rmse(fu: ArrayLike, fv: ArrayLike, ou: ArrayLike, ov: ArrayLike) -> float:
    """Vector wind RMSE ``sqrt(mean((u_f - u_o)^2 + (v_f - v_o)^2))``."""
    a = np.column_stack([np.asarray(x, dtype=np.float64) for x in (fu, fv, ou, ov)])
    a = a[np.all(np.isfinite(a), axis=1)]
    if not a.size:
        return float("nan")
    return float(np.sqrt(np.mean((a[:, 0] - a[:, 2]) ** 2 + (a[:, 1] - a[:, 3]) ** 2)))
