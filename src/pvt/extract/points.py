"""Station extraction from the regional sub-grid (ADR-006, ADR-015 rev. 2026-11-13).

Only the grid points needed for the stations are archived ("stencil"):

* the 4 grid points enclosing the station (bilinear interpolation, nearest grid point);
* the nearest land point (land-sea mask >= 0.5) within the surrounding 4 x 4 block.

From these, ``forecast_point`` rows are derived per station and method:

* ``bilinear`` -- weights from the station position inside the enclosing cell;
* ``nearest`` -- nearest of the 4 enclosing points (ECMWF SYNOP verification practice);
* ``nearest_land`` -- nearest land point (ADR-006 primary method).

Height correction (ADR-006, ECMWF verification standard): ``t2m_hcorr = t2m - 0.0065 K/m *
(z_station - z_model)`` with ``z_model`` the method's model orography. Raw values are kept.
Wind speed/direction are derived from interpolated u/v (meteorological "from" direction).
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
from typing import Any, Final

import numpy as np
import polars as pl

from pvt.stations import haversine_km

LAPSE_RATE_K_PER_M: Final = 0.0065
LAND_THRESHOLD: Final = 0.5
METHODS: Final = ("bilinear", "nearest", "nearest_land")

WEIGHTS_SCHEMA: dict[str, pl.DataType] = {
    "station_id": pl.String(),
    "interp_method": pl.String(),
    "grid_lat_deg": pl.Float64(),
    "grid_lon_deg": pl.Float64(),
    "weight": pl.Float64(),
    "grid_dist_km": pl.Float64(),
}


def _snap(value: float, inc: float) -> float:
    return round(round(value / inc) * inc, 6)


def build_weights(
    static: pl.DataFrame, targets: pl.DataFrame, inc: float
) -> tuple[pl.DataFrame, list[str]]:
    """Interpolation weights per station and method.

    Parameters
    ----------
    static : polars.DataFrame
        Box static fields with ``grid_lat_deg``, ``grid_lon_deg``, ``grid_lsm_frac``.
    targets : polars.DataFrame
        Stations with ``station_id``, ``lat_deg``, ``lon_deg``.
    inc : float
        Grid increment (deg).

    Returns
    -------
    tuple of (polars.DataFrame, list of str)
        Weights table (WEIGHTS_SCHEMA) and ids of stations skipped (outside the box).
    """
    pts = {
        (round(r["grid_lat_deg"], 6), round(r["grid_lon_deg"], 6)): r["grid_lsm_frac"]
        for r in static.select("grid_lat_deg", "grid_lon_deg", "grid_lsm_frac").iter_rows(
            named=True
        )
    }
    rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    for st in targets.iter_rows(named=True):
        lat, lon, sid = st["lat_deg"], st["lon_deg"], st["station_id"]
        lat0 = _snap(math.floor(lat / inc + 1e-9) * inc, inc)
        lon0 = _snap(math.floor(lon / inc + 1e-9) * inc, inc)
        lat1, lon1 = _snap(lat0 + inc, inc), _snap(lon0 + inc, inc)
        corners = [(lat0, lon0), (lat0, lon1), (lat1, lon0), (lat1, lon1)]
        if any(c not in pts for c in corners):
            skipped.append(sid)
            continue
        wy, wx = (lat - lat0) / inc, (lon - lon0) / inc
        weights = [(1 - wx) * (1 - wy), wx * (1 - wy), (1 - wx) * wy, wx * wy]
        dists = [haversine_km(lat, lon, c[0], c[1]) for c in corners]
        for c, w, d in zip(corners, weights, dists, strict=True):
            rows.append(
                {
                    "station_id": sid,
                    "interp_method": "bilinear",
                    "grid_lat_deg": c[0],
                    "grid_lon_deg": c[1],
                    "weight": w,
                    "grid_dist_km": d,
                }
            )
        k = int(np.argmin(dists))
        rows.append(
            {
                "station_id": sid,
                "interp_method": "nearest",
                "grid_lat_deg": corners[k][0],
                "grid_lon_deg": corners[k][1],
                "weight": 1.0,
                "grid_dist_km": dists[k],
            }
        )
        block = [
            (_snap(lat0 + i * inc, inc), _snap(lon0 + j * inc, inc))
            for i in (-1, 0, 1, 2)
            for j in (-1, 0, 1, 2)
        ]
        land = [
            (haversine_km(lat, lon, p[0], p[1]), p)
            for p in block
            if p in pts and pts[p] >= LAND_THRESHOLD
        ]
        if land:
            d, p = min(land)
            rows.append(
                {
                    "station_id": sid,
                    "interp_method": "nearest_land",
                    "grid_lat_deg": p[0],
                    "grid_lon_deg": p[1],
                    "weight": 1.0,
                    "grid_dist_km": d,
                }
            )
    return pl.DataFrame(rows, schema=WEIGHTS_SCHEMA), skipped


def stencil_points(weights: pl.DataFrame) -> pl.DataFrame:
    """Return the unique grid points referenced by the weights (what gets archived)."""
    return (
        weights.select("grid_lat_deg", "grid_lon_deg")
        .unique()
        .sort(["grid_lat_deg", "grid_lon_deg"], descending=[True, False])
    )


def wind_speed_dir(u: pl.Expr, v: pl.Expr) -> tuple[pl.Expr, pl.Expr]:
    """Speed (m/s) and meteorological direction the wind blows FROM (deg, 0 = north)."""
    speed = (u.pow(2) + v.pow(2)).sqrt()
    direction = (pl.arctan2(-u, -v).degrees() + 360.0) % 360.0
    return speed, direction


VALUE_COLS: Final = (
    "t2m_degC",
    "u10_m_s",
    "v10_m_s",
    "mslp_hPa",
    "precip_acc_mm",
    "precip_acc_quantum_mm",
    "gust10m_max_m_s",
)


def derive_points(
    grid: pl.DataFrame,
    static: pl.DataFrame,
    weights: pl.DataFrame,
    targets: pl.DataFrame,
) -> pl.DataFrame:
    """Station values per method from stencil grid values (columns as FORECAST_POINT).

    ``gust10m_max_m_s`` stays null when the model has no gust field.
    """
    w = weights.join(
        static.select("grid_lat_deg", "grid_lon_deg", "grid_orog_m", "grid_lsm_frac"),
        on=["grid_lat_deg", "grid_lon_deg"],
        how="left",
    )
    keys = ["model_id", "model_cycle", "issue_time_utc", "valid_time_utc", "lead_h", "member"]
    joined = grid.join(w, on=["grid_lat_deg", "grid_lon_deg"], how="inner")
    agg = [
        pl.when(pl.col(c).is_null().all())
        .then(None)
        .otherwise((pl.col(c) * pl.col("weight")).sum())
        .alias(c)
        for c in VALUE_COLS
    ]
    single = pl.col("interp_method") != "bilinear"
    out = (
        joined.group_by([*keys, "station_id", "interp_method"])
        .agg(
            *agg,
            (pl.col("grid_orog_m") * pl.col("weight")).sum().alias("grid_orog_m"),
            (pl.col("grid_lsm_frac") * pl.col("weight")).sum().alias("grid_lsm_frac"),
            pl.col("grid_lat_deg").first(),
            pl.col("grid_lon_deg").first(),
            pl.col("grid_dist_km").first(),
            pl.col("precip_acc_start_h").first(),
            pl.col("gust_window_start_h").first(),
            pl.col("grib_gen_proc_id").first(),
            pl.col("source_uri").first(),
            pl.col("provenance").first(),
            pl.col("ingest_version").first(),
            pl.col("schema_version").first(),
        )
        .with_columns(
            pl.when(single).then(pl.col("grid_lat_deg")).otherwise(None).alias("grid_lat_deg"),
            pl.when(single).then(pl.col("grid_lon_deg")).otherwise(None).alias("grid_lon_deg"),
            pl.when(single).then(pl.col("grid_dist_km")).otherwise(None).alias("grid_dist_km"),
        )
        .join(
            targets.select("station_id", "height_m_EH2000").rename(
                {"height_m_EH2000": "station_height_m_EH2000"}
            ),
            on="station_id",
            how="left",
        )
    )
    speed, direction = wind_speed_dir(pl.col("u10_m_s"), pl.col("v10_m_s"))
    return out.with_columns(
        (
            pl.col("t2m_degC")
            - LAPSE_RATE_K_PER_M * (pl.col("station_height_m_EH2000") - pl.col("grid_orog_m"))
        ).alias("t2m_hcorr_degC"),
        speed.alias("wind10m_speed_m_s"),
        direction.alias("wind10m_dir_deg"),
    )


WEIGHTS_FILE_SCHEMA: dict[str, pl.DataType] = {
    **WEIGHTS_SCHEMA,
    "station_lat_deg": pl.Float64(),
    "station_lon_deg": pl.Float64(),
    "station_height_m_EH2000": pl.Float64(),
    "station_verified": pl.Boolean(),
}


def attach_targets(weights: pl.DataFrame, targets: pl.DataFrame) -> pl.DataFrame:
    """Add the station metadata used for this run (so derivation is self-contained)."""
    t = targets.select(
        "station_id",
        pl.col("lat_deg").alias("station_lat_deg"),
        pl.col("lon_deg").alias("station_lon_deg"),
        pl.col("height_m_EH2000").alias("station_height_m_EH2000"),
        pl.col("verified").alias("station_verified"),
    )
    return (
        weights.join(t, on="station_id", how="left")
        .select(list(WEIGHTS_FILE_SCHEMA))
        .sort(["station_id", "interp_method", "grid_lat_deg", "grid_lon_deg"])
    )


def points_from_stencil(
    grid: pl.DataFrame, static: pl.DataFrame, weights_full: pl.DataFrame
) -> pl.DataFrame:
    """FORECAST_POINT rows from archived stencil grid, static fields and weights."""
    from pvt.schemas import FORECAST_POINT

    targets = weights_full.select(
        "station_id", pl.col("station_height_m_EH2000").alias("height_m_EH2000")
    ).unique()
    return (
        derive_points(grid, static, weights_full.select(list(WEIGHTS_SCHEMA)), targets)
        .select(list(FORECAST_POINT))
        .cast(FORECAST_POINT)  # type: ignore[arg-type]
        .sort(["lead_h", "station_id", "interp_method"])
    )


def load_points(data_root: Path, model_id: str, issue_time: dt.datetime) -> pl.DataFrame:
    """Derive the station values of one archived run (FORECAST_POINT layout)."""
    from pvt.storage import ecmwf_grid_path

    def read(kind: str) -> pl.DataFrame:
        return pl.read_parquet(ecmwf_grid_path(data_root, model_id, issue_time, kind))

    return points_from_stencil(read("grid"), read("static"), read("weights"))
