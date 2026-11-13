"""`pvt ingest-kliima`: validated hourly climate data (truth level T2).

Source: KAUR climate dataset API ``https://keskkonnaandmed.envir.ee/f_kliima_tund``
(PostgREST 12; table/column names from the API's OpenAPI document; CC BY 4.0,
Keskkonnaagentuur). One request returns at most 20 000 rows (Keskkonnaportaal
"Kasutusjuhend"), so requests are paged with ``limit``/``offset`` and a stable ``order``.

Time: columns ``aasta, kuu, paev, tund`` are documented as "... of measurement, UTC time".
``valid_time_utc`` = that date + ``tund`` hours. For the 1-hour sum PR1H the hour is assumed
to END at ``valid_time_utc`` (WMO convention) -- to be confirmed by KAUR (stage_1b report).

Validated data can be revised, so the last ``refetch_days`` days are fetched on every run
and a day file is rewritten only if its content changed.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Final

import polars as pl
import requests

from pvt import SCHEMA_VERSION
from pvt.config import Settings
from pvt.ingest.http import FetchError, session
from pvt.provenance import ingest_version
from pvt.schemas import UTC_TS, validate
from pvt.storage import day_dir, write_parquet_atomic
from pvt.timeutil import UTC, utc_now

LOG = logging.getLogger(__name__)

#: element code -> (column, unit string as returned by the API in element_yhik_eng)
ELEMENTS: Final[dict[str, tuple[str, str]]] = {
    "TA": ("ta_degC", "°C"),
    "PR1H": ("pr1h_mm", "mm"),
    "WS10M": ("ws10m_m_s", "m/s"),
    "WD10M": ("wd10m_deg", "°"),
    "WSX1H": ("wsx1h_m_s", "m/s"),
    "PA0": ("pa0_hPa", "hPa"),
    "RH": ("rh_pct", "%"),
}

OBS_KLIIMA: Final[dict[str, pl.DataType]] = {
    "station_id": pl.String(),
    "valid_time_utc": UTC_TS,
    **{col: pl.Float64() for col, _ in ELEMENTS.values()},
    "published_max_utc": UTC_TS,
    "provenance": pl.String(),
    "source": pl.String(),
    "source_uri": pl.String(),
    "ingest_version": pl.String(),
    "schema_version": pl.String(),
}
OBS_KLIIMA_KEY: Final = ("station_id", "valid_time_utc")
META_COLUMNS: Final = frozenset(
    {"provenance", "source", "source_uri", "ingest_version", "schema_version"}
)


class KliimaError(ValueError):
    """Raised for unexpected API content (unknown unit, duplicate rows)."""


def fetch_day(
    s: requests.Session, settings: Settings, day: dt.date, station_ids: list[str]
) -> list[dict[str, Any]]:
    """All hourly rows of ``day`` for the configured elements and stations (paged)."""
    k = settings.kliima
    url = f"{k.base_url.rstrip('/')}/{k.hourly_table}"
    params = {
        "select": "jaam_kood,aasta,kuu,paev,tund,element_kood,vaartus,element_yhik_eng,"
        "avaandmed_ts",
        "aasta": f"eq.{day.year}",
        "kuu": f"eq.{day.month}",
        "paev": f"eq.{day.day}",
        "element_kood": f"in.({','.join(k.elements)})",
        "jaam_kood": f"in.({','.join(station_ids)})",
        "order": "jaam_kood,tund,element_kood",
        "limit": str(k.page_size),
    }
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        try:
            r = s.get(url, params={**params, "offset": str(offset)}, timeout=120)
            r.raise_for_status()
        except requests.RequestException as exc:
            raise FetchError(f"{url}: {exc}") from exc
        page: list[dict[str, Any]] = r.json()
        rows.extend(page)
        if len(page) < k.page_size:
            return rows
        offset += k.page_size


def latest_revisions(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Keep, per station/hour/element, the row with the latest ``avaandmed_ts``.

    The API keeps earlier published versions of revised values (observed 2026-11-13:
    AJNARV01 2026-11-11 20 UTC PA0 published as 1002.7 and later 1002.8).

    Returns
    -------
    tuple of (list of dict, int)
        Latest rows and the number of superseded rows.

    Raises
    ------
    KliimaError
        If two rows with the same publication time disagree.
    """
    best: dict[tuple[Any, ...], dict[str, Any]] = {}
    superseded = 0
    for r in rows:
        key = (r["jaam_kood"], r["aasta"], r["kuu"], r["paev"], r["tund"], r["element_kood"])
        pub = dt.datetime.fromisoformat(r["avaandmed_ts"]).astimezone(UTC)
        r = {**r, "_pub": pub}
        old = best.get(key)
        if old is None:
            best[key] = r
            continue
        superseded += 1
        if pub == old["_pub"] and r["vaartus"] != old["vaartus"]:
            raise KliimaError(f"conflicting values with equal publication time for {key}")
        if pub > old["_pub"]:
            best[key] = r
    return list(best.values()), superseded


def to_frame(rows: list[dict[str, Any]], source_uri: str) -> pl.DataFrame:
    """Pivot API rows (latest revision only) to one row per station and hour (OBS_KLIIMA)."""
    latest, superseded = latest_revisions(rows)
    if superseded:
        LOG.info("kliima: %d superseded (revised) values ignored", superseded)
    recs: dict[tuple[str, dt.datetime], dict[str, Any]] = {}
    for r in latest:
        code = r["element_kood"]
        if code not in ELEMENTS:
            continue
        col, unit = ELEMENTS[code]
        if r["element_yhik_eng"] != unit:
            raise KliimaError(f"{code}: unit {r['element_yhik_eng']!r} != expected {unit!r}")
        t = dt.datetime(r["aasta"], r["kuu"], r["paev"], tzinfo=UTC) + dt.timedelta(
            hours=int(r["tund"])
        )
        rec = recs.setdefault(
            (r["jaam_kood"], t),
            {"station_id": r["jaam_kood"], "valid_time_utc": t, "published_max_utc": None},
        )
        rec[col] = None if r["vaartus"] is None else float(r["vaartus"])
        if rec["published_max_utc"] is None or r["_pub"] > rec["published_max_utc"]:
            rec["published_max_utc"] = r["_pub"]
    content = {c: d for c, d in OBS_KLIIMA.items() if c not in META_COLUMNS}
    df = pl.DataFrame(list(recs.values()), schema=content)
    return (
        df.with_columns(
            pl.lit("kvaliteedikontrollitud").alias("provenance"),
            pl.lit("kaur_kliima_hly").alias("source"),
            pl.lit(source_uri).alias("source_uri"),
            pl.lit(ingest_version()).alias("ingest_version"),
            pl.lit(SCHEMA_VERSION).alias("schema_version"),
        )
        .select(list(OBS_KLIIMA))
        .sort(["station_id", "valid_time_utc"])
    )


def _content(df: pl.DataFrame) -> pl.DataFrame:
    return df.drop("ingest_version")


def ingest(settings: Settings, now: dt.datetime | None = None) -> dict[str, str]:
    """Fetch the last ``refetch_days`` days (incl. today) and rewrite changed day files."""
    now = now or utc_now()
    ids = sorted(s.station_id for s in settings.stations if s.verified)
    s = session()
    uri = f"{settings.kliima.base_url.rstrip('/')}/{settings.kliima.hourly_table}"
    status: dict[str, str] = {}
    for back in range(settings.kliima.refetch_days, -1, -1):
        day = now.date() - dt.timedelta(days=back)
        df = to_frame(fetch_day(s, settings, day, ids), uri)
        if df.is_empty():
            status[day.isoformat()] = "empty"
            continue
        validate(df, OBS_KLIIMA, OBS_KLIIMA_KEY)
        path = day_dir(settings.data_root, "kliima", day) / f"kliima_hly_{day:%Y-%m-%d}.parquet"
        if path.exists() and _content(pl.read_parquet(path)).equals(_content(df)):
            status[day.isoformat()] = "unchanged"
            continue
        write_parquet_atomic(df, path)
        status[day.isoformat()] = f"written ({df.height} rows)"
        LOG.info("kliima %s: %d station-hours", day, df.height)
    return status
