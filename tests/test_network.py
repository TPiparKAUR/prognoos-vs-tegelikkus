"""Smoke test against a real ECMWF open data mirror (``pytest -m network``).

Downloads ~5 MB: step 0 static fields and step 6 of the most recent AIFS Single
run that is old enough to be published, and checks the extracted box is plausible.
"""

from __future__ import annotations

import datetime as dt
import os

import polars as pl
import pytest

from pvt.config import REPO_ROOT, load_settings
from pvt.ingest.ecmwf import (
    assemble_static_frame,
    assemble_step_frame,
    make_fetchers,
)
from pvt.ingest.ecmwf_grib import BoxExtractor, expected_box_size, read_box_fields
from pvt.timeutil import floor_to_run, utc_now

pytestmark = pytest.mark.network


@pytest.mark.parametrize("model_id", ["aifs-single", "ifs"])
def test_real_mirror_one_step(tmp_path: os.PathLike[str], model_id: str) -> None:
    s = load_settings(REPO_ROOT / "config", data_root=tmp_path)
    model = s.models[model_id]
    source = os.environ.get("PVT_TEST_SOURCE", "google")
    (fetcher,) = make_fetchers(s, [source])
    issue = floor_to_run(utc_now() - dt.timedelta(hours=12))
    assert fetcher.has_step(model, issue, 6), f"{model_id} {issue} step 6 not on {source}"
    ex = BoxExtractor(s.ecmwf.area)
    target = tmp_path / "x.grib2"  # type: ignore[operator]
    fetcher.retrieve(model, issue, [0], s.ecmwf.static_params, target)
    static = assemble_static_frame(read_box_fields(target, ex), model, issue, "test")
    fetcher.retrieve(model, issue, [6], s.ecmwf.step_params, target)
    grid = assemble_step_frame(
        read_box_fields(target, ex), model, issue, [6], s.ecmwf.step_params, "test"
    )
    n = expected_box_size(s.ecmwf.area)
    assert grid.height == n
    assert static.height == n
    assert grid.select(pl.col("t2m_degC").is_between(-45, 40).all()).item()
    assert grid.select(pl.col("mslp_hPa").is_between(940, 1060).all()).item()
    assert grid.select(pl.col("precip_acc_mm").is_between(0, 200).all()).item()
    assert static.select(pl.col("grid_lsm_frac").is_between(0, 1).all()).item()
    assert static.select(pl.col("grid_orog_m").is_between(-20, 400).all()).item()
