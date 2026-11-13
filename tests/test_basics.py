"""Time handling, units, configuration and schema validation."""

from __future__ import annotations

import dataclasses
import datetime as dt
import shutil
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from pvt import SCHEMA_VERSION
from pvt.config import REPO_ROOT, ConfigError, load_settings
from pvt.schemas import FORECAST_GRID_STATIC, UTC_TS, SchemaError, validate
from pvt.timeutil import (
    UTC,
    NaiveDatetimeError,
    floor_to_run,
    iter_runs,
    parse_utc,
    require_utc,
    run_tag,
)
from pvt.units import UnitError, convert

# ------------------------------------------------------------------ time


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(NaiveDatetimeError):
        require_utc(dt.datetime(2026, 11, 12, 6))  # noqa: DTZ001 (deliberately naive)


def test_parse_utc_requires_offset() -> None:
    assert parse_utc("2026-11-12T06Z") == dt.datetime(2026, 11, 12, 6, tzinfo=UTC)
    assert parse_utc("2026-11-12T08:00:00+02:00") == dt.datetime(2026, 11, 12, 6, tzinfo=UTC)
    with pytest.raises(NaiveDatetimeError):
        parse_utc("2026-11-12T06:00:00")


def test_run_enumeration_newest_first() -> None:
    start = dt.datetime(2026, 11, 11, 12, tzinfo=UTC)
    end = dt.datetime(2026, 11, 12, 7, 30, tzinfo=UTC)
    runs = list(iter_runs(start, end))
    assert [run_tag(r) for r in runs] == [
        "20261112T06Z",
        "20261112T00Z",
        "20261111T18Z",
        "20261111T12Z",
    ]
    assert floor_to_run(dt.datetime(2026, 11, 12, 5, 59, tzinfo=UTC)).hour == 0


# ------------------------------------------------------------------ units


@pytest.mark.parametrize(
    ("quantity", "unit", "value", "target", "expected"),
    [
        ("temperature", "K", 273.15, "degC", 0.0),
        ("pressure", "Pa", 101_325.0, "hPa", 1013.25),
        ("precipitation", "m", 0.0123, "mm", 12.3),
        ("precipitation", "kg m**-2", 12.3, "mm", 12.3),
        ("geopotential", "m**2 s**-2", 980.665, "m", 100.0),
        ("wind", "m s**-1", 5.0, "m_s", 5.0),
        ("fraction", "(0 - 1)", 0.4, "frac", 0.4),
    ],
)
def test_unit_conversions(
    quantity: str, unit: str, value: float, target: str, expected: float
) -> None:
    got_unit, got = convert(quantity, unit, np.array([value]))
    assert got_unit == target
    assert got[0] == pytest.approx(expected, abs=1e-9)


def test_unknown_unit_is_refused() -> None:
    with pytest.raises(UnitError):
        convert("precipitation", "mm h**-1", np.array([1.0]))
    with pytest.raises(UnitError):
        convert("temperature", "degC", np.array([1.0]))


# ------------------------------------------------------------------ config


def test_repository_config_loads() -> None:
    s = load_settings(REPO_ROOT / "config")
    ifs, aifs = s.models["ifs"], s.models["aifs-single"]
    # Observed schedules (config/params.toml), docs/01 conflict resolved by observation.
    assert len(ifs.expected_steps[0]) == 85
    assert len(ifs.expected_steps[6]) == 49
    assert ifs.expected_steps[18][-1] == 144
    assert all(len(aifs.expected_steps[h]) == 61 for h in (0, 6, 12, 18))
    assert ifs.cycle_for(dt.datetime(2026, 11, 12, tzinfo=UTC)) == "50r1"
    assert ifs.cycle_for(dt.datetime(2026, 1, 1, tzinfo=UTC)) == "unknown"


def test_no_station_is_verified_without_sources() -> None:
    s = load_settings(REPO_ROOT / "config")
    assert len(s.stations) == 25
    for st in s.stations:
        if st.verified:
            assert st.lat_deg is not None
            assert st.coord_source_uri
            assert st.height_source_uri


def test_verified_station_needs_all_metadata(tmp_path: Path) -> None:
    cdir = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", cdir)
    (cdir / "stations.toml").write_text(
        '[[station]]\nstation_id = "X"\nname = "Test"\nverified = true\nlat_deg = 59.0\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="missing"):
        load_settings(cdir)


def test_verified_station_outside_estonia_is_refused(tmp_path: Path) -> None:
    cdir = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", cdir)
    (cdir / "stations.toml").write_text(
        '[[station]]\nstation_id = "X"\nname = "Test"\nverified = true\nlat_deg = 52.0\n'
        'lon_deg = 13.0\nheight_m_EH2000 = 30.0\ncoord_source_uri = "a"\n'
        'height_source_uri = "b"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="outside Estonia"):
        load_settings(cdir)


# ------------------------------------------------------------------ schema


def _static_frame(n: int = 2) -> pl.DataFrame:
    t = dt.datetime(2026, 11, 12, 6, tzinfo=UTC)
    return pl.DataFrame(
        {
            "model_id": ["ifs"] * n,
            "model_cycle": ["50r1"] * n,
            "issue_time_utc": [t] * n,
            "grid_lat_deg": [59.0 + i for i in range(n)],
            "grid_lon_deg": [24.0] * n,
            "grid_orog_m": [10.0] * n,
            "grid_lsm_frac": [1.0] * n,
            "provenance": ["prognoos"] * n,
            "source_uri": ["x"] * n,
            "ingest_version": ["test"] * n,
            "schema_version": [SCHEMA_VERSION] * n,
        },
        schema=FORECAST_GRID_STATIC,
    )


def test_schema_accepts_valid_frame() -> None:
    validate(_static_frame(), FORECAST_GRID_STATIC, ("grid_lat_deg", "grid_lon_deg"))


def test_schema_rejects_naive_timestamps() -> None:
    df = _static_frame().with_columns(pl.col("issue_time_utc").dt.replace_time_zone(None))
    with pytest.raises(SchemaError, match="dtype"):
        validate(df, FORECAST_GRID_STATIC)


def test_schema_rejects_duplicates_and_mixed_provenance() -> None:
    df = pl.concat([_static_frame(1), _static_frame(1)])
    with pytest.raises(SchemaError, match="duplicate"):
        validate(df, FORECAST_GRID_STATIC, ("grid_lat_deg", "grid_lon_deg"))
    mixed = _static_frame().with_columns(pl.Series("provenance", ["prognoos", "reanalüüs"]))
    with pytest.raises(SchemaError, match="mixed provenance"):
        validate(mixed, FORECAST_GRID_STATIC)


def test_schema_rejects_lead_mismatch() -> None:
    schema = {"issue_time_utc": UTC_TS, "valid_time_utc": UTC_TS, "lead_h": pl.Int16()}
    t = dt.datetime(2026, 11, 12, 6, tzinfo=UTC)
    df = pl.DataFrame(
        {"issue_time_utc": [t], "valid_time_utc": [t + dt.timedelta(hours=6)], "lead_h": [3]},
        schema=schema,
    )
    with pytest.raises(SchemaError, match="lead_h"):
        validate(df, schema)


def test_settings_are_frozen() -> None:
    s = load_settings(REPO_ROOT / "config")
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.ecmwf.lookback_hours = 1  # type: ignore[misc]
