"""Table schemas (schema_version 1.0.0) and validation.

Units are part of column names. All datetimes are ``Datetime("us", "UTC")``.
``forecast_point``, ``obs``, ``station`` and ``score`` follow docs/03 section 3.
``forecast_grid`` and ``forecast_grid_static`` are the regional sub-grid archive
(ADR-015, proposal): the raw input from which ``forecast_point`` is derived.
"""

from __future__ import annotations

from typing import Final

import polars as pl

from pvt import SCHEMA_VERSION

UTC_TS: Final = pl.Datetime("us", "UTC")

PROVENANCE_VALUES: Final = frozenset(
    {
        "toormõõtmine",
        "kvaliteedikontrollitud",
        "lünki_täidetud",
        "homogeniseeritud",
        "mudeli_analüüs",
        "reanalüüs",
        "prognoos",
        "tuletatud_indeks",
    }
)

FORECAST_GRID: Final[dict[str, pl.DataType]] = {
    "model_id": pl.String(),
    "model_cycle": pl.String(),
    "grib_gen_proc_id": pl.Int16(),
    "issue_time_utc": UTC_TS,
    "valid_time_utc": UTC_TS,
    "lead_h": pl.Int16(),
    "member": pl.Int16(),
    "grid_lat_deg": pl.Float64(),
    "grid_lon_deg": pl.Float64(),
    "t2m_degC": pl.Float64(),
    "u10_m_s": pl.Float64(),
    "v10_m_s": pl.Float64(),
    "mslp_hPa": pl.Float64(),
    "precip_acc_mm": pl.Float64(),
    "precip_acc_start_h": pl.Int16(),
    "provenance": pl.String(),
    "source_uri": pl.String(),
    "ingest_version": pl.String(),
    "schema_version": pl.String(),
}
FORECAST_GRID_KEY: Final = (
    "model_id",
    "issue_time_utc",
    "lead_h",
    "member",
    "grid_lat_deg",
    "grid_lon_deg",
)

FORECAST_GRID_STATIC: Final[dict[str, pl.DataType]] = {
    "model_id": pl.String(),
    "model_cycle": pl.String(),
    "issue_time_utc": UTC_TS,
    "grid_lat_deg": pl.Float64(),
    "grid_lon_deg": pl.Float64(),
    "grid_orog_m": pl.Float64(),
    "grid_lsm_frac": pl.Float64(),
    "provenance": pl.String(),
    "source_uri": pl.String(),
    "ingest_version": pl.String(),
    "schema_version": pl.String(),
}
FORECAST_GRID_STATIC_KEY: Final = ("model_id", "issue_time_utc", "grid_lat_deg", "grid_lon_deg")

# docs/03 section 3 -- used from stage E2 on.
FORECAST_POINT: Final[dict[str, pl.DataType]] = {
    "model_id": pl.String(),
    "model_cycle": pl.String(),
    "issue_time_utc": UTC_TS,
    "valid_time_utc": UTC_TS,
    "lead_h": pl.Int16(),
    "station_id": pl.String(),
    "member": pl.Int16(),
    "t2m_degC": pl.Float64(),
    "t2m_hcorr_degC": pl.Float64(),
    "u10_m_s": pl.Float64(),
    "v10_m_s": pl.Float64(),
    "wind10m_speed_m_s": pl.Float64(),
    "wind10m_dir_deg": pl.Float64(),
    "mslp_hPa": pl.Float64(),
    "precip_acc_mm": pl.Float64(),
    "grid_lat_deg": pl.Float64(),
    "grid_lon_deg": pl.Float64(),
    "grid_orog_m": pl.Float64(),
    "grid_lsm_frac": pl.Float64(),
    "interp_method": pl.String(),
    "provenance": pl.String(),
    "source_uri": pl.String(),
    "retrieved_at_utc": UTC_TS,
    "ingest_version": pl.String(),
    "schema_version": pl.String(),
}


class SchemaError(ValueError):
    """Raised when a frame does not match its declared schema."""


def validate(
    df: pl.DataFrame,
    schema: dict[str, pl.DataType],
    key: tuple[str, ...] = (),
) -> None:
    """Validate column names/order, dtypes, provenance, key uniqueness and lead time.

    Parameters
    ----------
    df : polars.DataFrame
        Frame to check.
    schema : dict
        Ordered mapping of column name to dtype.
    key : tuple of str
        Columns that must be unique together (no duplicate keys).

    Raises
    ------
    SchemaError
        On the first violation found.
    """
    if list(df.columns) != list(schema):
        raise SchemaError(f"columns {df.columns} != expected {list(schema)}")
    for name, dtype in schema.items():
        if df.schema[name] != dtype:
            raise SchemaError(f"column {name}: dtype {df.schema[name]} != {dtype}")
    if "schema_version" in df.columns and df.height:
        bad = df.filter(pl.col("schema_version") != SCHEMA_VERSION).height
        if bad:
            raise SchemaError(f"{bad} rows with schema_version != {SCHEMA_VERSION}")
    if "provenance" in df.columns and df.height:
        values = set(df.get_column("provenance").unique().to_list())
        if not values <= PROVENANCE_VALUES:
            raise SchemaError(f"unknown provenance values {values - PROVENANCE_VALUES}")
        if len(values) > 1:
            raise SchemaError(f"mixed provenance in one table: {sorted(values)}")
    if key and df.height:
        dupes = df.height - df.select(key).unique().height
        if dupes:
            raise SchemaError(f"{dupes} duplicate rows on key {key}")
    if {"issue_time_utc", "valid_time_utc", "lead_h"} <= set(df.columns) and df.height:
        lead = (pl.col("valid_time_utc") - pl.col("issue_time_utc")).dt.total_hours()
        mismatched = df.filter(lead != pl.col("lead_h").cast(pl.Int64)).height
        if mismatched:
            raise SchemaError(f"{mismatched} rows where lead_h != valid - issue")
