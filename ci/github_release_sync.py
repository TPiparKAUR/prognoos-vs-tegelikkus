"""Persist the archive as GitHub Release assets (GitHub Actions runtime, ADR-010).

GitHub runners are ephemeral and the archive must not live in git history (docs/03 §5).
Every dataset-day directory ``<data_root>/<dataset>/YYYY/MM/DD`` is stored as one tar
asset ``<dataset>_<YYYY-MM-DD>.tar`` in the monthly release ``archive-YYYY-MM``; the
station registry ``<data_root>/meta`` is stored as ``meta.tar`` in release ``archive-meta``.

Usage inside a workflow (``GH_TOKEN`` set)::

    python ci/github_release_sync.py pull --data-root data --dataset ecmwf --days 5
    touch .sync-start
    ... run pvt ...
    python ci/github_release_sync.py push --data-root data --since-file .sync-start
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import logging
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from pvt.storage import DAY_DATASETS, day_dir
from pvt.timeutil import utc_now

LOG = logging.getLogger("release_sync")
META_TAG = "archive-meta"
META_ASSET = "meta.tar"
NOTES = (
    "Data archive of the experimental, unofficial project 'Prognoos vs tegelikkus'. "
    "Contains derived station extracts of ECMWF open data (CC BY 4.0, (c) ECMWF) and "
    "KAUR observations/forecasts (source: Keskkonnaagentuur, https://www.ilmateenistus.ee; "
    "climate data CC BY 4.0). Not a software release."
)


def _gh(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], check=check, capture_output=True, text=True)


def release_tag(day: dt.date) -> str:
    """Monthly release holding the dataset-day bundles of ``day``."""
    return f"archive-{day:%Y-%m}"


def asset_name(dataset: str, day: dt.date) -> str:
    """Asset name of one dataset-day bundle."""
    return f"{dataset}_{day:%Y-%m-%d}.tar"


def build_tar(data_root: Path, directory: Path) -> bytes:
    """Deterministic tar of ``directory`` with member names relative to ``data_root``."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for path in sorted(p for p in directory.rglob("*") if p.is_file()):
            info = tarfile.TarInfo(str(path.relative_to(data_root)))
            info.size = path.stat().st_size
            info.mtime = 0
            info.mode = 0o644
            with path.open("rb") as fh:
                tar.addfile(info, fh)
    return buf.getvalue()


def extract_tar(data_root: Path, tar_path: Path) -> int:
    """Extract a bundle safely (``data`` filter: no absolute paths, links or devices)."""
    with tarfile.open(tar_path) as tar:
        members = tar.getmembers()
        tar.extractall(data_root, filter="data")
    return len(members)


def _download(tag: str, asset: str, dest: Path) -> bool:
    r = _gh(
        "release", "download", tag, "--pattern", asset, "--dir", str(dest), "--clobber", check=False
    )
    if r.returncode != 0:
        LOG.info("no %s in %s (%s)", asset, tag, r.stderr.strip()[:160])
        return False
    return True


def pull(data_root: Path, datasets: list[str], days: int) -> None:
    """Restore the last ``days`` days of ``datasets`` and the station registry."""
    data_root.mkdir(parents=True, exist_ok=True)
    today = utc_now().date()
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        if _download(META_TAG, META_ASSET, t):
            LOG.info("restored meta (%d files)", extract_tar(data_root, t / META_ASSET))
        for ds in datasets:
            for d in range(days + 1):
                day = today - dt.timedelta(days=d)
                name = asset_name(ds, day)
                if _download(release_tag(day), name, t):
                    LOG.info("restored %s (%d files)", name, extract_tar(data_root, t / name))


def _ensure_release(tag: str) -> None:
    if _gh("release", "view", tag, check=False).returncode != 0:
        _gh("release", "create", tag, "--title", tag, "--notes", NOTES, "--latest=false")


def changed_day_dirs(data_root: Path, since: float) -> set[tuple[str, dt.date]]:
    """Dataset-days containing a file modified after ``since`` (POSIX time)."""
    out: set[tuple[str, dt.date]] = set()
    for ds in DAY_DATASETS:
        base = data_root / ds
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.stat().st_mtime >= since:
                y, m, d = p.relative_to(base).parts[:3]
                out.add((ds, dt.date(int(y), int(m), int(d))))
    return out


def push(data_root: Path, since_file: Path) -> None:
    """Upload every dataset-day bundle (and meta) that changed during this job."""
    since = since_file.stat().st_mtime
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        for ds, day in sorted(changed_day_dirs(data_root, since)):
            name = asset_name(ds, day)
            (t / name).write_bytes(build_tar(data_root, day_dir(data_root, ds, day)))
            _ensure_release(release_tag(day))
            _gh("release", "upload", release_tag(day), str(t / name), "--clobber")
            LOG.info("uploaded %s", name)
        meta = data_root / "meta"
        if meta.exists() and any(p.stat().st_mtime >= since for p in meta.rglob("*")):
            (t / META_ASSET).write_bytes(build_tar(data_root, meta))
            _ensure_release(META_TAG)
            _gh("release", "upload", META_TAG, str(t / META_ASSET), "--clobber")
            LOG.info("uploaded %s", META_ASSET)


def main(argv: list[str] | None = None) -> int:
    """Command line entry point."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("pull")
    pl.add_argument("--data-root", type=Path, required=True)
    pl.add_argument("--dataset", action="append", choices=DAY_DATASETS, default=[])
    pl.add_argument("--days", type=int, default=5)
    ps = sub.add_parser("push")
    ps.add_argument("--data-root", type=Path, required=True)
    ps.add_argument("--since-file", type=Path, required=True)
    a = p.parse_args(argv)
    try:
        if a.cmd == "pull":
            pull(a.data_root, a.dataset, a.days)
        else:
            push(a.data_root, a.since_file)
    except subprocess.CalledProcessError as exc:
        LOG.error("gh failed: %s", exc.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
