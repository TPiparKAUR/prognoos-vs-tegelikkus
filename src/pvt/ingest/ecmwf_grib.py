"""Decode ECMWF open-data GRIB2 files and cut out the regional sub-grid.

Grid coordinates are always read from the GRIB message (``latitudes`` /
``longitudes`` arrays), never assumed: AIFS v2 open data changed its longitude
convention once (docs/07 R4). Longitudes are normalised to [-180, 180).
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import eccodes
import numpy as np
import numpy.typing as npt

from pvt.config import Area
from pvt.timeutil import UTC

LOG = logging.getLogger(__name__)

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]

#: Accepted (shortName, typeOfLevel) combinations -> physical quantity used by pvt.units.
ACCEPTED: Final[dict[tuple[str, str], str]] = {
    ("2t", "heightAboveGround"): "temperature",
    ("10u", "heightAboveGround"): "wind",
    ("10v", "heightAboveGround"): "wind",
    ("msl", "meanSea"): "pressure",
    ("tp", "surface"): "precipitation",
    ("z", "surface"): "geopotential",
    ("lsm", "surface"): "fraction",
}

_COORD_TOL: Final = 1e-6


class GribContentError(ValueError):
    """Raised when GRIB content is not what the ingest expects."""


@dataclass(frozen=True)
class GridSignature:
    """Geometry of a regular lat/lon GRIB grid, used to cache box masks."""

    ni: int
    nj: int
    lat_first: float
    lon_first: float
    lat_last: float
    lon_last: float
    di: float
    dj: float


@dataclass
class BoxField:
    """One GRIB message reduced to the regional box."""

    short_name: str
    quantity: str
    units: str
    issue_time: dt.datetime
    valid_time: dt.datetime
    start_step_h: int
    end_step_h: int
    step_type: str
    gen_proc_id: int
    lat_deg: FloatArray
    lon_deg: FloatArray
    values: FloatArray


@dataclass
class BoxExtractor:
    """Extract the configured area from GRIB messages, caching masks per grid geometry."""

    area: Area
    _masks: dict[GridSignature, tuple[BoolArray, FloatArray, FloatArray, npt.NDArray[np.intp]]] = (
        field(default_factory=dict)
    )

    def _mask(
        self, gid: int, sig: GridSignature
    ) -> tuple[BoolArray, FloatArray, FloatArray, npt.NDArray[np.intp]]:
        cached = self._masks.get(sig)
        if cached is not None:
            return cached
        lat = np.asarray(eccodes.codes_get_array(gid, "latitudes"), dtype=np.float64)
        lon = normalise_lon(
            np.asarray(eccodes.codes_get_array(gid, "longitudes"), dtype=np.float64)
        )
        a = self.area
        mask = (
            (lat >= a.lat_min_deg - _COORD_TOL)
            & (lat <= a.lat_max_deg + _COORD_TOL)
            & (lon >= a.lon_min_deg - _COORD_TOL)
            & (lon <= a.lon_max_deg + _COORD_TOL)
        )
        idx = np.flatnonzero(mask)
        # Deterministic order: north to south, west to east.
        order = np.lexsort((lon[idx], -lat[idx]))
        idx = idx[order]
        expected = expected_box_size(a)
        if idx.size != expected:
            raise GribContentError(
                f"box has {idx.size} grid points, expected {expected} for {a} on grid {sig}"
            )
        result = (mask, np.round(lat[idx], 6), np.round(lon[idx], 6), idx)
        self._masks[sig] = result
        return result

    def extract(self, gid: int) -> tuple[FloatArray, FloatArray, FloatArray]:
        """Return (lat, lon, values) of the box for an open GRIB handle."""
        if eccodes.codes_get(gid, "gridType") != "regular_ll":
            raise GribContentError("only regular_ll grids are supported")
        sig = GridSignature(
            ni=int(eccodes.codes_get(gid, "Ni")),
            nj=int(eccodes.codes_get(gid, "Nj")),
            lat_first=float(eccodes.codes_get(gid, "latitudeOfFirstGridPointInDegrees")),
            lon_first=float(eccodes.codes_get(gid, "longitudeOfFirstGridPointInDegrees")),
            lat_last=float(eccodes.codes_get(gid, "latitudeOfLastGridPointInDegrees")),
            lon_last=float(eccodes.codes_get(gid, "longitudeOfLastGridPointInDegrees")),
            di=float(eccodes.codes_get(gid, "iDirectionIncrementInDegrees")),
            dj=float(eccodes.codes_get(gid, "jDirectionIncrementInDegrees")),
        )
        inc = self.area.grid_increment_deg
        if abs(sig.di - inc) > _COORD_TOL or abs(sig.dj - inc) > _COORD_TOL:
            raise GribContentError(f"grid increment {sig.di}/{sig.dj} != configured {inc}")
        _, lat, lon, idx = self._mask(gid, sig)
        values = np.asarray(eccodes.codes_get_values(gid), dtype=np.float64)
        if eccodes.codes_get(gid, "numberOfMissing") and np.any(
            values[idx] == eccodes.codes_get(gid, "missingValue")
        ):
            raise GribContentError("missing values inside the regional box")
        return lat, lon, values[idx]


def normalise_lon(lon: FloatArray) -> FloatArray:
    """Map longitudes to [-180, 180)."""
    out: FloatArray = ((lon + 180.0) % 360.0) - 180.0
    return out


def expected_box_size(area: Area) -> int:
    """Return the number of grid points inside ``area`` (inclusive bounds)."""
    inc = area.grid_increment_deg
    nlat = round((area.lat_max_deg - area.lat_min_deg) / inc) + 1
    nlon = round((area.lon_max_deg - area.lon_min_deg) / inc) + 1
    return nlat * nlon


def _grib_datetime(date: int, time: int) -> dt.datetime:
    return dt.datetime(
        date // 10000, (date // 100) % 100, date % 100, time // 100, time % 100, tzinfo=UTC
    )


def read_box_fields(path: Path, extractor: BoxExtractor) -> list[BoxField]:
    """Read all accepted messages of a GRIB file and reduce them to the box.

    Messages whose (shortName, typeOfLevel) is not in :data:`ACCEPTED` are skipped
    (e.g. pressure-level ``z``).

    Parameters
    ----------
    path : pathlib.Path
        GRIB2 file.
    extractor : BoxExtractor
        Area definition and mask cache.

    Returns
    -------
    list of BoxField
    """
    fields: list[BoxField] = []
    skipped = 0
    with path.open("rb") as fh:
        while True:
            gid = eccodes.codes_grib_new_from_file(fh)
            if gid is None:
                break
            try:
                key = (
                    str(eccodes.codes_get(gid, "shortName")),
                    str(eccodes.codes_get(gid, "typeOfLevel")),
                )
                quantity = ACCEPTED.get(key)
                if quantity is None:
                    skipped += 1
                    continue
                lat, lon, values = extractor.extract(gid)
                fields.append(
                    BoxField(
                        short_name=key[0],
                        quantity=quantity,
                        units=str(eccodes.codes_get(gid, "units")),
                        issue_time=_grib_datetime(
                            int(eccodes.codes_get(gid, "dataDate")),
                            int(eccodes.codes_get(gid, "dataTime")),
                        ),
                        valid_time=_grib_datetime(
                            int(eccodes.codes_get(gid, "validityDate")),
                            int(eccodes.codes_get(gid, "validityTime")),
                        ),
                        start_step_h=int(eccodes.codes_get(gid, "startStep")),
                        end_step_h=int(eccodes.codes_get(gid, "endStep")),
                        step_type=str(eccodes.codes_get(gid, "stepType")),
                        gen_proc_id=int(eccodes.codes_get(gid, "generatingProcessIdentifier")),
                        lat_deg=lat,
                        lon_deg=lon,
                        values=values,
                    )
                )
            finally:
                eccodes.codes_release(gid)
    if skipped:
        LOG.debug("skipped %d non-target messages in %s", skipped, path.name)
    return fields
