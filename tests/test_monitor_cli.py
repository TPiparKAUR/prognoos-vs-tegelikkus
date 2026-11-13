"""Monitor (freshness, inventory), CLI behaviour and repository-wide static rules."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pytest

from pvt.cli import EXIT_USAGE, main
from pvt.config import REPO_ROOT, Settings
from pvt.ingest.ecmwf import ingest
from pvt.monitor.freshness import EXIT_OK, EXIT_STALE, run_monitor
from pvt.storage import read_json
from tests.conftest import ISSUE, TEST_STEPS, FakeFetcher


def _archive(settings: Settings, issues: list[dt.datetime]) -> None:
    f = FakeFetcher("aws", set(TEST_STEPS))
    for issue in issues:
        ingest(
            settings,
            ["ifs", "aifs-single"],
            start=issue,
            end=issue,
            now=issue + dt.timedelta(hours=20),
            fetchers=[f],
        )


def test_monitor_ok_when_fresh(settings: Settings) -> None:
    _archive(settings, [ISSUE])
    out = run_monitor(settings, now=ISSUE + dt.timedelta(hours=10))
    assert out.exit_code == EXIT_OK
    src = out.freshness["sources"]
    assert src["ecmwf:ifs"]["status"] == "ok"
    assert src["ecmwf:ifs"]["age_hours"] == 10.0
    assert src["obs_xml"]["status"] == "not_implemented"
    assert (settings.data_root / "status" / "freshness.json").exists()


def test_monitor_fails_when_stale(settings: Settings) -> None:
    _archive(settings, [ISSUE])
    out = run_monitor(settings, now=ISSUE + dt.timedelta(hours=30))
    assert out.exit_code == EXIT_STALE
    assert any("stale" in p for p in out.freshness["problems"])


def test_monitor_fails_with_empty_archive(settings: Settings) -> None:
    out = run_monitor(settings, now=ISSUE)
    assert out.exit_code == EXIT_STALE


def test_inventory_lists_missing_runs_with_reason(settings: Settings) -> None:
    _archive(settings, [ISSUE])
    now = ISSUE + dt.timedelta(hours=14 + 13)  # window ends at ISSUE + 13 h
    out = run_monitor(settings, now=now)
    inv = out.inventory["models"]["ifs"]
    assert inv["runs_complete"] == 1
    assert inv["window_fully_covered"] is False  # archive started inside the window
    missing = {r["issue_time_utc"]: r for r in inv["runs_not_complete"]}
    assert "2026-11-12T12:00:00Z" in missing
    assert missing["2026-11-12T12:00:00Z"]["status"] == "no_manifest"
    saved = read_json(settings.data_root / "status" / "ecmwf_inventory.json")
    assert saved["models"]["ifs"]["runs_complete"] == 1


@pytest.mark.parametrize(
    "step",
    ["ingest-obs-xml", "ingest-kliima", "ingest-kaur-fc", "pair", "score", "mos", "build-site"],
)
def test_pending_steps_exit_with_usage_code(step: str) -> None:
    assert main([step]) == EXIT_USAGE


def test_unknown_model_is_usage_error(tmp_path: Path) -> None:
    assert main(["--data-root", str(tmp_path), "ingest-ecmwf", "--model", "gfs"]) == EXIT_USAGE


def test_cli_monitor_on_empty_archive(tmp_path: Path) -> None:
    assert main(["--data-root", str(tmp_path), "monitor"]) == EXIT_STALE


# ------------------------------------------------------------------ static rules


def _source_files() -> list[Path]:
    return sorted((REPO_ROOT / "src").rglob("*.py"))


def test_no_shuffled_or_random_splits_in_code() -> None:
    """docs/06 section 4 criterion 4: no random train/test split anywhere in src/."""
    pattern = re.compile(r"shuffle\s*=\s*True|train_test_split|KFold\(|ShuffleSplit")
    offenders = [str(p) for p in _source_files() if pattern.search(p.read_text("utf-8"))]
    assert offenders == []


def test_no_naive_now_in_code() -> None:
    pattern = re.compile(r"datetime\.(utcnow|now)\(\s*\)|\.utcfromtimestamp\(")
    offenders = [str(p) for p in _source_files() if pattern.search(p.read_text("utf-8"))]
    assert offenders == []


def test_no_grib_files_tracked() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text("utf-8")
    assert "*.grib2" in gitignore
    assert "/data/" in gitignore
