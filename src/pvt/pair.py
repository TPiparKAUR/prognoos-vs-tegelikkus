"""Forecast-observation pairs (stage E2, ``pvt pair``).

Inputs (all from the archive under ``data_root``):

* ECMWF station values derived from the stencil archive (``load_points``), verified
  stations only (docs/08: unverified stations never enter scores).
* T2 truth ``kvaliteedikontrollitud``: KAUR climate API hourly values (``kliima``).
* T1 truth ``toormõõtmine``: observations XML snapshots (``obs_xml``) of the verified
  stations (matched through ``kliima_station_id``).

Outputs (``data/derived``; recomputed from the archive on every run, never uploaded):

* ``pairs_hourly.parquet``: one row per model x run x lead x station x method x truth
  level, forecast and observed values side by side (``fc_*`` / ``obs_*``).
* ``pairs_precip24.parquet``: 24 h precipitation sums for the windows ending 00 and 06 UTC,
  with the packing-precision bound of ADR-005.

Persistence (docs/01 section 12): ``model_id = "persistence"`` gives, for every IFS run and
lead, the observation at ``valid - 24 h * ceil(lead / 24)`` -- information available at
issue time (KAUR publishes T2 with ~1 day delay, so this is a reference, not an
operational forecast).

Assumptions (reports/stage_2.md):

* PR1H at hour h is the sum over (h-1 h, h] UTC.
* An XML snapshot represents the full hour ``h`` when taken in [h+10 min, h+30 min); the
  earliest such snapshot is used and its lag is kept (``obs_lag_min``). XML pressure is not
  paired (station vs sea level unknown, reports/stage_1b.md question 3).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import polars as pl

from pvt.config import Station
from pvt.extract.points import load_points
from pvt.storage import write_parquet_atomic
from pvt.timeutil import parse_utc

LOG = logging.getLogger(__name__)

METHODS: Final = ("nearest_land", "bilinear", "nearest")
PRIMARY_METHOD: Final = "nearest_land"  # ADR-006
UTC: Final = pl.Datetime("us", "UTC")

# T1 plausibility limits (docs/01 section 10). Values outside are set null (flagged in
# ``qc_flags``), never corrected.
QC_LIMITS: Final = {
    "obs_t2m_degC": (-45.0, 40.0),
    "obs_wind_speed_m_s": (0.0, 60.0),
    "obs_mslp_hPa": (940.0, 1060.0),
}
QC_BIT: Final = {"obs_t2m_degC": 1, "obs_wind_speed_m_s": 2, "obs_mslp_hPa": 4}

XML_LAG_MIN: Final = (10, 30)

HOURLY_KEYS: Final = (
    "model_id",
    "issue_time_utc",
    "lead_h",
    "station_id",
    "interp_method",
    "truth_level",
)


@dataclass(frozen=True)
class PairResult:
    """Paths and row counts of one ``pvt pair`` invocation."""

    hourly_path: Path
    precip_path: Path
    n_hourly: int
    n_precip: int
    runs: int


def derived_dir(data_root: Path) -> Path:
    """Directory of derived (recomputable) products."""
    return data_root / "derived"


def archived_runs(data_root: Path) -> list[tuple[str, dt.datetime, str]]:
    """``(model_id, issue_time, status)`` of every archived ECMWF run with data."""
    out: list[tuple[str, dt.datetime, str]] = []
    for manifest in sorted((data_root / "ecmwf").glob("*/*/*/*.json")):
        try:
            meta = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOG.warning("skipping unreadable manifest %s: %s", manifest, exc)
            continue
        if meta.get("status") not in ("complete", "partial"):
            continue
        out.append((str(meta["model_id"]), parse_utc(str(meta["issue_time_utc"])), meta["status"]))
    return out


def load_forecasts(data_root: Path) -> pl.DataFrame:
    """Deterministic station forecasts of all archived runs and stations.

    ``station_class`` is ``kliima`` for verified climate stations and ``xml`` for the
    observations-XML stations (coordinates from the KAUR XML, no EH2000 height: the
    height-corrected temperature is null there, ADR-019).
    """
    frames = []
    runs = archived_runs(data_root)
    for model_id, issue, _ in runs:
        try:
            pts = load_points(data_root, model_id, issue)
        except (OSError, pl.exceptions.PolarsError) as exc:
            LOG.warning("skipping %s %s: %s", model_id, issue, exc)
            continue
        weights = pl.read_parquet(
            data_root
            / "ecmwf"
            / f"{issue:%Y/%m/%d}"
            / f"{model_id}_{issue:%Y%m%dT%H}Z_weights.parquet",
            columns=["station_id", "station_verified"],
        ).unique()
        verified = weights.filter(pl.col("station_verified"))["station_id"]
        frames.append(
            pts.filter(pl.col("member") == -1).with_columns(
                pl.when(pl.col("station_id").is_in(verified.implode()))
                .then(pl.lit("kliima"))
                .otherwise(pl.lit("xml"))
                .alias("station_class")
            )
        )
    if not frames:
        return pl.DataFrame()
    LOG.info("loaded %d archived runs", len(frames))
    return pl.concat(frames, how="vertical_relaxed")


def _read_days(data_root: Path, dataset: str) -> pl.DataFrame:
    files = sorted((data_root / dataset).glob("*/*/*/*.parquet"))
    if not files:
        return pl.DataFrame()
    return pl.concat([pl.read_parquet(f) for f in files], how="diagonal_relaxed")


def load_truth_t2(data_root: Path) -> pl.DataFrame:
    """Hourly T2 truth (KAUR climate API, ``kvaliteedikontrollitud``)."""
    k = _read_days(data_root, "kliima")
    if k.is_empty():
        return k
    return (
        k.select(
            "station_id",
            "valid_time_utc",
            pl.col("ta_degC").alias("obs_t2m_degC"),
            pl.col("ws10m_m_s").alias("obs_wind_speed_m_s"),
            pl.col("wd10m_deg").alias("obs_wind_dir_deg"),
            pl.col("pa0_hPa").alias("obs_mslp_hPa"),
            pl.col("pr1h_mm").alias("obs_precip_1h_mm"),
            pl.col("provenance").alias("obs_provenance"),
            pl.col("source").alias("obs_source"),
        )
        .unique(["station_id", "valid_time_utc"], keep="last")
        .with_columns(
            pl.lit("T2").alias("truth_level"),
            pl.lit(0, dtype=pl.Int16).alias("obs_lag_min"),
            pl.lit(0, dtype=pl.Int16).alias("qc_flags"),
        )
    )


def link_climate_station(climate: pl.DataFrame) -> pl.Expr:
    """Station id for XML rows: the climate station only if WMO code or name agree.

    The XML lists water-level and other sites within 1 km of climate stations (e.g.
    "Tooma soojaam 1-4"); distance alone (``kliima_station_id``) would mix them in.
    """
    wmo = dict(zip(climate["station_id"], climate["wmo_code"], strict=True))
    name = dict(zip(climate["station_id"], climate["name"], strict=True))
    same_wmo = pl.col("wmo_code").is_not_null() & (
        pl.col("wmo_code") == pl.col("kliima_station_id").replace_strict(wmo, default=None)
    )
    same_name = pl.col("station_name") == pl.col("kliima_station_id").replace_strict(
        name, default=None
    )
    return (
        pl.when(pl.col("kliima_station_id").is_not_null() & (same_wmo | same_name))
        .then(pl.col("kliima_station_id"))
        .otherwise(pl.col("station_id"))
    )


def load_truth_t1(data_root: Path, climate: pl.DataFrame | None = None) -> pl.DataFrame:
    """Hourly T1 truth from XML snapshots: climate stations and XML-only stations.

    ``climate`` (columns ``station_id``, ``name``, ``wmo_code``) links XML rows to the
    verified climate stations; without it every row keeps its XML station id.
    """
    x = _read_days(data_root, "obs_xml")
    if x.is_empty():
        return x
    lo, hi = XML_LAG_MIN
    if climate is not None and climate.height:
        sid = link_climate_station(climate)
    else:
        sid = pl.col("station_id")
    x = (
        x.with_columns(sid.alias("_sid"))
        .with_columns(
            pl.col("snapshot_time_utc").dt.truncate("1h").alias("valid_time_utc"),
            (
                (
                    pl.col("snapshot_time_utc") - pl.col("snapshot_time_utc").dt.truncate("1h")
                ).dt.total_minutes()
            )
            .cast(pl.Int16)
            .alias("obs_lag_min"),
        )
        .filter(pl.col("obs_lag_min").is_between(lo, hi, closed="left"))
        .sort("snapshot_time_utc")
        .unique(["_sid", "valid_time_utc"], keep="first")
    )
    out = x.select(
        pl.col("_sid").alias("station_id"),
        "valid_time_utc",
        pl.col("airtemperature_degC").alias("obs_t2m_degC"),
        pl.col("windspeed_m_s").alias("obs_wind_speed_m_s"),
        pl.col("winddirection_deg").alias("obs_wind_dir_deg"),
        pl.lit(None, dtype=pl.Float64).alias("obs_mslp_hPa"),
        pl.col("precipitations_1h_mm").alias("obs_precip_1h_mm"),
        pl.col("provenance").alias("obs_provenance"),
        pl.col("source").alias("obs_source"),
        pl.lit("T1").alias("truth_level"),
        "obs_lag_min",
    )
    return apply_qc(out)


def apply_qc(obs: pl.DataFrame) -> pl.DataFrame:
    """Null out values outside plausibility limits and set ``qc_flags`` bits."""
    flags = pl.lit(0, dtype=pl.Int16)
    exprs = []
    for col, (lo, hi) in QC_LIMITS.items():
        bad = pl.col(col).is_not_null() & ~pl.col(col).is_between(lo, hi)
        flags = flags + pl.when(bad).then(QC_BIT[col]).otherwise(0).cast(pl.Int16)
        exprs.append(pl.when(bad).then(None).otherwise(pl.col(col)).alias(col))
    return obs.with_columns(flags.alias("qc_flags")).with_columns(exprs)


FC_COLUMNS: Final = (
    pl.col("t2m_hcorr_degC").alias("fc_t2m_degC"),
    pl.col("t2m_degC").alias("fc_t2m_raw_degC"),
    pl.col("wind10m_speed_m_s").alias("fc_wind_speed_m_s"),
    pl.col("wind10m_dir_deg").alias("fc_wind_dir_deg"),
    pl.col("mslp_hPa").alias("fc_mslp_hPa"),
)


def persistence(forecasts: pl.DataFrame, truth: pl.DataFrame) -> pl.DataFrame:
    """Build persistence reference rows on the IFS run/lead grid (see module docstring)."""
    if forecasts.is_empty() or truth.is_empty():
        return pl.DataFrame()
    grid = (
        forecasts.filter(pl.col("model_id") == "ifs", pl.col("interp_method") == PRIMARY_METHOD)
        .select("issue_time_utc", "valid_time_utc", "lead_h", "station_id")
        .unique()
        .with_columns(
            (
                pl.col("valid_time_utc")
                - pl.duration(hours=24 * ((pl.col("lead_h").cast(pl.Int32) + 23) // 24).clip(1))
            ).alias("_src_time")
        )
    )
    obs = truth.select(
        "station_id",
        pl.col("valid_time_utc").alias("_src_time"),
        "truth_level",
        pl.col("obs_t2m_degC").alias("fc_t2m_degC"),
        pl.col("obs_t2m_degC").alias("fc_t2m_raw_degC"),
        pl.col("obs_wind_speed_m_s").alias("fc_wind_speed_m_s"),
        pl.col("obs_wind_dir_deg").alias("fc_wind_dir_deg"),
        pl.col("obs_mslp_hPa").alias("fc_mslp_hPa"),
    )
    return (
        grid.join(obs, on=["station_id", "_src_time"], how="inner")
        .drop("_src_time")
        .with_columns(
            pl.lit("persistence").alias("model_id"),
            pl.lit("obs").alias("model_cycle"),
            pl.lit(PRIMARY_METHOD).alias("interp_method"),
        )
    )


def build_hourly_pairs(forecasts: pl.DataFrame, truths: list[pl.DataFrame]) -> pl.DataFrame:
    """Join forecasts with every truth level on (station, valid time)."""
    truths = [t for t in truths if not t.is_empty()]
    if forecasts.is_empty() or not truths:
        return pl.DataFrame()
    truth = pl.concat(truths, how="vertical_relaxed")
    fc = forecasts.filter(pl.col("interp_method").is_in(METHODS)).select(
        "model_id",
        "model_cycle",
        "issue_time_utc",
        "valid_time_utc",
        "lead_h",
        "station_id",
        "interp_method",
        *FC_COLUMNS,
        "grid_lsm_frac",
        "grid_dist_km",
    )
    model_pairs = fc.join(truth, on=["station_id", "valid_time_utc"], how="inner")
    pers_parts = []
    for level in truth["truth_level"].unique().to_list():
        t_level = truth.filter(pl.col("truth_level") == level)
        p = persistence(forecasts, t_level)
        if not p.is_empty():
            pers_parts.append(
                p.join(
                    t_level.drop("truth_level"), on=["station_id", "valid_time_utc"], how="inner"
                )
            )
    out = pl.concat([model_pairs, *pers_parts], how="diagonal_relaxed")
    return out.with_columns(pl.col("lead_h").cast(pl.Int16)).sort(list(HOURLY_KEYS))


def obs_precip24(truth_t2: pl.DataFrame) -> pl.DataFrame:
    """24 h sums ending 00 and 06 UTC from PR1H; only days with all 24 hourly values."""
    if truth_t2.is_empty():
        return pl.DataFrame()
    parts = []
    for end_hour in (0, 6):
        p = (
            truth_t2.select("station_id", "valid_time_utc", "obs_precip_1h_mm")
            .filter(pl.col("obs_precip_1h_mm").is_not_null())
            .with_columns(
                # Hour h belongs to the window ending at the next end_hour >= h (h > start).
                (pl.col("valid_time_utc") - pl.duration(hours=end_hour + 1))
                .dt.truncate("1d")
                .alias("_d")
            )
            .with_columns((pl.col("_d") + pl.duration(hours=24 + end_hour)).alias("window_end_utc"))
            .group_by("station_id", "window_end_utc")
            .agg(pl.len().alias("_n"), pl.col("obs_precip_1h_mm").sum().alias("obs_precip_24h_mm"))
            .filter(pl.col("_n") == 24)
            .drop("_n")
            .with_columns(pl.lit(f"{end_hour:02d}-{end_hour:02d}").alias("window"))
        )
        parts.append(p)
    return pl.concat(parts)


def fc_precip24(forecasts: pl.DataFrame) -> pl.DataFrame:
    """Forecast 24 h sums = acc(lead) - acc(lead - 24) with the ADR-005 bound."""
    base = forecasts.filter(pl.col("interp_method").is_in(METHODS)).select(
        "model_id",
        "model_cycle",
        "issue_time_utc",
        "valid_time_utc",
        "lead_h",
        "station_id",
        "interp_method",
        "precip_acc_mm",
        "precip_acc_quantum_mm",
    )
    prev = base.select(
        "model_id",
        "issue_time_utc",
        "station_id",
        "interp_method",
        (pl.col("lead_h") + 24).alias("lead_h"),
        pl.col("precip_acc_mm").alias("_acc0"),
        pl.col("precip_acc_quantum_mm").alias("_q0"),
    )
    joined = base.with_columns(pl.col("lead_h").cast(pl.Int32)).join(
        prev.with_columns(pl.col("lead_h").cast(pl.Int32)),
        on=["model_id", "issue_time_utc", "station_id", "interp_method", "lead_h"],
        how="inner",
    )
    diff = pl.col("precip_acc_mm") - pl.col("_acc0")
    bound = (pl.col("precip_acc_quantum_mm") + pl.col("_q0")) / 2.0
    return joined.with_columns(
        bound.alias("fc_bound_mm"),
        diff.clip(lower_bound=0.0).alias("fc_precip_24h_mm"),
        (diff < 0).alias("clipped_to_zero"),
        (diff < -bound).alias("decreasing_beyond_bound"),
    ).select(
        "model_id",
        "model_cycle",
        "issue_time_utc",
        pl.col("valid_time_utc").alias("window_end_utc"),
        pl.col("lead_h").cast(pl.Int16),
        "station_id",
        "interp_method",
        "fc_precip_24h_mm",
        "fc_bound_mm",
        "clipped_to_zero",
        "decreasing_beyond_bound",
    )


def build_precip_pairs(forecasts: pl.DataFrame, truth_t2: pl.DataFrame) -> pl.DataFrame:
    """Pairs of 24 h precipitation (T2 only: XML hourly sums are snapshots with gaps)."""
    obs = obs_precip24(truth_t2)
    if forecasts.is_empty() or obs.is_empty():
        return pl.DataFrame()
    fc = fc_precip24(forecasts)
    bad = fc.filter(pl.col("decreasing_beyond_bound")).height
    if bad:
        LOG.warning("%d forecast 24 h sums decrease beyond the packing bound (excluded)", bad)
    return (
        fc.filter(~pl.col("decreasing_beyond_bound"))
        .join(obs, on=["station_id", "window_end_utc"], how="inner")
        .with_columns(
            pl.lit("T2").alias("truth_level"),
            pl.lit("kvaliteedikontrollitud").alias("obs_provenance"),
        )
        .sort(["model_id", "issue_time_utc", "lead_h", "station_id", "interp_method", "window"])
    )


def climate_table(stations: Sequence[Station]) -> pl.DataFrame:
    """Return the verified climate stations as (station_id, name, wmo_code)."""
    return pl.DataFrame(
        [
            {"station_id": s.station_id, "name": s.name, "wmo_code": s.wmo_code}
            for s in stations
            if s.verified
        ],
        schema={"station_id": pl.String, "name": pl.String, "wmo_code": pl.String},
    )


def run_pair(data_root: Path, stations: Sequence[Station] = ()) -> PairResult:
    """Recompute all pairs from the archive (idempotent)."""
    climate = climate_table(stations)
    forecasts = load_forecasts(data_root)
    t2 = load_truth_t2(data_root)
    t1 = load_truth_t1(data_root, climate)
    hourly = build_hourly_pairs(forecasts, [t2, t1])
    if hourly.height:
        hourly = hourly.with_columns(
            pl.when(pl.col("station_id").is_in(climate["station_id"].implode()))
            .then(pl.lit("kliima"))
            .otherwise(pl.lit("xml"))
            .alias("station_class")
        )
    precip = build_precip_pairs(forecasts, t2)
    out = derived_dir(data_root)
    hp, pp = out / "pairs_hourly.parquet", out / "pairs_precip24.parquet"
    write_parquet_atomic(hourly, hp)
    write_parquet_atomic(precip, pp)
    runs = forecasts.select("model_id", "issue_time_utc").n_unique() if forecasts.height else 0
    LOG.info("pairs: %d hourly, %d precip24 from %d runs", hourly.height, precip.height, runs)
    return PairResult(hp, pp, hourly.height, precip.height, runs)


def lead_bucket(lead_h: pl.Expr) -> pl.Expr:
    """Lead-time bucket label used on the map (D1 = (0, 24] h, ...)."""
    return (
        pl.when(lead_h == 0)
        .then(pl.lit("0"))
        .when(lead_h <= 24)
        .then(pl.lit("D1"))
        .when(lead_h <= 48)
        .then(pl.lit("D2"))
        .when(lead_h <= 72)
        .then(pl.lit("D3"))
        .when(lead_h <= 120)
        .then(pl.lit("D4-5"))
        .when(lead_h <= 240)
        .then(pl.lit("D6-10"))
        .otherwise(pl.lit("D11-15"))
    )


LEAD_BUCKETS: Final = ("D1", "D2", "D3", "D4-5", "D6-10", "D11-15")
