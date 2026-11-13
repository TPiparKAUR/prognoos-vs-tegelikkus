"""`pvt ingest-obs-xml`: snapshots of the KAUR observations XML (truth level T1).

Source: https://www.ilmateenistus.ee/ilma_andmed/xml/observations.php (KAUR; terms: cite
Keskkonnaagentuur and link ilmateenistus.ee). Element meanings from the KAUR page
"Eesti vaatlusandmed XML". The XML has no history, so it is fetched every 10 minutes.

* The root attribute ``timestamp`` is Unix epoch seconds (verified on a 2026-11-13 sample:
  1794556259 = 2026-11-13T07:50:59Z). It is stored as ``snapshot_time_utc``; individual
  parameters update hourly or every 10 min (KAUR page), so the exact measurement time per
  parameter is NOT in the data and is resolved in stage E2.
* Column names keep the XML element names plus units; e.g. ``airpressure_hPa`` is NOT
  renamed to sea-level pressure because the XML documentation does not say which it is.
* Raw XML is kept (gzip) only when it differs from the last stored snapshot.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Final

import polars as pl

from pvt import SCHEMA_VERSION
from pvt.config import Settings
from pvt.ingest.http import fetch_bytes, session
from pvt.provenance import ingest_version
from pvt.schemas import UTC_TS, SchemaError, validate
from pvt.stations import MATCH_RADIUS_KM, haversine_km, slug, xml_stations_path
from pvt.storage import day_dir, write_parquet_atomic
from pvt.timeutil import UTC, format_utc

LOG = logging.getLogger(__name__)

#: XML element -> (column, type). Units from the KAUR XML documentation page.
NUMERIC_ELEMENTS: Final[dict[str, str]] = {
    "visibility": "visibility_km",
    "precipitations": "precipitations_1h_mm",
    "airpressure": "airpressure_hPa",
    "relativehumidity": "relativehumidity_pct",
    "airtemperature": "airtemperature_degC",
    "winddirection": "winddirection_deg",
    "windspeed": "windspeed_m_s",
    "windspeedmax": "windspeedmax_m_s",
    "waterlevel": "waterlevel_cm",
    "waterlevel_eh2000": "waterlevel_eh2000_cm",
    "watertemperature": "watertemperature_degC",
    "uvindex": "uvindex_1",
    "sunshineduration": "sunshineduration_day_min",
    "globalradiation": "globalradiation_1h_W_m2",
}

OBS_XML: Final[dict[str, pl.DataType]] = {
    "snapshot_time_utc": UTC_TS,
    "station_id": pl.String(),
    "station_name": pl.String(),
    "wmo_code": pl.String(),
    "lat_deg": pl.Float64(),
    "lon_deg": pl.Float64(),
    "phenomenon": pl.String(),
    **{col: pl.Float64() for col in NUMERIC_ELEMENTS.values()},
    "provenance": pl.String(),
    "source": pl.String(),
    "raw_sha256": pl.String(),
    "ingest_version": pl.String(),
    "schema_version": pl.String(),
}
OBS_XML_KEY: Final = ("snapshot_time_utc", "station_id")

XML_STATIONS: Final[dict[str, pl.DataType]] = {
    "station_id": pl.String(),
    "name": pl.String(),
    "wmo_code": pl.String(),
    "lat_deg": pl.Float64(),
    "lon_deg": pl.Float64(),
    "first_seen_utc": UTC_TS,
}

MAX_XML_BYTES: Final = 5_000_000


class ObsXmlError(ValueError):
    """Raised when the observations XML does not have the documented structure."""


def _text(el: ET.Element, tag: str) -> str | None:
    child = el.find(tag)
    if child is None:
        raise ObsXmlError(f"station without <{tag}> element")
    value = (child.text or "").strip()
    return value or None


def _float(raw: str | None, tag: str, station: str) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise ObsXmlError(f"{station}: <{tag}> not numeric: {raw!r}") from exc


def parse_observations(
    xml_bytes: bytes, verified: list[dict[str, Any]]
) -> tuple[dt.datetime, pl.DataFrame]:
    """Parse one observations XML snapshot.

    Parameters
    ----------
    xml_bytes : bytes
        Raw XML.
    verified : list of dict
        Verified stations (``station_id``, ``name``, ``lat_deg``, ``lon_deg``) to map
        XML names to climate station codes (same name or within 1 km).

    Returns
    -------
    tuple of (datetime.datetime, polars.DataFrame)
        Snapshot time (UTC) and rows in OBS_XML layout (without provenance columns).
    """
    if len(xml_bytes) > MAX_XML_BYTES:
        raise ObsXmlError("XML larger than expected")
    # Trusted-format, size-capped input; Python 3.12's expat (>= 2.4.1) protects against
    # entity-expansion attacks, so the stdlib parser is acceptable here.
    root = ET.fromstring(xml_bytes)  # noqa: S314
    if root.tag != "observations" or "timestamp" not in root.attrib:
        raise ObsXmlError("root element must be <observations timestamp=...>")
    snap = dt.datetime.fromtimestamp(int(root.attrib["timestamp"]), UTC)
    rows: list[dict[str, Any]] = []
    for st in root.findall("station"):
        name = _text(st, "name")
        if name is None:
            raise ObsXmlError("station without name")
        lat = _float(_text(st, "latitude"), "latitude", name)
        lon = _float(_text(st, "longitude"), "longitude", name)
        sid = xml_station_id(name, lat, lon)
        # Station names are not unique in the XML (e.g. a meteorological and a hydrological
        # station share a name), so climate stations are matched by position only.
        if lat is not None and lon is not None:
            for v in verified:
                if haversine_km(v["lat_deg"], v["lon_deg"], lat, lon) < MATCH_RADIUS_KM:
                    sid = v["station_id"]
                    break
        row: dict[str, Any] = {
            "snapshot_time_utc": snap,
            "station_id": sid,
            "station_name": name,
            "wmo_code": _text(st, "wmocode"),
            "lat_deg": lat,
            "lon_deg": lon,
            "phenomenon": _text(st, "phenomenon"),
        }
        for tag, col in NUMERIC_ELEMENTS.items():
            row[col] = _float(_text(st, tag), tag, name)
        rows.append(row)
    if not rows:
        raise ObsXmlError("no <station> elements")
    cols = [c for c in OBS_XML if c in rows[0]]
    df = pl.DataFrame(rows, schema={c: OBS_XML[c] for c in cols})
    exact = df.height - df.unique().height
    if exact:
        LOG.warning("obs_xml %s: %d exact duplicate station entries dropped", snap, exact)
        df = df.unique(maintain_order=True)
    return snap, df


def xml_station_id(name: str, lat: float | None, lon: float | None) -> str:
    """Stable id of an XML-only station: name slug plus position (names are not unique)."""
    if lat is None or lon is None:
        return f"XML_{slug(name)}"
    return f"XML_{slug(name)}_{round(lat * 1000):d}_{round(lon * 1000):d}"


def _day_parquet(data_root: Path, day: dt.date) -> Path:
    return day_dir(data_root, "obs_xml", day) / f"obs_xml_{day:%Y-%m-%d}.parquet"


def update_xml_station_registry(data_root: Path, obs: pl.DataFrame) -> bool:
    """Add stations not yet in ``meta/xml_stations.parquet``; return True if changed.

    Existing entries are kept unchanged (a coordinate change is logged, not applied) so
    the registry file only changes when a station appears.
    """
    path = xml_stations_path(data_root)
    cur = pl.read_parquet(path) if path.exists() else pl.DataFrame(schema=XML_STATIONS)
    known = {r["station_id"]: r for r in cur.iter_rows(named=True)}
    new_rows = []
    for r in obs.filter(
        pl.col("lat_deg").is_not_null() & pl.col("lon_deg").is_not_null()
    ).iter_rows(named=True):
        k = known.get(r["station_id"])
        if k is None:
            new_rows.append(
                {
                    "station_id": r["station_id"],
                    "name": r["station_name"],
                    "wmo_code": r["wmo_code"],
                    "lat_deg": r["lat_deg"],
                    "lon_deg": r["lon_deg"],
                    "first_seen_utc": r["snapshot_time_utc"],
                }
            )
        elif haversine_km(k["lat_deg"], k["lon_deg"], r["lat_deg"], r["lon_deg"]) > 0.05:
            LOG.warning(
                "station %s moved in XML (%.4f, %.4f) -> (%.4f, %.4f); not applied",
                r["station_name"],
                k["lat_deg"],
                k["lon_deg"],
                r["lat_deg"],
                r["lon_deg"],
            )
    if not new_rows:
        return False
    out = pl.concat([cur, pl.DataFrame(new_rows, schema=XML_STATIONS)]).sort("station_id")
    write_parquet_atomic(out, path)
    LOG.info("xml station registry: +%d stations (%d total)", len(new_rows), out.height)
    return True


def store_snapshot(settings: Settings, xml_bytes: bytes) -> str:
    """Parse and archive one snapshot; returns ``stored``, ``duplicate``.

    Raises
    ------
    ObsXmlError, SchemaError
        If the XML is not in the documented structure.
    """
    verified = [
        {"station_id": s.station_id, "name": s.name, "lat_deg": s.lat_deg, "lon_deg": s.lon_deg}
        for s in settings.stations
        if s.verified
    ]
    snap, obs = parse_observations(xml_bytes, verified)
    digest = hashlib.sha256(xml_bytes).hexdigest()
    day = snap.date()
    path = _day_parquet(settings.data_root, day)
    existing = pl.read_parquet(path) if path.exists() else pl.DataFrame(schema=OBS_XML)
    if existing.filter(
        (pl.col("snapshot_time_utc") == snap) | (pl.col("raw_sha256") == digest)
    ).height:
        LOG.info("obs_xml %s: already stored", format_utc(snap))
        return "duplicate"
    obs = obs.with_columns(
        pl.lit("toormõõtmine").alias("provenance"),
        pl.lit("ilmateenistus_xml").alias("source"),
        pl.lit(digest).alias("raw_sha256"),
        pl.lit(ingest_version()).alias("ingest_version"),
        pl.lit(SCHEMA_VERSION).alias("schema_version"),
    ).select(list(OBS_XML))
    combined = pl.concat([existing, obs]).sort(["snapshot_time_utc", "station_name"])
    validate(combined, OBS_XML, OBS_XML_KEY)
    raw = day_dir(settings.data_root, "obs_xml", day) / "raw" / f"{snap:%H%M%S}.xml.gz"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(gzip.compress(xml_bytes, mtime=0))
    write_parquet_atomic(combined, path)
    update_xml_station_registry(settings.data_root, obs)
    LOG.info("obs_xml %s: %d stations stored", format_utc(snap), obs.height)
    return "stored"


def ingest(settings: Settings) -> str:
    """Fetch the observations XML once and archive it if new."""
    xml_bytes = fetch_bytes(session(), settings.obs_xml_url, max_bytes=MAX_XML_BYTES)
    try:
        return store_snapshot(settings, xml_bytes)
    except (ObsXmlError, SchemaError, ET.ParseError) as exc:
        # Keep the unexpected document for diagnosis (docs/07 R9: XML structure changes).
        bad = (
            settings.data_root
            / "quarantine"
            / f"obs_{hashlib.sha256(xml_bytes).hexdigest()[:16]}.xml"
        )
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_bytes(xml_bytes)
        raise ObsXmlError(f"{exc} (document kept in {bad})") from exc
