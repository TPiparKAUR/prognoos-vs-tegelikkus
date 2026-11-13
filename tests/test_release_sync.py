"""Asset name <-> archive path mapping of the GitHub release persistence helper."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from ci.github_release_sync import local_path, release_tag
from pvt.storage import ecmwf_grid_path, ecmwf_manifest_path
from pvt.timeutil import UTC

ISSUE = dt.datetime(2026, 11, 12, 18, tzinfo=UTC)


@pytest.mark.parametrize("model", ["ifs", "aifs-single"])
def test_asset_names_round_trip(tmp_path: Path, model: str) -> None:
    for kind in ("grid", "static"):
        p = ecmwf_grid_path(tmp_path, model, ISSUE, kind)
        assert local_path(tmp_path, p.name) == p
    m = ecmwf_manifest_path(tmp_path, model, ISSUE)
    assert local_path(tmp_path, m.name) == m


def test_release_tag_by_issue_month() -> None:
    assert release_tag(ISSUE) == "ecmwf-archive-2026-11"


def test_unexpected_asset_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unexpected"):
        local_path(tmp_path, "../../etc/passwd")
