"""Dataset-day bundles of the GitHub release persistence helper."""

from __future__ import annotations

import datetime as dt
import os
import time
from pathlib import Path

import pytest

from ci.github_release_sync import (
    asset_name,
    build_tar,
    changed_day_dirs,
    extract_tar,
    release_tag,
)
from pvt.storage import day_dir, ecmwf_grid_path
from pvt.timeutil import UTC

DAY = dt.date(2026, 11, 12)


def test_names() -> None:
    assert release_tag(DAY) == "archive-2026-11"
    assert asset_name("ecmwf", DAY) == "ecmwf_2026-11-12.tar"


def test_tar_round_trip_is_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "data"
    f = ecmwf_grid_path(root, "ifs", dt.datetime(2026, 11, 12, 6, tzinfo=UTC), "point")
    f.parent.mkdir(parents=True)
    f.write_bytes(b"abc")
    (f.parent / "x.json").write_text("{}")
    blob = build_tar(root, day_dir(root, "ecmwf", DAY))
    os.utime(f, (1, 1))
    assert build_tar(root, day_dir(root, "ecmwf", DAY)) == blob  # mtime-independent
    tar_path = tmp_path / "b.tar"
    tar_path.write_bytes(blob)
    out = tmp_path / "restored"
    assert extract_tar(out, tar_path) == 2
    assert (out / f.relative_to(root)).read_bytes() == b"abc"


def test_changed_day_dirs(tmp_path: Path) -> None:
    root = tmp_path / "data"
    old = day_dir(root, "obs_xml", DAY) / "a.parquet"
    old.parent.mkdir(parents=True)
    old.write_text("x")
    os.utime(old, (1, 1))
    since = time.time() - 1
    new = day_dir(root, "kliima", DAY) / "b.parquet"
    new.parent.mkdir(parents=True)
    new.write_text("y")
    assert changed_day_dirs(root, since) == {("kliima", DAY)}


def test_unknown_dataset_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown dataset"):
        day_dir(tmp_path, "nope", DAY)
