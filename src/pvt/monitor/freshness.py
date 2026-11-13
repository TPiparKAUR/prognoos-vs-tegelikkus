"""`pvt monitor`: archive freshness and run inventory (docs/03 section 7).

Writes ``status/freshness.json`` and ``status/ecmwf_inventory.json`` under the data
root and returns a non-zero exit code when the pipeline should turn red.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pvt.config import Settings
from pvt.storage import read_json, write_json_atomic
from pvt.timeutil import format_utc, iter_runs, parse_utc, require_utc, run_tag, utc_now

LOG = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_STALE = 1


@dataclass(frozen=True)
class MonitorOutcome:
    """Result of a monitor pass."""

    exit_code: int
    freshness: dict[str, Any]
    inventory: dict[str, Any]


def _load_manifests(root: Path, model_id: str) -> dict[str, dict[str, Any]]:
    base = root / "ecmwf"
    out: dict[str, dict[str, Any]] = {}
    if base.exists():
        for p in sorted(base.rglob(f"{model_id}_*.json")):
            m = read_json(p)
            out[m["issue_time_utc"]] = m
    return out


def run_monitor(settings: Settings, now: dt.datetime | None = None) -> MonitorOutcome:
    """Compute freshness and the run inventory; write status JSON files.

    Parameters
    ----------
    settings : Settings
        Loaded configuration.
    now : datetime.datetime, optional
        Current time (injected for tests).

    Returns
    -------
    MonitorOutcome
        ``exit_code`` is 1 if any implemented source is stale, or if the completeness
        over a fully covered inventory window is below the configured fraction.
    """
    now = require_utc(now or utc_now())
    ms = settings.monitor
    problems: list[str] = []
    sources: dict[str, Any] = {}
    models_inv: dict[str, Any] = {}

    win_end = now - dt.timedelta(hours=settings.ecmwf.partial_after_hours)
    win_start = win_end - dt.timedelta(days=ms.inventory_days)

    for model_id, model in settings.models.items():
        manifests = _load_manifests(settings.data_root, model_id)
        complete = {k: v for k, v in manifests.items() if v.get("status") == "complete"}
        latest = max((parse_utc(k) for k in complete), default=None)
        age_h = None if latest is None else round((now - latest).total_seconds() / 3600, 2)
        stale = age_h is None or age_h > ms.max_age_hours_ecmwf
        sources[f"ecmwf:{model_id}"] = {
            "status": "stale" if stale else "ok",
            "latest_complete_issue_utc": None if latest is None else format_utc(latest),
            "age_hours": age_h,
            "threshold_hours": ms.max_age_hours_ecmwf,
        }
        if stale:
            problems.append(f"ecmwf:{model_id} stale (age {age_h} h)")

        expected_runs = list(
            iter_runs(max(win_start, model.min_issue_time), win_end, model.runs_utc)
        )
        rows = []
        for issue in sorted(expected_runs):
            m = manifests.get(format_utc(issue))
            rows.append(
                {
                    "issue_time_utc": format_utc(issue),
                    "status": m["status"] if m else "no_manifest",
                    "detail": (m or {}).get("detail", "no ingest attempt recorded"),
                    "steps_missing": (m or {}).get("steps_missing"),
                    "attempts": (m or {}).get("attempts", 0),
                }
            )
        n_exp = len(rows)
        n_ok = sum(r["status"] == "complete" for r in rows)
        first_attempt = min(
            (parse_utc(m["first_attempt_utc"]) for m in manifests.values()), default=None
        )
        covered = first_attempt is not None and first_attempt <= win_start
        frac = round(n_ok / n_exp, 4) if n_exp else None
        gen_ids = sorted({g for m in complete.values() for g in m.get("grib_gen_proc_id", [])})
        if len(gen_ids) > 1:
            LOG.warning(
                "%s: generatingProcessIdentifier changed within archive: %s "
                "(possible model change; check model_cycles in params.toml)",
                model_id,
                gen_ids,
            )
        models_inv[model_id] = {
            "window_start_utc": format_utc(win_start),
            "window_end_utc": format_utc(win_end),
            "runs_expected": n_exp,
            "runs_complete": n_ok,
            "completeness_fraction": frac,
            "window_fully_covered": covered,
            "grib_gen_proc_ids_seen": gen_ids,
            "runs_not_complete": [r for r in rows if r["status"] != "complete"],
        }
        if covered and frac is not None and frac < ms.min_completeness_fraction:
            problems.append(
                f"ecmwf:{model_id} completeness {frac} < {ms.min_completeness_fraction}"
            )
        for r in rows:
            if r["status"] != "complete":
                LOG.info(
                    "%s %s: %s (%s)",
                    model_id,
                    run_tag(parse_utc(r["issue_time_utc"])),
                    r["status"],
                    r["detail"],
                )

    for name in ("obs_xml", "kliima", "kaur_fc"):
        sources[name] = {"status": "not_implemented"}

    freshness = {
        "generated_at_utc": format_utc(now),
        "sources": sources,
        "problems": problems,
    }
    inventory = {"generated_at_utc": format_utc(now), "models": models_inv}
    status_dir = settings.data_root / "status"
    write_json_atomic(freshness, status_dir / "freshness.json")
    write_json_atomic(inventory, status_dir / "ecmwf_inventory.json")
    for p in problems:
        LOG.error("monitor: %s", p)
    code = EXIT_STALE if problems else EXIT_OK
    LOG.info("monitor: %s", "OK" if code == EXIT_OK else f"{len(problems)} problem(s)")
    return MonitorOutcome(code, freshness, inventory)
