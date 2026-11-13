"""Shared fixtures: synthetic GRIB2 writer, fake mirrors and test settings."""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Callable, Sequence
from pathlib import Path

import eccodes
import numpy as np
import pytest

from pvt.config import REPO_ROOT, Area, ModelConfig, Settings, load_settings
from pvt.timeutil import UTC

ISSUE = dt.datetime(2026, 11, 12, 6, tzinfo=UTC)
TEST_AREA = Area(
    lat_min_deg=57.0, lat_max_deg=60.0, lon_min_deg=21.0, lon_max_deg=28.0, grid_increment_deg=1.0
)
TEST_STEPS = (0, 3, 6, 9, 12)

# (shortName, typeOfLevel, level) as in ECMWF open data
LEVELS: dict[str, tuple[str, int | None]] = {
    "2t": ("heightAboveGround", 2),
    "10u": ("heightAboveGround", 10),
    "10v": ("heightAboveGround", 10),
    "msl": ("meanSea", None),
    "tp": ("surface", None),
    "z": ("surface", None),
    "lsm": ("surface", None),
}


def field_value(param: str, step: int, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Known synthetic field in GRIB units (lon in [-180, 180))."""
    if param == "2t":
        return 270.0 + 0.1 * lat + 0.01 * lon + 0.5 * step
    if param == "10u":
        return 3.0 + 0.01 * lon + 0.1 * step
    if param == "10v":
        return -2.0 + 0.01 * lat
    if param == "msl":
        return 101_000.0 + 10.0 * lat + 5.0 * step
    if param == "tp":
        return 0.0001 * step * (1.0 + 0.01 * (lat - 57.0))  # metres, non-decreasing in step
    if param == "z":
        return 9.80665 * (10.0 + lat)  # geopotential of (10 + lat) m
    if param == "lsm":
        return np.where(lon < 23.0, 0.0, 1.0)
    raise KeyError(param)


def write_grib(
    path: Path,
    fields: Sequence[tuple[str, int]],
    *,
    issue: dt.datetime = ISSUE,
    lon_first: float = 180.0,
    increment: float = 1.0,
    transform: Callable[[str, int, np.ndarray], np.ndarray] | None = None,
    gen_proc_id: int = 161,
) -> None:
    """Write synthetic global regular_ll GRIB2 messages for (param, step) pairs."""
    ni, nj = round(360 / increment), round(180 / increment) + 1
    with path.open("wb") as fh:
        for param, step in fields:
            h = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
            eccodes.codes_set(h, "centre", "ecmf")
            eccodes.codes_set(h, "dataDate", int(issue.strftime("%Y%m%d")))
            eccodes.codes_set(h, "dataTime", issue.hour * 100)
            for k, v in (
                ("Ni", ni),
                ("Nj", nj),
                ("latitudeOfFirstGridPointInDegrees", 90.0),
                ("latitudeOfLastGridPointInDegrees", -90.0),
                ("longitudeOfFirstGridPointInDegrees", lon_first),
                ("longitudeOfLastGridPointInDegrees", (lon_first + 360 - increment) % 360),
                ("iDirectionIncrementInDegrees", increment),
                ("jDirectionIncrementInDegrees", increment),
            ):
                eccodes.codes_set(h, k, v)
            level_type, level = LEVELS[param]
            eccodes.codes_set(h, "typeOfLevel", level_type)
            if level is not None:
                eccodes.codes_set(h, "level", level)
            if param == "tp":
                eccodes.codes_set(h, "stepType", "accum")
                eccodes.codes_set(h, "startStep", 0)
            else:
                eccodes.codes_set(h, "stepType", "instant")
            eccodes.codes_set(h, "endStep", step)
            eccodes.codes_set(h, "shortName", param)
            eccodes.codes_set(h, "generatingProcessIdentifier", gen_proc_id)
            eccodes.codes_set(h, "packingType", "grid_simple")
            eccodes.codes_set(h, "bitsPerValue", 24)
            eccodes.codes_set_values(h, np.zeros(ni * nj))  # size the data section first
            lat = np.asarray(eccodes.codes_get_array(h, "latitudes"))
            lon = np.asarray(eccodes.codes_get_array(h, "longitudes"))
            lon = ((lon + 180.0) % 360.0) - 180.0
            vals = field_value(param, step, lat, lon)
            if transform is not None:
                vals = transform(param, step, vals)
            eccodes.codes_set_values(h, vals)
            eccodes.codes_write(h, fh)
            eccodes.codes_release(h)


@dataclasses.dataclass
class FakeFetcher:
    """In-memory mirror: knows which steps exist and writes synthetic GRIB on retrieve."""

    name: str
    steps: set[int]
    fail_retrieve: bool = False
    lon_first: float = 180.0
    drop_param: str | None = None
    transform: Callable[[str, int, np.ndarray], np.ndarray] | None = None
    probes: int = 0
    retrieves: int = 0

    def has_step(self, model: ModelConfig, issue: dt.datetime, step: int) -> bool:
        self.probes += 1
        return step in self.steps

    def retrieve(
        self,
        model: ModelConfig,
        issue: dt.datetime,
        steps: Sequence[int],
        params: Sequence[str],
        target: Path,
    ) -> int:
        from pvt.ingest.ecmwf import SourceUnavailableError

        self.retrieves += 1
        if self.fail_retrieve:
            raise SourceUnavailableError(f"{self.name}: simulated outage")
        fields = [(p, s) for s in steps for p in params if p != self.drop_param]
        write_grib(target, fields, issue=issue, lon_first=self.lon_first, transform=self.transform)
        return target.stat().st_size


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Repository configuration with a small test area, 1-degree grid and 5 steps."""
    s = load_settings(REPO_ROOT / "config", data_root=tmp_path / "data")
    ecmwf = dataclasses.replace(s.ecmwf, area=TEST_AREA, steps_per_batch=2, probe_pause_seconds=0.0)
    models = {
        mid: dataclasses.replace(
            m,
            candidate_steps=TEST_STEPS,
            expected_steps=dict.fromkeys(m.runs_utc, TEST_STEPS),
        )
        for mid, m in s.models.items()
    }
    return dataclasses.replace(s, ecmwf=ecmwf, models=models)
