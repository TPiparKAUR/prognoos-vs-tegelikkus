"""Scores from pairs (stage E3, ``pvt score``).

Output tables in ``data/derived`` (all recomputable with one command, docs/06 §4 item 2):

* ``scores_lead.parquet``    model x variable x truth x method x sample x lead_h
* ``scores_bucket.parquet``  same per lead bucket (D1 ...), with block-bootstrap CI of MAE
  and MAE skill score against persistence
* ``scores_station.parquet`` per station and lead bucket (map)
* ``scores_diff.parquet``    IFS - AIFS paired MAE difference per bucket with bootstrap CI
* ``scores_precip.parquet``  24 h precipitation: ME/MAE and contingency per threshold
  (ADR-005: yes / no / uncertain; scores on certain cases only)

``sample = "common"`` keeps only (run, lead, station, method, truth, variable) keys where
IFS, AIFS Single and persistence all have a value (docs/01 §2: fair comparison);
``sample = "all"`` uses every pair of a model. Unverified stations never reach this stage.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import polars as pl

from pvt.pair import LEAD_BUCKETS, METHODS, derived_dir, lead_bucket
from pvt.storage import write_parquet_atomic
from pvt.verify.bootstrap import moving_block_ci
from pvt.verify.categorical import Contingency

LOG = logging.getLogger(__name__)

MODELS: Final = ("ifs", "aifs-single")
REFERENCE: Final = "persistence"
WIND_DIR_MIN_SPEED_M_S: Final = 2.0  # docs/01 §4 (work decision, not from a source)
PRECIP_THRESHOLDS_MM: Final = (0.2, 1.0, 5.0, 10.0, 20.0)  # ADR-005
MIN_DAYS_FOR_CI: Final = 10
N_BOOT: Final = 1000

KEYS: Final = ("issue_time_utc", "lead_h", "station_id", "interp_method", "truth_level")
GROUP: Final = ("model_id", "variable", "truth_level", "interp_method", "sample", "network")
# network: "kliima" = verified climate stations; "koik" = all stations incl. XML (ADR-019)


@dataclass(frozen=True)
class Variable:
    """A scored variable: forecast/observation columns and unit."""

    key: str
    fc: str
    obs: str
    unit: str
    kind: str  # "linear" | "circular" | "vector"


VARIABLES: Final = (
    Variable("t2m", "fc_t2m_degC", "obs_t2m_degC", "degC", "linear"),
    Variable("t2m_nocorr", "fc_t2m_raw_degC", "obs_t2m_degC", "degC", "linear"),
    Variable("wind_speed", "fc_wind_speed_m_s", "obs_wind_speed_m_s", "m_s", "linear"),
    Variable("wind_dir", "fc_wind_dir_deg", "obs_wind_dir_deg", "deg", "circular"),
    Variable("wind_vec", "fc_wind_speed_m_s", "obs_wind_speed_m_s", "m_s", "vector"),
    Variable("mslp", "fc_mslp_hPa", "obs_mslp_hPa", "hPa", "linear"),
)


def _uv(speed: str, direction: str) -> tuple[pl.Expr, pl.Expr]:
    rad = pl.col(direction).radians()
    return -pl.col(speed) * rad.sin(), -pl.col(speed) * rad.cos()


def long_errors(pairs: pl.DataFrame) -> pl.DataFrame:
    """One row per pair and variable with ``f``, ``o``, ``err``, ``abs_err``, ``sq_err``."""
    if "station_class" not in pairs.columns:
        pairs = pairs.with_columns(pl.lit("kliima").alias("station_class"))
    base = [
        "model_id",
        *KEYS,
        "valid_time_utc",
        "station_class",
    ]
    persist = pairs.filter(pl.col("model_id") == REFERENCE)
    # Persistence does not depend on the interpolation method: replicate it per method.
    persist = pl.concat([persist.with_columns(pl.lit(m).alias("interp_method")) for m in METHODS])
    pairs = pl.concat([pairs.filter(pl.col("model_id") != REFERENCE), persist])
    parts = []
    for v in VARIABLES:
        if v.kind == "linear":
            err = pl.col(v.fc) - pl.col(v.obs)
            sel = pairs.select(
                *base,
                pl.col(v.fc).alias("f"),
                pl.col(v.obs).alias("o"),
                err.alias("err"),
            ).with_columns(
                pl.col("err").abs().alias("abs_err"), pl.col("err").pow(2).alias("sq_err")
            )
        elif v.kind == "circular":
            calm = (pl.col("fc_wind_speed_m_s") >= WIND_DIR_MIN_SPEED_M_S) & (
                pl.col("obs_wind_speed_m_s") >= WIND_DIR_MIN_SPEED_M_S
            )
            d = ((pl.col(v.fc) - pl.col(v.obs) + 180.0) % 360.0) - 180.0
            sel = (
                pairs.filter(calm)
                .select(*base, pl.col(v.fc).alias("f"), pl.col(v.obs).alias("o"), d.alias("err"))
                .with_columns(
                    pl.col("err").abs().alias("abs_err"), pl.col("err").pow(2).alias("sq_err")
                )
            )
        else:
            fu, fv = _uv("fc_wind_speed_m_s", "fc_wind_dir_deg")
            ou, ov = _uv("obs_wind_speed_m_s", "obs_wind_dir_deg")
            sq = (fu - ou).pow(2) + (fv - ov).pow(2)
            sel = pairs.select(
                *base,
                pl.lit(None, dtype=pl.Float64).alias("f"),
                pl.lit(None, dtype=pl.Float64).alias("o"),
                pl.lit(None, dtype=pl.Float64).alias("err"),
                sq.sqrt().alias("abs_err"),
                sq.alias("sq_err"),
            )
        parts.append(
            sel.filter(pl.col("sq_err").is_not_null() & pl.col("sq_err").is_finite()).with_columns(
                pl.lit(v.key).alias("variable"), pl.lit(v.unit).alias("unit")
            )
        )
    return pl.concat(parts, how="vertical_relaxed")


def with_samples(long: pl.DataFrame) -> pl.DataFrame:
    """Duplicate rows into ``sample = all`` and the fair ``sample = common`` subset."""
    need = (*MODELS, REFERENCE)
    common_keys = (
        long.filter(pl.col("model_id").is_in(need))
        .group_by([*KEYS, "variable"])
        .agg(pl.col("model_id").n_unique().alias("_m"))
        .filter(pl.col("_m") == len(need))
        .drop("_m")
    )
    common = long.join(common_keys, on=[*KEYS, "variable"], how="semi")
    sampled = pl.concat(
        [
            long.with_columns(pl.lit("all").alias("sample")),
            common.with_columns(pl.lit("common").alias("sample")),
        ]
    )
    return pl.concat(
        [
            sampled.filter(pl.col("station_class") == "kliima").with_columns(
                pl.lit("kliima").alias("network")
            ),
            sampled.with_columns(pl.lit("koik").alias("network")),
        ]
    )


def _agg() -> list[pl.Expr]:
    # wind_vec rows carry null err/f/o, so ME and correlation come out null for it.
    return [
        pl.len().alias("n"),
        pl.col("valid_time_utc").dt.date().n_unique().alias("n_days"),
        pl.col("station_id").n_unique().alias("n_stations"),
        pl.col("err").mean().alias("me"),
        pl.col("abs_err").mean().alias("mae"),
        pl.col("sq_err").mean().sqrt().alias("rmse"),
        pl.corr("f", "o").alias("corr"),
        pl.col("unit").first(),
    ]


def scores_by_lead(long: pl.DataFrame) -> pl.DataFrame:
    return long.group_by([*GROUP, "lead_h"]).agg(_agg()).sort([*GROUP, "lead_h"])


def scores_by_station(long: pl.DataFrame) -> pl.DataFrame:
    """Per-station scores (network "koik" holds every station once)."""
    return (
        long.filter(pl.col("network") == "koik")
        .with_columns(lead_bucket(pl.col("lead_h")).alias("lead_bucket"))
        .filter(pl.col("lead_bucket") != "0")
        .group_by([*GROUP, "station_id", "lead_bucket"])
        .agg(_agg())
        .sort([*GROUP, "station_id", "lead_bucket"])
    )


def _bucket_days(lead_bucket_label: str) -> int:
    upper = {"D1": 1, "D2": 2, "D3": 3, "D4-5": 5, "D6-10": 10, "D11-15": 15}
    return upper.get(lead_bucket_label, 1)


def _per_day(frame: pl.DataFrame, col: str) -> list[np.ndarray]:
    """Values of ``col`` per consecutive valid day (gaps as empty arrays)."""
    days = frame.with_columns(pl.col("valid_time_utc").dt.date().alias("_d"))
    if days.is_empty():
        return []
    groups: dict[dt.date, np.ndarray] = {k[0]: g[col].to_numpy() for k, g in days.group_by("_d")}
    first, last = min(groups), max(groups)
    n = (last - first).days + 1
    return [groups.get(first + dt.timedelta(days=i), np.empty(0)) for i in range(n)]


def scores_by_bucket(long: pl.DataFrame) -> pl.DataFrame:
    """Bucket scores with bootstrap CI (primary truth sets) and skill vs persistence."""
    lb = long.with_columns(lead_bucket(pl.col("lead_h")).alias("lead_bucket")).filter(
        pl.col("lead_bucket") != "0"
    )
    table = lb.group_by([*GROUP, "lead_bucket"]).agg(_agg())
    ref = table.filter(pl.col("model_id") == REFERENCE).select(
        *[c for c in GROUP if c != "model_id"],
        "lead_bucket",
        pl.col("mae").alias("_mae_ref"),
        pl.col("rmse").alias("_rmse_ref"),
    )
    table = (
        table.join(ref, on=[*[c for c in GROUP if c != "model_id"], "lead_bucket"], how="left")
        .with_columns(
            (1.0 - pl.col("mae") / pl.col("_mae_ref")).alias("ss_mae_persistence"),
            (1.0 - pl.col("rmse").pow(2) / pl.col("_rmse_ref").pow(2)).alias("ss_mse_persistence"),
        )
        .drop("_mae_ref", "_rmse_ref")
    )
    # Block-bootstrap CI for MAE: only when enough valid days exist (docs/01 §7).
    ci_rows = []
    for key, g in lb.group_by([*GROUP, "lead_bucket"]):
        per_day = _per_day(g, "abs_err")
        block = max(7, _bucket_days(str(key[-1])) + 1)
        lo = hi = float("nan")
        if len(per_day) >= max(MIN_DAYS_FOR_CI, 2 * block):
            lo, hi = moving_block_ci(per_day, lambda a: float(np.mean(a)), block, n_boot=N_BOOT)
        ci_rows.append((*key, lo, hi))
    ci = pl.DataFrame(
        ci_rows,
        schema=[*GROUP, "lead_bucket", "mae_ci_low", "mae_ci_high"],
        orient="row",
    )
    return table.join(ci, on=[*GROUP, "lead_bucket"], how="left").sort([*GROUP, "lead_bucket"])


def scores_diff(long: pl.DataFrame) -> pl.DataFrame:
    """Paired MAE difference IFS - AIFS on the common sample, per bucket, with CI."""
    c = long.filter(pl.col("sample") == "common", pl.col("model_id").is_in(MODELS))
    if c.is_empty():
        return pl.DataFrame()
    wide = (
        c.select(*KEYS, "variable", "network", "valid_time_utc", "model_id", "abs_err")
        .pivot(
            on="model_id",
            index=[*KEYS, "variable", "network", "valid_time_utc"],
            values="abs_err",
        )
        .drop_nulls(list(MODELS))
        .with_columns(
            (pl.col(MODELS[0]) - pl.col(MODELS[1])).alias("d"),
            lead_bucket(pl.col("lead_h")).alias("lead_bucket"),
        )
        .filter(pl.col("lead_bucket") != "0")
    )
    rows = []
    for key, g in wide.group_by(
        ["variable", "truth_level", "interp_method", "network", "lead_bucket"]
    ):
        per_day = _per_day(g, "d")
        block = max(7, _bucket_days(str(key[-1])) + 1)
        lo = hi = float("nan")
        if len(per_day) >= max(MIN_DAYS_FOR_CI, 2 * block):
            lo, hi = moving_block_ci(per_day, lambda a: float(np.mean(a)), block, n_boot=N_BOOT)
        mae_a = float(g[MODELS[0]].mean())  # type: ignore[arg-type]
        mae_b = float(g[MODELS[1]].mean())  # type: ignore[arg-type]
        rows.append(
            {
                "variable": key[0],
                "truth_level": key[1],
                "interp_method": key[2],
                "network": key[3],
                "lead_bucket": key[4],
                "n": g.height,
                "n_days": len([d for d in per_day if d.size]),
                "mae_ifs": mae_a,
                "mae_aifs": mae_b,
                "diff_mae": mae_a - mae_b,
                "rel_diff": (mae_a - mae_b) / mae_b if mae_b else float("nan"),
                "diff_ci_low": lo,
                "diff_ci_high": hi,
                "significant": bool(np.isfinite(lo) and (lo > 0 or hi < 0)),
            }
        )
    return pl.DataFrame(rows).sort(
        ["variable", "truth_level", "interp_method", "network", "lead_bucket"]
    )


def classify(fc_mm: float, bound_mm: float, threshold: float) -> str:
    """ADR-005: 'yes' if lower bound >= threshold, 'no' if upper bound < threshold."""
    if fc_mm - bound_mm >= threshold:
        return "yes"
    if fc_mm + bound_mm < threshold:
        return "no"
    return "uncertain"


def scores_precip(pp: pl.DataFrame) -> pl.DataFrame:
    """ME/MAE and contingency scores of 24 h precipitation per model/method/window/bucket."""
    if pp.is_empty():
        return pl.DataFrame()
    pp = pp.with_columns(lead_bucket(pl.col("lead_h")).alias("lead_bucket"))
    rows = []
    for key, g in pp.group_by(["model_id", "interp_method", "window", "lead_bucket"]):
        f = g["fc_precip_24h_mm"].to_numpy()
        o = g["obs_precip_24h_mm"].to_numpy()
        q = g["fc_bound_mm"].to_numpy()
        base = {
            "model_id": key[0],
            "interp_method": key[1],
            "window": key[2],
            "lead_bucket": key[3],
            "n": g.height,
            "me": float(np.mean(f - o)),
            "mae": float(np.mean(np.abs(f - o))),
            "n_clipped": int(g["clipped_to_zero"].sum()),
        }
        for thr in PRECIP_THRESHOLDS_MM:
            cls = [classify(fi, qi, thr) for fi, qi in zip(f, q, strict=True)]
            obs_yes = o >= thr
            a = sum(1 for c, y in zip(cls, obs_yes, strict=True) if c == "yes" and y)
            b = sum(1 for c, y in zip(cls, obs_yes, strict=True) if c == "yes" and not y)
            cc = sum(1 for c, y in zip(cls, obs_yes, strict=True) if c == "no" and y)
            d = sum(1 for c, y in zip(cls, obs_yes, strict=True) if c == "no" and not y)
            table = Contingency(a, b, cc, d)
            rows.append(
                {
                    **base,
                    "threshold_mm": thr,
                    "a": a,
                    "b": b,
                    "c": cc,
                    "d": d,
                    "n_uncertain": sum(1 for c in cls if c == "uncertain"),
                    "n_obs_events": int(obs_yes.sum()),
                    **table.scores(),
                }
            )
    return pl.DataFrame(rows).sort(
        ["model_id", "interp_method", "window", "lead_bucket", "threshold_mm"]
    )


@dataclass(frozen=True)
class ScoreResult:
    """Row counts of one ``pvt score`` invocation."""

    n_lead: int
    n_bucket: int
    n_station: int
    n_diff: int
    n_precip: int


def run_score(data_root: Path) -> ScoreResult:
    """Compute all score tables from the pair files (idempotent)."""
    out = derived_dir(data_root)
    hourly = pl.read_parquet(out / "pairs_hourly.parquet")
    precip = pl.read_parquet(out / "pairs_precip24.parquet")
    if hourly.is_empty():
        empty = pl.DataFrame()
        for name in ("lead", "bucket", "station", "diff", "precip"):
            write_parquet_atomic(empty, out / f"scores_{name}.parquet")
        return ScoreResult(0, 0, 0, 0, 0)
    long = with_samples(long_errors(hourly))
    tables = {
        "lead": scores_by_lead(long),
        "bucket": scores_by_bucket(long),
        "station": scores_by_station(long),
        "diff": scores_diff(long),
        "precip": scores_precip(precip),
    }
    for name, df in tables.items():
        write_parquet_atomic(df, out / f"scores_{name}.parquet")
    LOG.info("scores: %s", {k: v.height for k, v in tables.items()})
    return ScoreResult(*(tables[k].height for k in ("lead", "bucket", "station", "diff", "precip")))


__all__ = ["LEAD_BUCKETS", "run_score"]
