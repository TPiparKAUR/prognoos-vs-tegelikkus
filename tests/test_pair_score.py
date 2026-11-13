"""Pairing and scoring on small synthetic tables."""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from pvt.pair import (
    apply_qc,
    build_hourly_pairs,
    build_precip_pairs,
    fc_precip24,
    obs_precip24,
    persistence,
)
from pvt.score import classify, long_errors, scores_by_bucket, scores_precip, with_samples

T0 = dt.datetime(2026, 11, 10, 0, tzinfo=dt.UTC)


def _fc(model: str, leads: list[int], t2m: float, acc_per_h: float = 0.0) -> pl.DataFrame:
    rows = []
    for lead in leads:
        for method in ("nearest_land", "bilinear"):
            rows.append(
                {
                    "model_id": model,
                    "model_cycle": "x",
                    "issue_time_utc": T0,
                    "valid_time_utc": T0 + dt.timedelta(hours=lead),
                    "lead_h": lead,
                    "member": -1,
                    "station_id": "S1",
                    "interp_method": method,
                    "t2m_degC": t2m,
                    "t2m_hcorr_degC": t2m,
                    "wind10m_speed_m_s": 5.0,
                    "wind10m_dir_deg": 350.0,
                    "mslp_hPa": 1000.0,
                    "precip_acc_mm": acc_per_h * lead,
                    "precip_acc_quantum_mm": 0.1,
                    "grid_lsm_frac": 1.0,
                    "grid_dist_km": 10.0,
                }
            )
    return pl.DataFrame(rows).with_columns(pl.col("lead_h").cast(pl.Int16))


def _truth(hours: range, t2m: float, pr: float = 0.0) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "station_id": "S1",
            "valid_time_utc": [T0 + dt.timedelta(hours=h) for h in hours],
            "obs_t2m_degC": t2m,
            "obs_wind_speed_m_s": 4.0,
            "obs_wind_dir_deg": 10.0,
            "obs_mslp_hPa": 1001.0,
            "obs_precip_1h_mm": pr,
            "obs_provenance": "kvaliteedikontrollitud",
            "obs_source": "kaur_kliima_hly",
            "truth_level": "T2",
            "obs_lag_min": 0,
            "qc_flags": 0,
        }
    ).with_columns(pl.col("obs_lag_min", "qc_flags").cast(pl.Int16))


def test_persistence_uses_observation_known_at_issue_time() -> None:
    fc = _fc("ifs", [6, 30], 0.0)
    truth = _truth(range(-48, 48), 0.0).with_columns(
        (pl.col("valid_time_utc").dt.hour().cast(pl.Float64)).alias("obs_t2m_degC")
    )
    p = persistence(fc, truth).sort("lead_h")
    # lead 6 -> obs at valid-24 h, lead 30 -> valid-48 h: both = issue-18 h (hour 06)
    assert p["fc_t2m_degC"].to_list() == [6.0, 6.0]


def test_hourly_pairs_scores_and_common_sample() -> None:
    fc = pl.concat([_fc("ifs", [6, 12, 30], 2.0), _fc("aifs-single", [6, 30], 1.0)])
    truth = _truth(range(-48, 48), 0.0)
    pairs = build_hourly_pairs(fc, [truth])
    long = with_samples(long_errors(pairs))
    common = long.filter(pl.col("sample") == "common", pl.col("variable") == "t2m")
    # lead 12 exists only for IFS -> not in the common sample
    assert set(common["lead_h"].to_list()) == {6, 30}
    b = scores_by_bucket(long).filter(
        pl.col("variable") == "t2m",
        pl.col("sample") == "common",
        pl.col("interp_method") == "nearest_land",
        pl.col("lead_bucket") == "D1",
    )
    by_model = dict(zip(b["model_id"], b["mae"], strict=True))
    assert by_model["ifs"] == pytest.approx(2.0)
    assert by_model["aifs-single"] == pytest.approx(1.0)
    assert by_model["persistence"] == pytest.approx(0.0)
    wd = long.filter(pl.col("variable") == "wind_dir", pl.col("model_id") == "ifs")
    assert wd["err"].to_list()[0] == pytest.approx(-20.0)


def test_qc_nulls_out_of_range_and_flags() -> None:
    obs = pl.DataFrame(
        {
            "obs_t2m_degC": [5.0, 99.0],
            "obs_wind_speed_m_s": [3.0, 3.0],
            "obs_mslp_hPa": [None, 900.0],
        }
    )
    q = apply_qc(obs)
    assert q["obs_t2m_degC"].to_list() == [5.0, None]
    assert q["qc_flags"].to_list() == [0, 1 + 4]


def test_precip24_windows_and_bound() -> None:
    truth = _truth(range(1, 49), 0.0, pr=0.5)  # 0.5 mm every hour
    obs = obs_precip24(truth)
    w00 = obs.filter(pl.col("window") == "00-00")
    assert w00["obs_precip_24h_mm"].to_list() == [pytest.approx(12.0)] * 2
    assert sorted(w00["window_end_utc"].to_list()) == [
        T0 + dt.timedelta(hours=24),
        T0 + dt.timedelta(hours=48),
    ]
    # 06-06: only the window ending T0+30 h has all 24 hours (hours 7..30)
    w06 = obs.filter(pl.col("window") == "06-06")
    assert w06["window_end_utc"].to_list() == [T0 + dt.timedelta(hours=30)]
    fc = _fc("ifs", [0, 6, 24, 30, 48], 0.0, acc_per_h=0.25)
    f24 = fc_precip24(fc).filter(pl.col("interp_method") == "nearest_land")
    assert f24["fc_precip_24h_mm"].to_list() == [pytest.approx(6.0)] * 3
    assert f24["fc_bound_mm"].to_list() == [pytest.approx(0.1)] * 3
    pp = build_precip_pairs(fc, truth)
    sp = scores_precip(pp).filter(
        pl.col("threshold_mm") == 5.0, pl.col("interp_method") == "bilinear"
    )
    assert sp["a"].sum() == sp.height
    assert sp["n_uncertain"].sum() == 0


def test_classify_three_way() -> None:
    assert classify(0.25, 0.06, 0.2) == "uncertain"
    assert classify(0.30, 0.06, 0.2) == "yes"
    assert classify(0.10, 0.06, 0.2) == "no"


def test_columnar_export_rounds_and_nulls_nan() -> None:
    from pvt.site.build import columnar

    df = pl.DataFrame({"a": [1.234567, float("nan")], "t": [T0, T0]})
    out = columnar(df)
    assert out["a"] == [1.2346, None]
    assert out["t"] == ["2026-11-10T00:00:00Z"] * 2


def test_xml_rows_link_to_climate_station_only_by_wmo_or_name() -> None:
    from pvt.pair import link_climate_station

    climate = pl.DataFrame({"station_id": ["AJTOOM01"], "name": ["Tooma"], "wmo_code": ["26147"]})
    x = pl.DataFrame(
        {
            "station_id": ["XML_TOOMA", "XML_SOOJAAM", "XML_OTHER"],
            "kliima_station_id": ["AJTOOM01", "AJTOOM01", None],
            "station_name": ["Tooma", "Tooma soojaam 1", "Elsewhere"],
            "wmo_code": ["26147", "00", None],
        }
    )
    out = x.select(link_climate_station(climate).alias("sid"))["sid"].to_list()
    assert out == ["AJTOOM01", "XML_SOOJAAM", "XML_OTHER"]
