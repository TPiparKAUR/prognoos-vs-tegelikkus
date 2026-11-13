"""Persist the archive as GitHub Release assets (GitHub Actions variant only, ADR-010).

GitHub runners are ephemeral and the archive must not live in git history (docs/03
section 5), so each month gets a release ``ecmwf-archive-YYYY-MM`` whose assets are the
per-run Parquet files and manifests. The primary GitLab variant uses a mounted
``PVT_DATA_ROOT`` instead and does not need this script.

Usage (inside the workflow, with ``GH_TOKEN`` set)::

    python ci/github_release_sync.py pull --data-root data --days 5
    python ci/github_release_sync.py push --data-root data --since-file .sync-start
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from pvt.storage import ecmwf_grid_path, ecmwf_manifest_path, read_json
from pvt.timeutil import UTC, utc_now

LOG = logging.getLogger("release_sync")
ASSET_RE = re.compile(
    r"^(?P<model>[a-z0-9-]+)_(?P<tag>\d{8}T\d{2}Z)(?:_(?P<kind>grid|static))?\.(?:parquet|json)$"
)


def _gh(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], check=check, capture_output=True, text=True)


def release_tag(issue: dt.datetime) -> str:
    """Release holding the runs issued in ``issue``'s month."""
    return f"ecmwf-archive-{issue:%Y-%m}"


def local_path(data_root: Path, asset: str) -> Path:
    """Map a flat asset name back to its archive path."""
    m = ASSET_RE.match(asset)
    if not m:
        raise ValueError(f"unexpected asset name {asset!r}")
    issue = dt.datetime.strptime(m["tag"], "%Y%m%dT%HZ").replace(tzinfo=UTC)
    if m["kind"]:
        return ecmwf_grid_path(data_root, m["model"], issue, m["kind"])
    return ecmwf_manifest_path(data_root, m["model"], issue)


def pull(data_root: Path, days: int) -> None:
    """Download the assets of the last ``days`` days into the archive tree."""
    today = utc_now()
    for d in range(days + 1):
        day = today - dt.timedelta(days=d)
        with tempfile.TemporaryDirectory() as tmp:
            r = _gh(
                "release",
                "download",
                release_tag(day),
                "--dir",
                tmp,
                "--pattern",
                f"*_{day:%Y%m%d}T*",
                check=False,
            )
            if r.returncode != 0:
                LOG.info("nothing for %s (%s)", f"{day:%Y-%m-%d}", r.stderr.strip()[:200])
                continue
            for f in Path(tmp).iterdir():
                dest = local_path(data_root, f.name)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(f, dest)
                LOG.info("restored %s", dest.relative_to(data_root))


def push(data_root: Path, since_file: Path) -> None:
    """Upload manifests (and their files) changed after ``since_file`` was touched."""
    since = since_file.stat().st_mtime
    base = data_root / "manifests"
    for mpath in sorted(base.rglob("*.json")) if base.exists() else []:
        if mpath.stat().st_mtime < since:
            continue
        man = read_json(mpath)
        issue = dt.datetime.strptime(man["issue_time_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
        tag = release_tag(issue)
        if _gh("release", "view", tag, check=False).returncode != 0:
            _gh(
                "release",
                "create",
                tag,
                "--title",
                tag,
                "--notes",
                "ECMWF open data (CC BY 4.0) regional sub-grid archive. Experimental, "
                "unofficial. Data assets only; not a software release.",
            )
        files = [str(data_root / f["path"]) for f in man.get("files", {}).values()]
        _gh("release", "upload", tag, "--clobber", *files, str(mpath))
        LOG.info("uploaded %s (%s, %d files)", mpath.name, man["status"], len(files) + 1)


def main(argv: list[str] | None = None) -> int:
    """Command line entry point."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("pull")
    pl.add_argument("--data-root", type=Path, required=True)
    pl.add_argument("--days", type=int, default=5)
    ps = sub.add_parser("push")
    ps.add_argument("--data-root", type=Path, required=True)
    ps.add_argument("--since-file", type=Path, required=True)
    a = p.parse_args(argv)
    try:
        if a.cmd == "pull":
            pull(a.data_root, a.days)
        else:
            push(a.data_root, a.since_file)
    except subprocess.CalledProcessError as exc:
        LOG.error("gh failed: %s", exc.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
