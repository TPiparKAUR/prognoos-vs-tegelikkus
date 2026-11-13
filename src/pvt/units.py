"""Explicit unit conversions. Every conversion is named; nothing is converted implicitly.

GRIB unit strings are taken from the ecCodes ``units`` key. Unknown units raise
:class:`UnitError` instead of guessing.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]

#: Standard gravity used by ECMWF to convert geopotential to height (m s-2).
STANDARD_GRAVITY_M_S2: Final = 9.80665
KELVIN_OFFSET: Final = 273.15


class UnitError(ValueError):
    """Raised when a source unit is not one this code knows how to convert."""


# Target unit per archived quantity and the conversion from each accepted GRIB unit.
_CONVERSIONS: Final[dict[tuple[str, str], tuple[str, float, float]]] = {
    # (quantity, grib unit): (target unit, scale, offset)  -> target = value * scale + offset
    ("temperature", "K"): ("degC", 1.0, -KELVIN_OFFSET),
    ("pressure", "Pa"): ("hPa", 0.01, 0.0),
    ("wind", "m s**-1"): ("m_s", 1.0, 0.0),
    # IFS open data: tp in metres of water equivalent.
    ("precipitation", "m"): ("mm", 1000.0, 0.0),
    # AIFS open data: tp in kg m-2, numerically equal to mm of water.
    ("precipitation", "kg m**-2"): ("mm", 1.0, 0.0),
    ("geopotential", "m**2 s**-2"): ("m", 1.0 / STANDARD_GRAVITY_M_S2, 0.0),
    ("fraction", "(0 - 1)"): ("frac", 1.0, 0.0),
}


def convert(quantity: str, grib_units: str, values: FloatArray) -> tuple[str, FloatArray]:
    """Convert ``values`` given in ``grib_units`` to the canonical unit of ``quantity``.

    Parameters
    ----------
    quantity : str
        One of ``temperature``, ``pressure``, ``wind``, ``precipitation``,
        ``geopotential``, ``fraction``.
    grib_units : str
        Value of the ecCodes ``units`` key, e.g. ``"K"`` or ``"kg m**-2"``.
    values : numpy.ndarray
        Values in ``grib_units``.

    Returns
    -------
    tuple of (str, numpy.ndarray)
        Target unit label and converted values.

    Raises
    ------
    UnitError
        If the (quantity, unit) pair is unknown.
    """
    try:
        target, scale, offset = _CONVERSIONS[(quantity, grib_units)]
    except KeyError as exc:
        raise UnitError(f"no conversion for {quantity!r} in unit {grib_units!r}") from exc
    out: FloatArray = values * scale + offset
    return target, out
