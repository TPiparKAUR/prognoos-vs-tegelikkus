"""Static site data (stage E4, ``pvt build-site``).

Writes pre-computed JSON for the web page (ADR-011) into ``out_dir``:

* ``meta.json``          period, runs, models, variables, attribution, data status
* ``stations.geojson``   verified stations (scored) + XML stations (latest observation only)
* ``scores_*.json``      columnar score tables (``{"col": [...], ...}``)
* ``station/<id>.json``  time series for the station panel: T2/T1 observations, the latest
  run of each model, and the 24-30 h old forecast that verified at each past hour

Every number keeps its provenance label; KAUR forecast scores are not exported (ADR-012).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
from pathlib import Path
from typing import Any, Final

import polars as pl

from pvt import SCHEMA_VERSION
from pvt.config import Settings
from pvt.pair import (
    LEAD_BUCKETS,
    METHODS,
    PRIMARY_METHOD,
    climate_table,
    derived_dir,
    link_climate_station,
    load_forecasts,
    load_truth_t1,
    load_truth_t2,
)
from pvt.provenance import ingest_version
from pvt.score import PRECIP_THRESHOLDS_MM, VARIABLES
from pvt.stations import station_targets
from pvt.storage import read_json
from pvt.timeutil import format_utc, utc_now

LOG = logging.getLogger(__name__)

SERIES_DAYS: Final = 10
TRACE_LEAD_H: Final = (24, 30)  # forecast "one day ahead" trace shown against observations

VARIABLE_LABELS: Final = {
    "t2m": ("2 m temperatuur", "°C", "kõrguskorrektsiooniga 0,0065 K/m (ADR-006)"),
    "t2m_nocorr": ("2 m temperatuur (korrektsioonita)", "°C", "mudeli toorväärtus"),
    "wind_speed": ("10 m tuule kiirus", "m/s", "vaatlus: 10 min keskmine"),
    "wind_dir": ("10 m tuule suund", "°", "ainult kui mõlemad kiirused ≥ 2 m/s"),
    "wind_vec": ("10 m tuule vektorviga", "m/s", "RMSE u/v komponentidest"),
    "mslp": ("Õhurõhk merepinnal", "hPa", "T2: PA0; T1 XML rõhku ei võrrelda"),
}
MODEL_LABELS: Final = {
    "ifs": "ECMWF IFS (0,25°)",
    "aifs-single": "ECMWF AIFS Single (0,25°)",
    "persistence": "Persistents (vaatlus 24 h tagasi)",
    "kaur_asukoht": "KAURi asukohaprognoos",
}
# Sources that are planned but not yet archived (shown as "waiting" on the page).
PENDING_MODELS: Final = {
    "kaur_asukoht": (
        "ilmmicroservice.envir.ee lükkab automaatsed päringud tagasi (ühendus suletakse "
        "vastuseta, nii arenduskeskkonnast kui GitHubist, 13.11.2026). Vajalik KAURi IT "
        "lubatud ligipääs; seejärel salvestatakse prognoos igal jooksul jaamade kohal."
    )
}
METHOD_LABELS: Final = {
    "nearest_land": "Lähim maapunkt",
    "bilinear": "Bilineaarne",
    "nearest": "Lähim ruudupunkt",
}
TRUTH_LABELS: Final = {
    "T2": "T2 - KAURi kliimaandmestik (kvaliteedikontrollitud)",
    "T1": "T1 - vaatluste XML (toormõõtmine)",
}
ATTRIBUTION: Final = [
    {
        "text": "ECMWF avaandmed (IFS, AIFS Single), CC BY 4.0. Adapted from ECMWF open data.",
        "url": "https://www.ecmwf.int/en/forecasts/datasets/open-data",
    },
    {
        "text": "Vaatlused: Keskkonnaagentuur, ilmateenistus.ee; kliimaandmestik CC BY 4.0",
        "url": "https://www.ilmateenistus.ee",
    },
    {
        "text": "Varukontuur: © OpenStreetMap contributors (ODbL)",
        "url": "https://www.openstreetmap.org/copyright",
    },
]


def _clean(value: Any) -> Any:
    if isinstance(value, float):
        return None if not math.isfinite(value) else round(value, 4)
    if isinstance(value, dt.datetime):
        return format_utc(value)
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


def columnar(df: pl.DataFrame) -> dict[str, list[Any]]:
    """``{column: [values]}`` with rounded floats, NaN -> null, UTC ISO timestamps."""
    return {c: [_clean(v) for v in df[c].to_list()] for c in df.columns}


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        encoding="utf-8",
    )


def _read_table(data_root: Path, name: str) -> pl.DataFrame:
    p = derived_dir(data_root) / f"{name}.parquet"
    return pl.read_parquet(p) if p.exists() else pl.DataFrame()


MEASURE_COLUMNS: Final = {
    "t2m": "airtemperature_degC",
    "wind": "windspeed_m_s",
    "precip": "precipitations_1h_mm",
    "pressure": "airpressure_hPa",
}


def stations_geojson(settings: Settings, latest_xml: pl.DataFrame) -> dict[str, Any]:
    """Forecast target stations as GeoJSON with the latest XML observation.

    Targets come from ``station_targets`` (verified climate stations + XML stations more
    than 1 km from them), so an XML duplicate of a climate station is not a second point.
    """
    obs_by_station: dict[str, dict[str, Any]] = {}
    if not latest_xml.is_empty():
        linked = latest_xml.with_columns(
            link_climate_station(climate_table(settings.stations)).alias("_sid")
        )
        for row in linked.iter_rows(named=True):
            sid = row["_sid"]
            if sid in obs_by_station:
                continue
            obs_by_station[sid] = {
                "time_utc": _clean(row["snapshot_time_utc"]),
                "t2m_degC": _clean(row["airtemperature_degC"]),
                "wind_speed_m_s": _clean(row["windspeed_m_s"]),
                "wind_dir_deg": _clean(row["winddirection_deg"]),
                "gust_m_s": _clean(row["windspeedmax_m_s"]),
                "precip_1h_mm": _clean(row["precipitations_1h_mm"]),
                "pressure_hPa": _clean(row["airpressure_hPa"]),
                "phenomenon": row["phenomenon"],
                "measures": [k for k, c in MEASURE_COLUMNS.items() if row[c] is not None],
                "provenance": "toormõõtmine",
            }
    wmo = {s.station_id: s.wmo_code for s in settings.stations}
    feats: list[dict[str, Any]] = []
    for row in station_targets(settings).iter_rows(named=True):
        sid = row["station_id"]
        feats.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [row["lon_deg"], row["lat_deg"]]},
                "properties": {
                    "id": sid,
                    "name": row["name"],
                    "verified": bool(row["verified"]),
                    "class": "kliima" if row["verified"] else "xml",
                    "height_m_EH2000": row["height_m_EH2000"],
                    "wmo_code": wmo.get(sid),
                    "latest_obs": obs_by_station.get(sid),
                },
            }
        )
    return {"type": "FeatureCollection", "features": feats}


def _latest_xml(data_root: Path) -> pl.DataFrame:
    files = sorted((data_root / "obs_xml").glob("*/*/*/*.parquet"))
    if not files:
        return pl.DataFrame()
    x = pl.read_parquet(files[-1])
    if x.is_empty():
        return x
    return x.filter(pl.col("snapshot_time_utc") == pl.col("snapshot_time_utc").max())


def station_series(
    forecasts: pl.DataFrame, t2: pl.DataFrame, t1: pl.DataFrame, now: dt.datetime
) -> dict[str, dict[str, Any]]:
    """Per-station series for the detail panel (primary interpolation method)."""
    start = now - dt.timedelta(days=SERIES_DAYS)
    out: dict[str, dict[str, Any]] = {}
    fc = (
        forecasts.filter(pl.col("interp_method") == PRIMARY_METHOD)
        if forecasts.height
        else forecasts
    )
    fc_cols: list[str | pl.Expr] = [
        "valid_time_utc",
        # Height-corrected where the station height is known, else the raw model value
        # (XML stations, ADR-019); the page labels which one is shown.
        pl.coalesce("t2m_hcorr_degC", "t2m_degC").alias("t2m_degC"),
        pl.col("wind10m_speed_m_s").alias("wind_speed_m_s"),
        pl.col("wind10m_dir_deg").alias("wind_dir_deg"),
        "mslp_hPa",
        "precip_acc_mm",
    ]
    latest: dict[str, pl.DataFrame] = {}
    trace: dict[str, pl.DataFrame] = {}
    if fc.height:
        for model in fc["model_id"].unique().to_list():
            m = fc.filter(pl.col("model_id") == model)
            last_issue = m["issue_time_utc"].max()
            latest[model] = m.filter(pl.col("issue_time_utc") == last_issue)
            lo, hi = TRACE_LEAD_H
            trace[model] = (
                m.filter(pl.col("lead_h").is_between(lo, hi, closed="left"))
                .filter(pl.col("valid_time_utc") >= start)
                .sort("issue_time_utc")
                .unique(["station_id", "valid_time_utc"], keep="last")
            )
    station_ids = set(t2["station_id"].unique().to_list()) if t2.height else set()
    if fc.height:
        station_ids |= set(fc["station_id"].unique().to_list())
    obs_cols = [
        "valid_time_utc",
        pl.col("obs_t2m_degC").alias("t2m_degC"),
        pl.col("obs_wind_speed_m_s").alias("wind_speed_m_s"),
        pl.col("obs_wind_dir_deg").alias("wind_dir_deg"),
        pl.col("obs_mslp_hPa").alias("mslp_hPa"),
        pl.col("obs_precip_1h_mm").alias("precip_1h_mm"),
    ]
    for sid in sorted(station_ids):
        entry: dict[str, Any] = {"station_id": sid, "obs": {}, "latest_run": {}, "trace_24h": {}}
        for level, t in (("T2", t2), ("T1", t1)):
            if t.height:
                s = (
                    t.filter(pl.col("station_id") == sid, pl.col("valid_time_utc") >= start)
                    .sort("valid_time_utc")
                    .select(obs_cols)
                )
                if s.height:
                    entry["obs"][level] = columnar(s)
        for model, df in latest.items():
            s = df.filter(pl.col("station_id") == sid).sort("valid_time_utc")
            if s.height:
                entry["latest_run"][model] = {
                    "issue_time_utc": _clean(s["issue_time_utc"][0]),
                    "model_cycle": s["model_cycle"][0],
                    **columnar(s.select(fc_cols)),
                }
        for model, df in trace.items():
            s = df.filter(pl.col("station_id") == sid).sort("valid_time_utc")
            if s.height:
                entry["trace_24h"][model] = columnar(
                    s.select("valid_time_utc", "lead_h", *fc_cols[1:5])
                )
        out[sid] = entry
    return out


def _availability(bucket: pl.DataFrame) -> dict[str, dict[str, list[str]]]:
    """Variables with pairs per truth level and network (to disable empty choices)."""
    out: dict[str, dict[str, list[str]]] = {}
    if not bucket.height:
        return out
    have = (
        bucket.filter(pl.col("n") > 0, pl.col("sample") == "all")
        .select("truth_level", "network", "variable")
        .unique()
    )
    for row in have.iter_rows(named=True):
        out.setdefault(row["truth_level"], {}).setdefault(row["network"], []).append(
            row["variable"]
        )
    for nets in out.values():
        for v in nets.values():
            v.sort()
    return out


def _inventory_summary(inventory: Any) -> dict[str, Any] | None:
    """Per-model completeness only (the per-run list stays in status/ecmwf_inventory.json)."""
    if not isinstance(inventory, dict) or not isinstance(inventory.get("models"), dict):
        return None
    keep = ("completeness_fraction", "runs_complete", "runs_expected")
    return {
        "generated_at_utc": inventory.get("generated_at_utc"),
        "models": {m: {k: v.get(k) for k in keep} for m, v in inventory["models"].items()},
    }


def build_site(settings: Settings, out_dir: Path, now: dt.datetime | None = None) -> Path:
    """Write all site JSON files; return ``out_dir``."""
    now = now or utc_now()
    root = settings.data_root
    pairs = _read_table(root, "pairs_hourly")
    tables = {
        name: _read_table(root, f"scores_{name}")
        for name in ("lead", "bucket", "station", "diff", "precip")
    }
    forecasts = load_forecasts(root)
    t2, t1 = load_truth_t2(root), load_truth_t1(root, climate_table(settings.stations))
    latest_xml = _latest_xml(root)

    status_dir = root / "status"
    freshness = (
        read_json(status_dir / "freshness.json")
        if (status_dir / "freshness.json").exists()
        else None
    )
    inventory = (
        read_json(status_dir / "ecmwf_inventory.json")
        if (status_dir / "ecmwf_inventory.json").exists()
        else None
    )
    runs = (
        forecasts.select("model_id", "model_cycle", "issue_time_utc")
        .unique()
        .sort("issue_time_utc")
        if forecasts.height
        else pl.DataFrame()
    )
    meta = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": format_utc(now),
        "ingest_version": ingest_version(),
        "period": {
            "first_valid_utc": _clean(pairs["valid_time_utc"].min()) if pairs.height else None,
            "last_valid_utc": _clean(pairs["valid_time_utc"].max()) if pairs.height else None,
            "n_pairs": pairs.height,
            "n_days": pairs["valid_time_utc"].dt.date().n_unique() if pairs.height else 0,
        },
        "runs": {
            m: {
                "n": runs.filter(pl.col("model_id") == m).height,
                "first_utc": _clean(runs.filter(pl.col("model_id") == m)["issue_time_utc"].min()),
                "last_utc": _clean(runs.filter(pl.col("model_id") == m)["issue_time_utc"].max()),
                "cycles": sorted(
                    runs.filter(pl.col("model_id") == m)["model_cycle"].unique().to_list()
                ),
            }
            for m in (runs["model_id"].unique().to_list() if runs.height else [])
        },
        "models": MODEL_LABELS,
        "methods": METHOD_LABELS,
        "primary_method": PRIMARY_METHOD,
        "truth_levels": TRUTH_LABELS,
        "variables": {
            v.key: {
                "label": VARIABLE_LABELS[v.key][0],
                "unit": VARIABLE_LABELS[v.key][1],
                "note": VARIABLE_LABELS[v.key][2],
            }
            for v in VARIABLES
        },
        "pending_models": PENDING_MODELS,
        "availability": _availability(tables["bucket"]),
        "networks": {
            "kliima": "Kliimajaamad (kinnitatud, T1 ja T2)",
            "koik": "Kõik vaatlusjaamad (ka XML-i jaamad, ainult T1)",
        },
        "lead_buckets": list(LEAD_BUCKETS),
        "precip_thresholds_mm": list(PRECIP_THRESHOLDS_MM),
        "attribution": ATTRIBUTION,
        "freshness": freshness,
        "inventory": _inventory_summary(inventory),
        "notes": [
            "Eksperimentaalne, mitteametlik. Ei asenda KAURi ametlikku prognoosi ega hoiatusi.",
            "Mudelite võrdlus ühisel valimil: samad jooksud, etteanded, jaamad ja tunnid.",
            "Usaldusvahemikku näidatakse alates 10 valiidsuspäevast (plokk-bootstrap).",
            "XML-jaamad (kõrgus teadmata) on skoorides ainult T1-ga ja temperatuur ilma "
            "kõrguskorrektsioonita (ADR-019).",
        ],
    }
    _write(out_dir / "meta.json", meta)
    _write(out_dir / "stations.geojson", stations_geojson(settings, latest_xml))
    # The map uses the fair common sample only; drop redundant columns to keep it small.
    if tables["station"].height:
        tables["station"] = (
            tables["station"]
            .filter(pl.col("sample") == "common")
            .drop("sample", "n_stations", "unit")
        )
    for name, df in tables.items():
        _write(out_dir / f"scores_{name}.json", columnar(df) if df.height else {})
    series = station_series(forecasts, t2, t1, now)
    for sid, entry in series.items():
        _write(out_dir / "station" / f"{sid}.json", entry)
    LOG.info("site data: %d stations with series -> %s", len(series), out_dir)
    return out_dir


__all__ = ["METHODS", "build_site", "columnar"]
