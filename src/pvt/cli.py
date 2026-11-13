"""Command line entry point: ``pvt <step>``.

Every step is idempotent. Exit codes: 0 ok, 1 data/monitor problem, 2 usage error or
step not implemented yet, 3 configuration error.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from pvt import __version__
from pvt.config import ConfigError, Settings, load_settings
from pvt.timeutil import parse_utc

LOG = logging.getLogger("pvt")

EXIT_OK, EXIT_PROBLEM, EXIT_USAGE, EXIT_CONFIG = 0, 1, 2, 3

# Steps defined in docs/08 that later stages implement.
_PENDING_STEPS = {
    "mos": "E5",
}


def setup_logging(level: str) -> None:
    """Configure root logging with UTC ISO 8601 timestamps."""
    fmt = logging.Formatter(
        "%(asctime)sZ %(levelname)s %(name)s: %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"
    )
    fmt.converter = time.gmtime
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # multiurl forces tqdm progress bars on (disable=False), which floods CI logs; a huge
    # refresh interval reduces them to one line per download.
    os.environ.setdefault("TQDM_MININTERVAL", "3600")
    for noisy in ("urllib3", "multiurl", "ecmwf.opendata"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _cmd_ingest_ecmwf(settings: Settings, args: argparse.Namespace) -> int:
    from pvt.ingest.ecmwf import ingest, make_fetchers

    models = list(settings.models) if args.model == "all" else [args.model]
    results = ingest(
        settings,
        models,
        start=parse_utc(args.start) if args.start else None,
        end=parse_utc(args.end) if args.end else None,
        force=args.force,
        dry_run=args.dry_run,
        fetchers=make_fetchers(settings, args.source) if args.source else None,
    )
    failed = [r for r in results if r.status in ("failed", "source_error")]
    for r in failed:
        LOG.error("%s %s: %s", r.model_id, r.issue_time_utc, r.detail)
    return EXIT_PROBLEM if failed else EXIT_OK


def _cmd_ingest_obs_xml(settings: Settings, args: argparse.Namespace) -> int:
    from pvt.ingest.http import FetchError
    from pvt.ingest.obs_xml import ObsXmlError, ingest

    try:
        ingest(settings)
    except (FetchError, ObsXmlError) as exc:
        LOG.error("ingest-obs-xml: %s", exc)
        return EXIT_PROBLEM
    return EXIT_OK


def _cmd_ingest_kaur_fc(settings: Settings, args: argparse.Namespace) -> int:
    from pvt.ingest.kaur_fc import ingest

    results = ingest(settings)
    return EXIT_PROBLEM if any(v.startswith("failed") for v in results.values()) else EXIT_OK


def _cmd_ingest_kliima(settings: Settings, args: argparse.Namespace) -> int:
    from pvt.ingest.http import FetchError
    from pvt.ingest.kliima import KliimaError, ingest

    try:
        for day, status in ingest(settings).items():
            LOG.info("kliima %s: %s", day, status)
    except (FetchError, KliimaError) as exc:
        LOG.error("ingest-kliima: %s", exc)
        return EXIT_PROBLEM
    return EXIT_OK


def _cmd_sync_stations(settings: Settings, args: argparse.Namespace) -> int:
    from pvt.stations import sync_stations

    sync_stations(settings, settings.kliima.base_url)
    return EXIT_OK


def _cmd_monitor(settings: Settings, args: argparse.Namespace) -> int:
    from pvt.monitor.freshness import run_monitor

    return run_monitor(settings).exit_code


def _cmd_pair(settings: Settings, args: argparse.Namespace) -> int:
    from pvt.pair import run_pair

    result = run_pair(settings.data_root, settings.stations)
    return EXIT_OK if result.n_hourly else EXIT_PROBLEM


def _cmd_score(settings: Settings, args: argparse.Namespace) -> int:
    from pvt.score import run_score

    try:
        run_score(settings.data_root)
    except FileNotFoundError as exc:
        LOG.error("score: pairs missing (run `pvt pair` first): %s", exc)
        return EXIT_PROBLEM
    return EXIT_OK


def _cmd_build_site(settings: Settings, args: argparse.Namespace) -> int:
    from pvt.site.build import build_site

    build_site(settings, args.out)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    p = argparse.ArgumentParser(prog="pvt", description="Prognoos vs tegelikkus pipeline")
    p.add_argument("--version", action="version", version=f"pvt {__version__}")
    p.add_argument("--config-dir", type=Path, help="directory with *.toml (default ./config)")
    p.add_argument("--data-root", type=Path, help="archive root (default from settings.toml)")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    sub = p.add_subparsers(dest="step", required=True)

    e = sub.add_parser("ingest-ecmwf", help="archive ECMWF IFS / AIFS Single open data runs")
    e.add_argument("--model", default="all", help="ifs | aifs-single | all")
    e.add_argument("--start", help="earliest issue time, ISO 8601 UTC (e.g. 2026-11-12T00Z)")
    e.add_argument("--end", help="latest issue time, ISO 8601 UTC")
    e.add_argument(
        "--source",
        action="append",
        help="mirror(s) to use instead of settings (repeatable): aws, google, ...",
    )
    e.add_argument("--force", action="store_true", help="re-ingest runs already complete")
    e.add_argument("--dry-run", action="store_true", help="discover steps only, write nothing")
    e.set_defaults(func=_cmd_ingest_ecmwf)

    for name, func, help_text in (
        ("ingest-obs-xml", _cmd_ingest_obs_xml, "snapshot of the KAUR observations XML (T1)"),
        ("ingest-kaur-fc", _cmd_ingest_kaur_fc, "snapshot of the KAUR 'Eesti prognoos' XML"),
        ("ingest-kliima", _cmd_ingest_kliima, "validated hourly climate data via API (T2)"),
        (
            "sync-stations",
            _cmd_sync_stations,
            "regenerate config/stations.toml from the climate API",
        ),
    ):
        sub.add_parser(name, help=help_text).set_defaults(func=func)

    sub.add_parser("pair", help="forecast-observation pairs from the archive (E2)").set_defaults(
        func=_cmd_pair
    )
    sub.add_parser("score", help="verification scores from the pairs (E3)").set_defaults(
        func=_cmd_score
    )
    b = sub.add_parser("build-site", help="JSON data for the static web page (E4)")
    b.add_argument("--out", type=Path, default=Path("site/public/data"), help="output directory")
    b.set_defaults(func=_cmd_build_site)

    m = sub.add_parser("monitor", help="freshness and run inventory; exit 1 if stale")
    m.set_defaults(func=_cmd_monitor)

    for name, stage in _PENDING_STEPS.items():
        sp = sub.add_parser(name, help=f"not implemented yet ({stage})")
        sp.set_defaults(func=None, pending=stage)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the exit code."""
    args = build_parser().parse_args(argv)
    setup_logging(args.log_level)
    if args.func is None:
        LOG.error("step %r is not implemented yet: %s", args.step, args.pending)
        return EXIT_USAGE
    try:
        settings = load_settings(args.config_dir, args.data_root)
    except (ConfigError, KeyError) as exc:
        LOG.error("configuration error: %s", exc)
        return EXIT_CONFIG
    if hasattr(args, "model") and args.model != "all" and args.model not in settings.models:
        LOG.error("unknown model %r (known: %s)", args.model, ", ".join(settings.models))
        return EXIT_USAGE
    code: int = args.func(settings, args)
    return code


if __name__ == "__main__":
    sys.exit(main())
