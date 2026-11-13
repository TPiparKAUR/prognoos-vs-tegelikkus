"""GRIB box extraction and the idempotent ECMWF run ingest (with fake mirrors)."""

from __future__ import annotations

import dataclasses
import datetime as dt
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from pvt.config import Settings
from pvt.extract.points import load_points
from pvt.ingest.ecmwf import discover_run, ingest, ingest_run, relative_key
from pvt.ingest.ecmwf_grib import BoxExtractor, GribContentError, read_box_fields
from pvt.schemas import (
    FORECAST_GRID,
    FORECAST_GRID_KEY,
    FORECAST_POINT,
    FORECAST_POINT_KEY,
    validate,
)
from pvt.storage import ecmwf_grid_path, ecmwf_manifest_path, read_json, sha256_file
from tests.conftest import ISSUE, TEST_AREA, TEST_STEPS, FakeFetcher, field_value, write_grib

NOW = ISSUE + dt.timedelta(hours=20)  # old enough to be "complete or partial"

# ------------------------------------------------------------------ GRIB extraction


@pytest.mark.parametrize("lon_first", [180.0, 0.0, -180.0])
def test_box_extraction_independent_of_longitude_convention(
    tmp_path: Path, lon_first: float
) -> None:
    path = tmp_path / "a.grib2"
    write_grib(path, [("2t", 6)], lon_first=lon_first)
    (fld,) = read_box_fields(path, BoxExtractor(TEST_AREA))
    assert fld.lat_deg.size == 4 * 8  # 57..60 x 21..28 at 1 degree
    assert fld.lat_deg[0] == 60.0
    assert fld.lon_deg[0] == 21.0
    assert fld.lat_deg[-1] == 57.0
    assert fld.lon_deg[-1] == 28.0
    expected = field_value("2t", 6, fld.lat_deg, fld.lon_deg)
    np.testing.assert_allclose(fld.values, expected, atol=1e-3)
    assert fld.units == "K"
    assert fld.end_step_h == 6
    assert fld.gen_proc_id == 161
    assert fld.valid_time == ISSUE + dt.timedelta(hours=6)


def test_pressure_level_fields_are_skipped(tmp_path: Path) -> None:
    import eccodes

    path = tmp_path / "pl.grib2"
    write_grib(path, [("z", 0)])
    h = eccodes.codes_grib_new_from_samples("regular_ll_pl_grib2")
    with path.open("ab") as fh:
        eccodes.codes_write(h, fh)
    eccodes.codes_release(h)
    fields = read_box_fields(path, BoxExtractor(TEST_AREA))
    assert [f.short_name for f in fields] == ["z"]


def test_wrong_grid_increment_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "b.grib2"
    write_grib(path, [("2t", 0)], increment=2.0)
    with pytest.raises(GribContentError, match="increment"):
        read_box_fields(path, BoxExtractor(TEST_AREA))


def test_relative_key_layout(settings: Settings) -> None:
    key = relative_key(settings.models["ifs"], ISSUE, 9)
    assert key == "20261112/06z/ifs/0p25/oper/20261112060000-9h-oper-fc.grib2"
    key = relative_key(settings.models["aifs-single"], ISSUE, 6, "index")
    assert key == "20261112/06z/aifs-single/0p25/oper/20261112060000-6h-oper-fc.index"


# ------------------------------------------------------------------ discovery


def test_discovery_falls_back_to_mirror_with_complete_run(settings: Settings) -> None:
    model = settings.models["ifs"]
    lagging = FakeFetcher("aws", {0, 3})
    full = FakeFetcher("google", set(TEST_STEPS))
    d = discover_run(model, ISSUE, [lagging, full], age_h=20, partial_after_h=14)
    assert d.status == "available"
    assert d.source == "google"
    assert d.steps_available == TEST_STEPS


def test_discovery_young_incomplete_run_is_not_available(settings: Settings) -> None:
    model = settings.models["ifs"]
    d = discover_run(model, ISSUE, [FakeFetcher("aws", {0, 3})], age_h=6, partial_after_h=14)
    assert d.status == "not_available"


def test_discovery_old_incomplete_run_is_partial(settings: Settings) -> None:
    model = settings.models["ifs"]
    d = discover_run(model, ISSUE, [FakeFetcher("aws", {0, 3, 9})], age_h=20, partial_after_h=14)
    assert d.status == "partial"
    assert d.steps_available == (0, 3, 9)


# ------------------------------------------------------------------ run ingest


def _run(settings: Settings, fetcher: FakeFetcher, model_id: str = "ifs") -> dict[str, object]:
    res = ingest_run(settings, settings.models[model_id], ISSUE, [fetcher], NOW)
    return res.manifest


def test_complete_run_is_archived_and_valid(settings: Settings) -> None:
    man = _run(settings, FakeFetcher("aws", set(TEST_STEPS)))
    assert man["status"] == "complete"
    assert man["steps_archived"] == list(TEST_STEPS)
    assert man["steps_missing"] == []
    assert man["stations"] == 2
    assert man["stations_skipped_outside_area"] == ["S3"]
    grid = pl.read_parquet(ecmwf_grid_path(settings.data_root, "ifs", ISSUE, "grid"))
    validate(grid, FORECAST_GRID, FORECAST_GRID_KEY)
    # only stencil points are archived: S1 4 corners (+ nearest land among them),
    # S2 4 corners + nearest land outside them
    n_points = grid.select("grid_lat_deg", "grid_lon_deg").unique().height
    assert n_points == 9
    assert grid.height == len(TEST_STEPS) * n_points
    static = pl.read_parquet(ecmwf_grid_path(settings.data_root, "ifs", ISSUE, "static"))
    assert static.height == n_points

    pts = load_points(settings.data_root, "ifs", ISSUE)
    validate(pts, FORECAST_POINT, FORECAST_POINT_KEY)
    assert pts.height == len(TEST_STEPS) * (3 + 3)  # 2 stations x 3 methods
    s1 = pts.filter((pl.col("station_id") == "S1") & (pl.col("lead_h") == 6))
    bil = s1.filter(pl.col("interp_method") == "bilinear").row(0, named=True)
    # bilinear interpolation is exact for the linear synthetic fields
    t2m = 270.0 + 0.1 * 58.5 + 0.01 * 24.25 + 0.5 * 6 - 273.15
    assert bil["t2m_degC"] == pytest.approx(t2m, abs=1e-3)
    assert bil["grid_orog_m"] == pytest.approx(10.0 + 58.5, abs=1e-3)
    assert bil["t2m_hcorr_degC"] == pytest.approx(t2m - 0.0065 * (20.0 - 68.5), abs=1e-3)
    assert bil["mslp_hPa"] == pytest.approx((101_000.0 + 585.0 + 30.0) / 100.0, abs=1e-3)
    assert bil["precip_acc_mm"] == pytest.approx(0.0001 * 6 * 1.015 * 1000.0, abs=1e-3)
    assert bil["gust10m_max_m_s"] == pytest.approx(8.0 + 0.585 + 0.6, abs=1e-3)
    assert bil["gust_window_start_h"] == 5
    assert bil["grid_lat_deg"] is None
    u = 3.0 + 0.2425 + 0.6
    v = -2.0 + 0.585
    assert bil["wind10m_speed_m_s"] == pytest.approx((u * u + v * v) ** 0.5, abs=1e-3)
    assert bil["station_height_m_EH2000"] == 20.0
    near = s1.filter(pl.col("interp_method") == "nearest").row(0, named=True)
    # equidistant in latitude; 0.25 deg of longitude is shorter at 59N -> (59, 24)
    assert (near["grid_lat_deg"], near["grid_lon_deg"]) == (59.0, 24.0)
    s2_land = pts.filter(
        (pl.col("station_id") == "S2") & (pl.col("interp_method") == "nearest_land")
    ).row(0, named=True)
    assert (s2_land["grid_lat_deg"], s2_land["grid_lon_deg"]) == (59.0, 23.0)
    assert s2_land["grid_lsm_frac"] == 1.0
    assert s2_land["source_uri"].startswith("ecmwf-opendata:20261112/06z/ifs/")


def test_gust_is_optional_per_step(settings: Settings) -> None:
    """IFS open data has no 10fg for 93-144 h; such steps must not fail the run."""
    f = FakeFetcher("aws", set(TEST_STEPS), drop_at=frozenset({("10fg", 9)}))
    man = _run(settings, f)
    assert man["status"] == "complete"
    assert man["optional_param_steps"] == {"10fg": [0, 3, 6, 12]}
    pts = load_points(settings.data_root, "ifs", ISSUE)
    assert pts.filter(pl.col("lead_h") == 9).get_column("gust10m_max_m_s").null_count() == 6
    assert pts.filter(pl.col("lead_h") == 12).get_column("gust10m_max_m_s").null_count() == 0


def test_aifs_has_no_gust(settings: Settings) -> None:
    man = _run(settings, FakeFetcher("aws", set(TEST_STEPS)), model_id="aifs-single")
    assert man["status"] == "complete"
    pts = load_points(settings.data_root, "aifs-single", ISSUE)
    assert pts.get_column("gust10m_max_m_s").null_count() == pts.height


def test_rerun_skips_complete_runs(settings: Settings) -> None:
    f = FakeFetcher("aws", set(TEST_STEPS))
    first = ingest(settings, ["ifs"], start=ISSUE, end=ISSUE, now=NOW, fetchers=[f])
    assert [r.status for r in first] == ["complete"]
    probes, retrieves = f.probes, f.retrieves
    second = ingest(settings, ["ifs"], start=ISSUE, end=ISSUE, now=NOW, fetchers=[f])
    assert second == []
    assert (f.probes, f.retrieves) == (probes, retrieves)


def test_reingest_is_byte_identical(settings: Settings) -> None:
    f = FakeFetcher("aws", set(TEST_STEPS))
    _run(settings, f)
    gpath = ecmwf_grid_path(settings.data_root, "ifs", ISSUE, "grid")
    h1 = sha256_file(gpath)
    ingest(settings, ["ifs"], start=ISSUE, end=ISSUE, now=NOW, fetchers=[f], force=True)
    assert sha256_file(gpath) == h1


def test_modified_archive_file_triggers_reingest(settings: Settings) -> None:
    f = FakeFetcher("aws", set(TEST_STEPS))
    _run(settings, f)
    gpath = ecmwf_grid_path(settings.data_root, "ifs", ISSUE, "grid")
    gpath.write_bytes(b"corrupt")
    res = ingest(settings, ["ifs"], start=ISSUE, end=ISSUE, now=NOW, fetchers=[f])
    assert [r.status for r in res] == ["complete"]
    assert pl.read_parquet(gpath).height == len(TEST_STEPS) * 9


def test_partial_run_then_completed_later(settings: Settings) -> None:
    f = FakeFetcher("aws", {0, 3, 6})
    man = _run(settings, f)
    assert man["status"] == "partial"
    assert man["steps_missing"] == [9, 12]
    f.steps = set(TEST_STEPS)
    res = ingest(settings, ["ifs"], start=ISSUE, end=ISSUE, now=NOW, fetchers=[f])
    assert [r.status for r in res] == ["complete"]
    assert read_json(ecmwf_manifest_path(settings.data_root, "ifs", ISSUE))["attempts"] == 2


def test_young_unavailable_run_writes_nothing(settings: Settings) -> None:
    res = ingest_run(
        settings,
        settings.models["ifs"],
        ISSUE,
        [FakeFetcher("aws", set())],
        ISSUE + dt.timedelta(hours=6),
    )
    assert res.status == "not_available"
    assert not ecmwf_manifest_path(settings.data_root, "ifs", ISSUE).exists()


def test_old_unavailable_run_is_recorded(settings: Settings) -> None:
    res = ingest_run(settings, settings.models["ifs"], ISSUE, [FakeFetcher("aws", set())], NOW)
    assert res.status == "not_available"
    assert read_json(ecmwf_manifest_path(settings.data_root, "ifs", ISSUE))["status"] == (
        "not_available"
    )


@pytest.mark.parametrize(
    ("fetcher", "message"),
    [
        (FakeFetcher("aws", set(TEST_STEPS), fail_retrieve=True), "simulated outage"),
        (FakeFetcher("aws", set(TEST_STEPS), drop_param="msl"), "missing fields"),
        (
            FakeFetcher(
                "aws",
                set(TEST_STEPS),
                transform=lambda p, s, v: v * 0.0 if (p == "tp" and s == 12) else v,
            ),
            "accumulation decreases",
        ),
    ],
)
def test_bad_runs_fail_without_archive(
    settings: Settings, fetcher: FakeFetcher, message: str
) -> None:
    man = _run(settings, fetcher)
    assert man["status"] == "failed"
    assert message in str(man["detail"])
    assert not ecmwf_grid_path(settings.data_root, "ifs", ISSUE, "grid").exists()


def test_min_issue_time_guard(settings: Settings) -> None:
    model = dataclasses.replace(settings.models["ifs"], min_issue_time=ISSUE)
    s = dataclasses.replace(settings, models={**settings.models, "ifs": model})
    f = FakeFetcher("aws", set(TEST_STEPS))
    res = ingest(s, ["ifs"], start=ISSUE - dt.timedelta(days=1), end=ISSUE, now=NOW, fetchers=[f])
    assert [r.issue_time_utc for r in res] == ["2026-11-12T06:00:00Z"]


# ------------------------------------------------------------------ packing precision


def _acc_frame(values: list[float], quanta: list[float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "lead_h": list(range(0, 6 * len(values), 6)),
            "grid_lat_deg": [59.0] * len(values),
            "grid_lon_deg": [24.0] * len(values),
            "precip_acc_mm": values,
            "precip_acc_quantum_mm": quanta,
        }
    )


def test_accumulation_decrease_within_packing_precision_is_accepted() -> None:
    from pvt.ingest.ecmwf import _check_accumulation

    # Observed in AIFS 2026-11-12 06 UTC: 22.4375 -> 22.3750 with quanta 0.0625 / 0.125.
    _check_accumulation(_acc_frame([0.0, 22.4375, 22.375], [0.0, 0.0625, 0.125]))


def test_accumulation_decrease_beyond_packing_precision_fails() -> None:
    from pvt.ingest.ecmwf import IngestError, _check_accumulation

    with pytest.raises(IngestError, match="beyond packing precision"):
        _check_accumulation(_acc_frame([0.0, 22.4375, 22.25], [0.0, 0.0625, 0.125]))


def test_packing_quantum_is_archived(settings: Settings) -> None:
    _run(settings, FakeFetcher("aws", set(TEST_STEPS)))
    df = pl.read_parquet(ecmwf_grid_path(settings.data_root, "ifs", ISSUE, "grid"))
    q = df.group_by("lead_h").agg(pl.col("precip_acc_quantum_mm").first()).sort("lead_h")
    # step 0 tp is a constant field -> quantum 0; later steps are packed with 24 bits
    assert q.get_column("precip_acc_quantum_mm")[0] == 0.0
    assert all(0 < v < 1e-3 for v in q.get_column("precip_acc_quantum_mm")[1:])


@pytest.mark.parametrize(
    ("u", "v", "expected"),
    [(0.0, -5.0, 0.0), (-5.0, 0.0, 90.0), (0.0, 5.0, 180.0), (5.0, 0.0, 270.0)],
)
def test_wind_direction_is_meteorological(u: float, v: float, expected: float) -> None:
    from pvt.extract.points import wind_speed_dir

    df = pl.DataFrame({"u": [u], "v": [v]})
    speed, direction = wind_speed_dir(pl.col("u"), pl.col("v"))
    row = df.select(speed.alias("s"), direction.alias("d")).row(0)
    assert row[0] == pytest.approx(5.0)
    assert row[1] % 360.0 == pytest.approx(expected)


def test_invocation_cap_takes_newest_first(settings: Settings) -> None:
    f = FakeFetcher("aws", set(TEST_STEPS))
    start = ISSUE - dt.timedelta(hours=6)
    res = ingest(
        settings, ["ifs", "aifs-single"], start=start, end=ISSUE, now=NOW, fetchers=[f], max_runs=2
    )
    assert [(r.model_id, r.issue_time_utc) for r in res] == [
        ("ifs", "2026-11-12T06:00:00Z"),
        ("aifs-single", "2026-11-12T06:00:00Z"),
    ]
    rest = ingest(
        settings, ["ifs", "aifs-single"], start=start, end=ISSUE, now=NOW, fetchers=[f], max_runs=10
    )
    assert sorted(r.issue_time_utc for r in rest) == ["2026-11-12T00:00:00Z"] * 2
