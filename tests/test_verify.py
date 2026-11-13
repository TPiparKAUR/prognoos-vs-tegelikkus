"""Known-value tests for the verification package (docs/06 section 1)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from pvt.verify.bootstrap import moving_block_ci
from pvt.verify.categorical import Contingency
from pvt.verify.continuous import (
    circular_diff_deg,
    circular_mae_deg,
    corr,
    mae,
    me,
    rmse,
    skill_score,
    vector_rmse,
    wind_uv,
)


def test_continuous_known_values() -> None:
    f, o = [1.0, 2.0, 3.0], [1.0, 1.0, 1.0]
    assert me(f, o) == pytest.approx(1.0)
    assert mae(f, o) == pytest.approx(1.0)
    assert rmse(f, o) == pytest.approx(math.sqrt(5 / 3))
    assert rmse(f, o) == pytest.approx(1.29099, abs=1e-5)


def test_nan_pairs_ignored_and_empty_is_nan() -> None:
    assert mae([1.0, np.nan], [0.0, 5.0]) == pytest.approx(1.0)
    assert math.isnan(mae([np.nan], [1.0]))
    assert math.isnan(corr([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]))


def test_skill_score() -> None:
    assert skill_score(1.0, 4.0) == pytest.approx(0.75)
    assert math.isnan(skill_score(1.0, 0.0))


def test_circular() -> None:
    assert circular_diff_deg(350.0, 10.0) == pytest.approx(-20.0)
    assert circular_diff_deg(10.0, 350.0) == pytest.approx(20.0)
    assert circular_mae_deg([350.0, 90.0], [10.0, 90.0]) == pytest.approx(10.0)


def test_wind_uv_and_vector_rmse() -> None:
    u, v = wind_uv([10.0], [270.0])  # westerly wind blows towards east: u > 0
    assert u[0] == pytest.approx(10.0)
    assert v[0] == pytest.approx(0.0, abs=1e-12)
    assert vector_rmse([3.0], [0.0], [0.0], [4.0]) == pytest.approx(5.0)


def test_contingency_known_values() -> None:
    t = Contingency(a=10, b=5, c=5, d=80)
    assert t.pod() == pytest.approx(0.6667, abs=1e-4)
    assert t.far() == pytest.approx(0.3333, abs=1e-4)
    assert t.csi() == pytest.approx(0.5)
    assert t.freq_bias() == pytest.approx(1.0)
    assert t.ets() == pytest.approx(7.75 / 17.75)
    assert t.pss() == pytest.approx(0.6078, abs=1e-4)
    assert t.hss() == pytest.approx(0.6078, abs=1e-4)


def test_contingency_undefined_is_nan() -> None:
    t = Contingency(0, 0, 0, 10)
    assert math.isnan(t.pod())
    assert math.isnan(t.far())


def test_bootstrap_reproducible_and_brackets_mean() -> None:
    rng = np.random.default_rng(1)
    days = [rng.normal(1.0, 0.5, 20) for _ in range(40)]
    lo, hi = moving_block_ci(days, lambda a: float(np.mean(a)), block_days=7, n_boot=300)
    assert lo < 1.0 < hi
    assert (lo, hi) == moving_block_ci(days, lambda a: float(np.mean(a)), 7, n_boot=300)


def test_bootstrap_too_few_days_is_nan() -> None:
    lo, hi = moving_block_ci([np.ones(3)] * 5, lambda a: float(np.mean(a)), block_days=7)
    assert math.isnan(lo)
    assert math.isnan(hi)
