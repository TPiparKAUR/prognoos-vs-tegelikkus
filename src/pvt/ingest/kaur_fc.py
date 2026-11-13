"""`pvt ingest-kaur-fc`: snapshots of KAUR's "Eesti prognoos" XML (4-day text forecast).

Source: https://www.ilmateenistus.ee/ilma_andmed/xml/forecast.php (+ ``?lang=eng``), KAUR
page "Eesti prognoos XML". The forecast is prepared by noon and revised in the morning if
needed (KAUR); the XML carries no issue time, so ``retrieved_at_utc`` (when the changed
content was first seen) is the only time reference. A snapshot is stored only when the
document's SHA-256 differs from the last stored one for that URL.

Scores for this forecast are internal only until the publication approver decides
(ADR-012); this module only archives.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import logging
import xml.etree.ElementTree as ET
from typing import Any, Final

import polars as pl

from pvt import SCHEMA_VERSION
from pvt.config import Settings
from pvt.ingest.http import FetchError, fetch_bytes, session
from pvt.provenance import ingest_version
from pvt.schemas import UTC_TS
from pvt.storage import day_dir, write_parquet_atomic
from pvt.timeutil import format_utc, require_utc, utc_now

LOG = logging.getLogger(__name__)

PERIOD: Final[dict[str, pl.DataType]] = {
    "retrieved_at_utc": UTC_TS,
    "lang": pl.String(),
    "forecast_date": pl.Date(),
    "period": pl.String(),  # "night" | "day" (local time, exact hours unconfirmed)
    "phenomenon": pl.String(),
    "tempmin_degC": pl.Float64(),
    "tempmax_degC": pl.Float64(),
    "text": pl.String(),
    "sea_text": pl.String(),
    "peipsi_text": pl.String(),
    "raw_sha256": pl.String(),
    "provenance": pl.String(),
    "ingest_version": pl.String(),
    "schema_version": pl.String(),
}
DETAIL: Final[dict[str, pl.DataType]] = {
    "retrieved_at_utc": UTC_TS,
    "lang": pl.String(),
    "forecast_date": pl.Date(),
    "period": pl.String(),
    "kind": pl.String(),  # "place" | "wind"
    "name": pl.String(),
    "phenomenon": pl.String(),
    "tempmin_degC": pl.Float64(),
    "tempmax_degC": pl.Float64(),
    "wind_direction_text": pl.String(),
    "speedmin_m_s": pl.Float64(),
    "speedmax_m_s": pl.Float64(),
    "gust_m_s": pl.Float64(),
    "raw_sha256": pl.String(),
    "provenance": pl.String(),
    "ingest_version": pl.String(),
    "schema_version": pl.String(),
}
MAX_XML_BYTES: Final = 2_000_000
META_COLUMNS: Final = frozenset({"raw_sha256", "provenance", "ingest_version", "schema_version"})


class KaurFcError(ValueError):
    """Raised when the forecast XML does not have the documented structure."""


def _t(el: ET.Element | None, tag: str) -> str | None:
    if el is None:
        return None
    child = el.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip() or None


def _f(el: ET.Element | None, tag: str) -> float | None:
    raw = _t(el, tag)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise KaurFcError(f"<{tag}> not numeric: {raw!r}") from exc


def lang_of(url: str) -> str:
    """Language code of a forecast URL (``est`` when no ``lang`` parameter)."""
    return url.split("lang=", 1)[1].split("&", 1)[0] if "lang=" in url else "est"


def parse_forecast(
    xml_bytes: bytes, retrieved_at: dt.datetime, lang: str
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Parse one forecast XML into (period rows, place/wind rows) without provenance."""
    if len(xml_bytes) > MAX_XML_BYTES:
        raise KaurFcError("XML larger than expected")
    root = ET.fromstring(xml_bytes)  # noqa: S314 (size-capped; expat >= 2.4.1)
    if root.tag != "forecasts":
        raise KaurFcError("root element must be <forecasts>")
    t = require_utc(retrieved_at)
    periods: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    for fc in root.findall("forecast"):
        try:
            date = dt.date.fromisoformat(fc.attrib["date"])
        except (KeyError, ValueError) as exc:
            raise KaurFcError("<forecast> without valid date attribute") from exc
        for period in ("night", "day"):
            el = fc.find(period)
            if el is None:
                continue
            common = {"retrieved_at_utc": t, "lang": lang, "forecast_date": date, "period": period}
            periods.append(
                {
                    **common,
                    "phenomenon": _t(el, "phenomenon"),
                    "tempmin_degC": _f(el, "tempmin"),
                    "tempmax_degC": _f(el, "tempmax"),
                    "text": _t(el, "text"),
                    "sea_text": _t(el, "sea"),
                    "peipsi_text": _t(el, "peipsi"),
                }
            )
            for pl_el in el.findall("place"):
                details.append(
                    {
                        **common,
                        "kind": "place",
                        "name": _t(pl_el, "name"),
                        "phenomenon": _t(pl_el, "phenomenon"),
                        "tempmin_degC": _f(pl_el, "tempmin"),
                        "tempmax_degC": _f(pl_el, "tempmax"),
                        "wind_direction_text": None,
                        "speedmin_m_s": None,
                        "speedmax_m_s": None,
                        "gust_m_s": None,
                    }
                )
            for w in el.findall("wind"):
                details.append(
                    {
                        **common,
                        "kind": "wind",
                        "name": _t(w, "name"),
                        "phenomenon": None,
                        "tempmin_degC": None,
                        "tempmax_degC": None,
                        "wind_direction_text": _t(w, "direction"),
                        "speedmin_m_s": _f(w, "speedmin"),
                        "speedmax_m_s": _f(w, "speedmax"),
                        "gust_m_s": _f(w, "gust"),
                    }
                )
    if not periods:
        raise KaurFcError("no <forecast> periods found")
    return (
        pl.DataFrame(periods, schema=_content_schema(PERIOD)),
        pl.DataFrame(details, schema=_content_schema(DETAIL)),
    )


def _content_schema(schema: dict[str, pl.DataType]) -> dict[str, pl.DataType]:
    return {c: d for c, d in schema.items() if c not in META_COLUMNS}


def _with_meta(df: pl.DataFrame, digest: str, schema: dict[str, pl.DataType]) -> pl.DataFrame:
    return df.with_columns(
        pl.lit(digest).alias("raw_sha256"),
        pl.lit("prognoos").alias("provenance"),
        pl.lit(ingest_version()).alias("ingest_version"),
        pl.lit(SCHEMA_VERSION).alias("schema_version"),
    ).select(list(schema))


def last_digest(settings: Settings, lang: str, today: dt.date, days_back: int = 7) -> str | None:
    """SHA-256 of the most recent stored snapshot for ``lang`` (searching back a week)."""
    for d in range(days_back + 1):
        day = today - dt.timedelta(days=d)
        p = day_dir(settings.data_root, "kaur_fc", day) / f"kaur_fc_period_{day:%Y-%m-%d}.parquet"
        if p.exists():
            df = pl.read_parquet(p).filter(pl.col("lang") == lang)
            if df.height:
                return str(df.sort("retrieved_at_utc").get_column("raw_sha256")[-1])
    return None


def store_snapshot(settings: Settings, xml_bytes: bytes, url: str, now: dt.datetime) -> str:
    """Archive one forecast document if it changed; returns ``stored`` or ``unchanged``."""
    lang = lang_of(url)
    now = require_utc(now).replace(second=0, microsecond=0)
    digest = hashlib.sha256(xml_bytes).hexdigest()
    if last_digest(settings, lang, now.date()) == digest:
        return "unchanged"
    per, det = parse_forecast(xml_bytes, now, lang)
    day = now.date()
    ddir = day_dir(settings.data_root, "kaur_fc", day)
    for name, new, schema in (("period", per, PERIOD), ("detail", det, DETAIL)):
        path = ddir / f"kaur_fc_{name}_{day:%Y-%m-%d}.parquet"
        old = pl.read_parquet(path) if path.exists() else pl.DataFrame(schema=schema)
        out = pl.concat([old, _with_meta(new, digest, schema)]).sort(
            ["retrieved_at_utc", "lang", "forecast_date", "period"], maintain_order=True
        )
        write_parquet_atomic(out, path)
    raw = ddir / "raw" / f"{now:%H%M}_{lang}.xml.gz"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(gzip.compress(xml_bytes, mtime=0))
    LOG.info("kaur_fc %s %s: new version stored", lang, format_utc(now))
    return "stored"


def ingest(settings: Settings, now: dt.datetime | None = None) -> dict[str, str]:
    """Fetch every configured forecast URL once; returns status per URL."""
    s = session()
    now = now or utc_now()
    out: dict[str, str] = {}
    for url in settings.kaur_fc_urls:
        try:
            out[url] = store_snapshot(
                settings, fetch_bytes(s, url, max_bytes=MAX_XML_BYTES), url, now
            )
        except (FetchError, KaurFcError, ET.ParseError) as exc:
            LOG.error("kaur_fc %s: %s", url, exc)
            out[url] = f"failed: {exc}"
    return out
