"""Atomic, deterministic file output (Parquet and JSON) and archive paths."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import polars as pl

from pvt.timeutil import require_utc, run_tag

# Fixed writer options so that identical content gives identical bytes.
_PARQUET_OPTS: dict[str, Any] = {
    "compression": "zstd",
    "compression_level": 9,
    "statistics": True,
    "row_group_size": 1_000_000,
}


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of a file."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_target(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    return Path(tmp)


def write_parquet_atomic(df: pl.DataFrame, path: Path) -> str:
    """Write ``df`` to ``path`` atomically and return the SHA-256 of the file.

    The file is written to a temporary name in the same directory and renamed, so a
    crash never leaves a truncated Parquet file behind.
    """
    tmp = _atomic_target(path)
    try:
        df.write_parquet(tmp, **_PARQUET_OPTS)
        digest = sha256_file(tmp)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return digest


def write_json_atomic(obj: Any, path: Path) -> None:
    """Write ``obj`` as pretty, key-sorted UTF-8 JSON atomically."""
    tmp = _atomic_target(path)
    try:
        tmp.write_text(
            json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path: Path) -> Any:
    """Read a JSON file written by :func:`write_json_atomic`."""
    return json.loads(path.read_text(encoding="utf-8"))


def ecmwf_grid_path(data_root: Path, model_id: str, issue_time: dt.datetime, kind: str) -> Path:
    """Archive path of one run (ADR-009 partitioning ``source/model/year/month``).

    Parameters
    ----------
    data_root : pathlib.Path
        Root of the data archive.
    model_id : str
        ``ifs`` or ``aifs-single``.
    issue_time : datetime.datetime
        Run start (aware).
    kind : str
        ``grid`` (per-step fields) or ``static`` (orography, land-sea mask).
    """
    t = require_utc(issue_time)
    return (
        data_root
        / f"forecast_{kind}"
        / "source=ecmwf_opendata"
        / f"model={model_id}"
        / f"year={t:%Y}"
        / f"month={t:%m}"
        / f"{model_id}_{run_tag(t)}_{kind}.parquet"
    )


def ecmwf_manifest_path(data_root: Path, model_id: str, issue_time: dt.datetime) -> Path:
    """Path of the per-run manifest (status, steps, hashes, retrieval metadata)."""
    t = require_utc(issue_time)
    return (
        data_root
        / "manifests"
        / "ecmwf_opendata"
        / f"model={model_id}"
        / f"year={t:%Y}"
        / f"{model_id}_{run_tag(t)}.json"
    )
