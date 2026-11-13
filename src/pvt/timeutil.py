"""Timezone-aware UTC helpers. Naive datetimes are rejected everywhere."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

UTC = dt.UTC


class NaiveDatetimeError(ValueError):
    """Raised when a naive (timezone-unaware) datetime is passed where UTC is required."""


def require_utc(value: dt.datetime) -> dt.datetime:
    """Return ``value`` converted to UTC, refusing naive datetimes.

    Parameters
    ----------
    value : datetime.datetime
        A timezone-aware datetime.

    Returns
    -------
    datetime.datetime
        The same instant expressed in UTC.

    Raises
    ------
    NaiveDatetimeError
        If ``value`` has no timezone information.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise NaiveDatetimeError(f"naive datetime not allowed: {value!r}")
    return value.astimezone(UTC)


def utc_now() -> dt.datetime:
    """Return the current time as an aware UTC datetime, truncated to seconds."""
    return dt.datetime.now(UTC).replace(microsecond=0)


def parse_utc(text: str) -> dt.datetime:
    """Parse an ISO 8601 string that carries an explicit offset (``Z`` allowed).

    Parameters
    ----------
    text : str
        For example ``"2026-11-12T06:00:00Z"`` or ``"2026-11-12T06Z"``.

    Returns
    -------
    datetime.datetime
        Aware datetime in UTC.

    Raises
    ------
    NaiveDatetimeError
        If the string has no offset.
    ValueError
        If the string is not ISO 8601.
    """
    raw = text.strip()
    # Accept the compact "YYYY-MM-DDTHHZ" form used on the command line.
    if len(raw) == 14 and raw[10] == "T" and raw.endswith("Z"):
        raw = raw[:-1] + ":00:00Z"
    parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return require_utc(parsed)


def format_utc(value: dt.datetime) -> str:
    """Format an aware datetime as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return require_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_tag(issue_time: dt.datetime) -> str:
    """Return the compact run tag used in file names, e.g. ``20261112T06Z``."""
    return require_utc(issue_time).strftime("%Y%m%dT%HZ")


def floor_to_run(value: dt.datetime, hours: tuple[int, ...] = (0, 6, 12, 18)) -> dt.datetime:
    """Return the latest run start (one of ``hours``) at or before ``value``."""
    v = require_utc(value).replace(minute=0, second=0, microsecond=0)
    for back in range(25):
        cand = v - dt.timedelta(hours=back)
        if cand.hour in hours:
            return cand
    raise ValueError(f"no run hour in {hours!r}")


def iter_runs(
    start: dt.datetime, end: dt.datetime, hours: tuple[int, ...] = (0, 6, 12, 18)
) -> Iterator[dt.datetime]:
    """Yield run start times in ``[start, end]`` (inclusive), newest first.

    Parameters
    ----------
    start, end : datetime.datetime
        Aware datetimes bounding the window.
    hours : tuple of int
        Run hours (UTC).
    """
    s = require_utc(start)
    cur = floor_to_run(require_utc(end), hours)
    while cur >= s:
        yield cur
        cur = floor_to_run(cur - dt.timedelta(hours=1), hours)
