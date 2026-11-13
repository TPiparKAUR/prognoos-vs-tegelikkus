"""KAUR observations XML, 'Eesti prognoos' XML and climate API ingest (offline)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from pvt.config import REPO_ROOT, Settings
from pvt.ingest import kaur_fc, kliima, obs_xml
from pvt.stations import station_targets, xml_stations_path
from pvt.storage import day_dir
from pvt.timeutil import UTC

FIX = REPO_ROOT / "tests" / "fixtures"
OBS = (FIX / "observations_sample.xml").read_bytes()
FC = (FIX / "forecast_sample.xml").read_bytes()
SNAP = dt.datetime(2026, 11, 13, 7, 50, 59, tzinfo=UTC)


@pytest.fixture
def real_stations(settings: Settings) -> Settings:
    """Test settings but with the repository's verified station register."""
    import dataclasses

    from pvt.config import load_settings

    return dataclasses.replace(settings, stations=load_settings(REPO_ROOT / "config").stations)


# ------------------------------------------------------------------ observations XML


def test_parse_observations_fixture(real_stations: Settings) -> None:
    verified = [
        {"station_id": s.station_id, "name": s.name, "lat_deg": s.lat_deg, "lon_deg": s.lon_deg}
        for s in real_stations.stations
    ]
    snap, df = obs_xml.parse_observations(OBS, verified)
    assert snap == SNAP  # epoch seconds, UTC
    assert df.height == 9
    harku = df.filter(pl.col("station_name") == "Tallinn-Harku").row(0, named=True)
    assert harku["station_id"] == "XML_TALLINN_HARKU_59398_24603_W26038"
    assert harku["kliima_station_id"] == "AJHARK01"
    assert harku["wmo_code"] == "26038"
    assert harku["airtemperature_degC"] == 2.0
    assert harku["precipitations_1h_mm"] == 0.2
    assert harku["phenomenon"] == "Light shower"
    kur = df.filter(pl.col("station_name") == "Kuressaare linn").row(0, named=True)
    assert kur["station_id"] == "XML_KURESSAARE_LINN_58264_22489"
    assert kur["kliima_station_id"] is None
    assert kur["wmo_code"] is None
    assert kur["windspeed_m_s"] is None
    narva = df.filter(pl.col("station_name") == "Narva").row(0, named=True)
    assert narva["globalradiation_1h_W_m2"] == -1.0  # kept as published; QC is E2


def test_store_observations_is_idempotent(real_stations: Settings) -> None:
    assert obs_xml.store_snapshot(real_stations, OBS) == "stored"
    assert obs_xml.store_snapshot(real_stations, OBS) == "duplicate"
    ddir = day_dir(real_stations.data_root, "obs_xml", SNAP.date())
    df = pl.read_parquet(ddir / "obs_xml_2026-11-13.parquet")
    assert df.height == 9
    assert set(df.get_column("provenance").unique()) == {"toormõõtmine"}
    assert (ddir / "raw" / "075059.xml.gz").exists()
    reg = pl.read_parquet(xml_stations_path(real_stations.data_root))
    assert reg.height == 9
    targets = station_targets(real_stations)
    extra = targets.filter(~pl.col("verified")).get_column("station_id").to_list()
    # only XML stations that are not climate stations are added (unverified)
    assert extra == ["XML_HAAPSALU_58945_23555_W26123", "XML_KURESSAARE_LINN_58264_22489"]


def test_request_timestamp_does_not_defeat_dedup(real_stations: Settings) -> None:
    """The XML timestamp is the request time; same content later is not stored again."""
    assert obs_xml.store_snapshot(real_stations, OBS) == "stored"
    later = OBS.replace(b"1794556259", b"1794556859")  # +10 min, same content
    assert obs_xml.store_snapshot(real_stations, later) == "duplicate"
    changed = later.replace(
        b"<airtemperature>2</airtemperature>", b"<airtemperature>2.1</airtemperature>"
    )
    assert obs_xml.store_snapshot(real_stations, changed) == "stored"


def test_conflicting_entries_are_reported_by_name(real_stations: Settings) -> None:
    block = OBS[OBS.index(b"<station>\n<name>Haapsalu") : OBS.index(b"</observations>")]
    other = block.replace(b"<airtemperature>3.6", b"<airtemperature>9.9")
    doc = OBS.replace(b"</observations>", other + b"</observations>")
    with pytest.raises(obs_xml.ObsXmlError, match="Haapsalu"):
        obs_xml.parse_observations(doc, [])


def test_duplicate_station_names_are_kept_apart(real_stations: Settings) -> None:
    """The live XML contains repeated station names (observed 2026-11-13 on GitHub)."""
    block = OBS[OBS.index(b"<station>\n<name>Haapsalu") : OBS.index(b"</observations>")]
    moved = block.replace(b"58.945277777444446", b"58.9").replace(
        b"<airtemperature>3.6", b"<airtemperature>3.9"
    )
    doc = OBS.replace(b"</observations>", block + moved + block + b"</observations>")
    _, df = obs_xml.parse_observations(doc, [])
    hap = df.filter(pl.col("station_name") == "Haapsalu")
    assert hap.height == 2  # exact duplicate dropped, different position kept
    assert hap.get_column("station_id").n_unique() == 2


def test_malformed_observations_rejected(real_stations: Settings) -> None:
    bad = OBS.replace(b"<airtemperature>2</airtemperature>", b"<airtemperature>x</airtemperature>")
    with pytest.raises(obs_xml.ObsXmlError, match="not numeric"):
        obs_xml.store_snapshot(real_stations, bad)
    with pytest.raises(obs_xml.ObsXmlError, match="root element"):
        obs_xml.store_snapshot(real_stations, b"<html></html>")


# ------------------------------------------------------------------ Eesti prognoos XML


def test_parse_forecast_fixture() -> None:
    t = dt.datetime(2026, 11, 13, 8, 0, tzinfo=UTC)
    per, det = kaur_fc.parse_forecast(FC, t, "est")
    assert per.height == 4
    first = per.row(0, named=True)
    assert first["forecast_date"] == dt.date(2026, 11, 13)
    assert first["period"] == "night"
    assert (first["tempmin_degC"], first["tempmax_degC"]) == (0.0, 5.0)
    assert det.filter(pl.col("kind") == "place").height == 8
    wind = det.filter((pl.col("kind") == "wind") & (pl.col("name") == "Väike-Maarja")).row(
        0, named=True
    )
    assert (wind["speedmin_m_s"], wind["speedmax_m_s"], wind["gust_m_s"]) == (7.0, 10.0, 13.0)
    assert wind["wind_direction_text"] == "Southeast wind"


def test_store_forecast_only_when_changed(settings: Settings) -> None:
    url = settings.kaur_fc_urls[0]
    t = dt.datetime(2026, 11, 13, 8, 0, tzinfo=UTC)
    assert kaur_fc.store_snapshot(settings, FC, url, t) == "stored"
    assert kaur_fc.store_snapshot(settings, FC, url, t + dt.timedelta(hours=1)) == "unchanged"
    changed = FC.replace(b"<tempmax>7</tempmax>", b"<tempmax>8</tempmax>", 1)
    assert kaur_fc.store_snapshot(settings, changed, url, t + dt.timedelta(hours=2)) == "stored"
    ddir = day_dir(settings.data_root, "kaur_fc", t.date())
    per = pl.read_parquet(ddir / "kaur_fc_period_2026-11-13.parquet")
    assert per.get_column("retrieved_at_utc").n_unique() == 2
    assert kaur_fc.lang_of(settings.kaur_fc_urls[1]) == "eng"


# ------------------------------------------------------------------ climate API


def _row(**kw: Any) -> dict[str, Any]:
    base = {
        "jaam_kood": "AJHARK01",
        "aasta": 2026,
        "kuu": 11,
        "paev": 11,
        "tund": 20,
        "element_kood": "PA0",
        "vaartus": 1002.7,
        "element_yhik_eng": "hPa",
        "avaandmed_ts": "2026-11-12T06:00:04+02:00",
    }
    return {**base, **kw}


def test_kliima_keeps_latest_revision() -> None:
    rows = [
        _row(),
        _row(vaartus=1002.8, avaandmed_ts="2026-11-12T07:00:04+02:00"),
        _row(element_kood="TA", vaartus=1.5, element_yhik_eng="°C"),
        _row(element_kood="PR1H", vaartus=None, element_yhik_eng="mm"),
    ]
    df = kliima.to_frame(rows, "test")
    assert df.height == 1
    r = df.row(0, named=True)
    assert r["valid_time_utc"] == dt.datetime(2026, 11, 11, 20, tzinfo=UTC)
    assert r["pa0_hPa"] == 1002.8
    assert r["ta_degC"] == 1.5
    assert r["pr1h_mm"] is None
    assert r["published_max_utc"] == dt.datetime(2026, 11, 12, 5, 0, 4, tzinfo=UTC)
    assert r["provenance"] == "kvaliteedikontrollitud"


def test_kliima_rejects_unit_change_and_conflicts() -> None:
    with pytest.raises(kliima.KliimaError, match="unit"):
        kliima.to_frame([_row(element_yhik_eng="Pa")], "test")
    with pytest.raises(kliima.KliimaError, match="conflicting"):
        kliima.to_frame([_row(), _row(vaartus=999.0)], "test")


def test_kliima_ingest_pages_and_skips_unchanged(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dataclasses

    s = dataclasses.replace(
        settings, kliima=dataclasses.replace(settings.kliima, refetch_days=0, page_size=2)
    )
    calls: list[int] = []

    class Resp:
        def __init__(self, data: list[dict[str, Any]]) -> None:
            self.data = data

        def raise_for_status(self) -> None:
            pass

        def json(self) -> list[dict[str, Any]]:
            return self.data

    rows = [
        _row(paev=13, tund=h, element_kood="TA", element_yhik_eng="°C", vaartus=float(h))
        for h in range(3)
    ]

    class Sess:
        def get(self, url: str, params: dict[str, str], timeout: int) -> Resp:
            off = int(params["offset"])
            calls.append(off)
            return Resp(rows[off : off + 2])

    monkeypatch.setattr(kliima, "session", lambda: Sess())
    now = dt.datetime(2026, 11, 13, 12, tzinfo=UTC)
    assert kliima.ingest(s, now) == {"2026-11-13": "written (3 rows)"}
    assert calls == [0, 2]
    assert kliima.ingest(s, now) == {"2026-11-13": "unchanged"}


def test_fixture_readme_cites_source() -> None:
    text = (FIX / "README.md").read_text("utf-8")
    assert "Keskkonnaagentuur" in text
    assert Path(FIX / "observations_sample.xml").exists()
