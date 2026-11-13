"""`pvt ingest-ecmwf`: idempotent archive of ECMWF IFS / AIFS Single open data runs.

For every run in the look-back window that is not yet archived as ``complete``:

1. discover which steps exist on a mirror by probing the per-step ``.index`` files
   (the step list is read from the source, not assumed);
2. download only the needed fields with ``ecmwf-opendata`` (index-based byte ranges),
   in batches of steps, into a temporary directory;
3. cut out the regional sub-grid, convert units explicitly, validate;
4. write one Parquet file per run (+ static fields) atomically, then a JSON manifest.

GRIB files are deleted after each batch and never stored. Re-running is safe: complete
runs whose files match the manifest hashes are skipped.
"""

from __future__ import annotations

import datetime as dt
import logging
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import polars as pl
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pvt import SCHEMA_VERSION
from pvt.config import Area, ModelConfig, Settings
from pvt.extract.points import (
    attach_targets,
    build_weights,
    points_from_stencil,
    stencil_points,
)
from pvt.ingest.ecmwf_grib import BoxExtractor, BoxField, GribContentError, read_box_fields
from pvt.provenance import ingest_version
from pvt.schemas import (
    FORECAST_GRID,
    FORECAST_GRID_KEY,
    FORECAST_GRID_STATIC,
    FORECAST_GRID_STATIC_KEY,
    FORECAST_POINT,
    FORECAST_POINT_KEY,
    SchemaError,
    validate,
)
from pvt.stations import station_targets
from pvt.storage import (
    ecmwf_grid_path,
    ecmwf_manifest_path,
    read_json,
    sha256_file,
    write_json_atomic,
    write_parquet_atomic,
)
from pvt.timeutil import format_utc, iter_runs, require_utc, run_tag, utc_now
from pvt.units import UnitError, convert

LOG = logging.getLogger(__name__)

#: shortName -> column in FORECAST_GRID
STEP_COLUMNS = {
    "2t": "t2m_degC",
    "10u": "u10_m_s",
    "10v": "v10_m_s",
    "msl": "mslp_hPa",
    "tp": "precip_acc_mm",
    "10fg": "gust10m_max_m_s",
}
STATIC_COLUMNS = {"z": "grid_orog_m", "lsm": "grid_lsm_frac"}
TARGET_UNITS = {
    "t2m_degC": "degC",
    "u10_m_s": "m_s",
    "v10_m_s": "m_s",
    "mslp_hPa": "hPa",
    "precip_acc_mm": "mm",
    "gust10m_max_m_s": "m_s",
    "grid_orog_m": "m",
    "grid_lsm_frac": "frac",
}


class IngestError(RuntimeError):
    """Raised when a run cannot be archived consistently."""


class SourceUnavailableError(IngestError):
    """Raised when a mirror cannot be reached or answers with an unexpected error."""


# --------------------------------------------------------------------------- fetchers


class Fetcher(Protocol):
    """Access to one ECMWF open data mirror."""

    name: str

    def has_step(self, model: ModelConfig, issue: dt.datetime, step: int) -> bool:
        """Return True if the step's index file exists (False on 404)."""
        ...

    def retrieve(
        self,
        model: ModelConfig,
        issue: dt.datetime,
        steps: Sequence[int],
        params: Sequence[str],
        target: Path,
    ) -> int:
        """Download the given steps/params (levtype=sfc) into ``target``; return bytes."""
        ...


def relative_key(model: ModelConfig, issue: dt.datetime, step: int, ext: str = "grib2") -> str:
    """Mirror-independent object key of one step file (same layout on all mirrors).

    Valid for runs from 2026-05-12 on, when 06/18 UTC runs moved to ``stream=oper``.
    """
    t = require_utc(issue)
    # 0.1 deg IFS ships single-level fields in "<name>-sfc" files (ecmwf-opendata
    # SPLIT_RESOLUTIONS); only surface fields are archived here.
    split = "-sfc" if model.resol in SPLIT_RESOLUTIONS else ""
    return (
        f"{t:%Y%m%d}/{t:%H}z/{model.client_model}/{model.resol}/{model.stream}/"
        f"{t:%Y%m%d%H%M%S}-{step}h-{model.stream}-{model.type}{split}.{ext}"
    )


#: Resolutions whose open-data files are split into "-sfc" and "-pl" (observed 2026-11-13).
SPLIT_RESOLUTIONS = frozenset({"0p1"})


def model_area(settings: Settings, model: ModelConfig) -> Area:
    """Regional box of a model (its own grid increment for the 0.1 deg IFS)."""
    return model.area or settings.ecmwf.area


@dataclass
class OpenDataFetcher:
    """Fetcher backed by ``ecmwf-opendata`` (downloads) and ``requests`` (index probes)."""

    name: str
    maximum_retries: int
    retry_after_seconds: int
    timeout_seconds: int
    probe_pause_seconds: float
    _session: requests.Session = field(init=False, repr=False)
    _clients: dict[str, Any] = field(init=False, default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._session = requests.Session()
        retry = Retry(
            total=self.maximum_retries,
            backoff_factor=2.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"HEAD", "GET"}),
            respect_retry_after_header=True,
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retry))

    def _client(self, model: ModelConfig) -> Any:
        from ecmwf.opendata import Client

        key = f"{model.client_model}/{model.resol}"
        if key not in self._clients:
            self._clients[key] = Client(
                source=self.name,
                model=model.client_model,
                resol=model.resol,
                maximum_retries=self.maximum_retries,
                retry_after=self.retry_after_seconds,
            )
        return self._clients[key]

    def has_step(self, model: ModelConfig, issue: dt.datetime, step: int) -> bool:
        """Probe ``<step>.index`` with HEAD."""
        url = f"{self._client(model).url}/{relative_key(model, issue, step, 'index')}"
        time.sleep(self.probe_pause_seconds)
        try:
            r = self._session.head(url, timeout=self.timeout_seconds, allow_redirects=True)
        except requests.RequestException as exc:
            raise SourceUnavailableError(f"{self.name}: {exc}") from exc
        if r.status_code == 200:
            return True
        if r.status_code in (403, 404):
            # S3/GCS answer 403 or 404 for missing objects in public buckets.
            return False
        raise SourceUnavailableError(f"{self.name}: HTTP {r.status_code} for {url}")

    def retrieve(
        self,
        model: ModelConfig,
        issue: dt.datetime,
        steps: Sequence[int],
        params: Sequence[str],
        target: Path,
    ) -> int:
        """Download with ``Client.retrieve`` (index-based byte ranges)."""
        t = require_utc(issue)
        try:
            self._client(model).retrieve(
                date=int(f"{t:%Y%m%d}"),
                time=t.hour,
                stream=model.stream,
                type=model.type,
                step=list(steps),
                param=list(params),
                levtype="sfc",
                target=str(target),
            )
        except (requests.RequestException, OSError, ValueError) as exc:
            raise SourceUnavailableError(f"{self.name}: retrieve failed: {exc}") from exc
        # Result.size from multiurl is not the byte count of the target; measure the file.
        return target.stat().st_size if target.exists() else 0


# --------------------------------------------------------------------------- planning


@dataclass
class Discovery:
    """Outcome of probing the mirrors for one run."""

    status: str  # "available" | "partial" | "not_available" | "source_error"
    source: str | None
    steps_available: tuple[int, ...]
    detail: str = ""


def discover_run(
    model: ModelConfig,
    issue: dt.datetime,
    fetchers: Sequence[Fetcher],
    age_h: float,
    partial_after_h: int,
) -> Discovery:
    """Find a mirror that has the run and list the steps that actually exist there.

    A mirror qualifies as soon as the last *expected* step exists; then every candidate
    step is probed on it. If no mirror has the last expected step and the run is older
    than ``partial_after_h``, the first mirror with step 0 is probed for a partial run.
    """
    expected = model.expected_steps[issue.hour]
    errors: list[str] = []
    partial_source: Fetcher | None = None
    for f in fetchers:
        try:
            if not f.has_step(model, issue, 0):
                continue
            if partial_source is None:
                partial_source = f
            if f.has_step(model, issue, expected[-1]):
                steps = tuple(s for s in model.candidate_steps if f.has_step(model, issue, s))
                return Discovery("available", f.name, steps)
        except SourceUnavailableError as exc:
            LOG.warning("%s %s: %s", model.model_id, run_tag(issue), exc)
            errors.append(str(exc))
    if partial_source is not None and age_h >= partial_after_h:
        try:
            steps = tuple(
                s for s in model.candidate_steps if partial_source.has_step(model, issue, s)
            )
        except SourceUnavailableError as exc:
            return Discovery("source_error", partial_source.name, (), str(exc))
        return Discovery("partial", partial_source.name, steps, "last expected step missing")
    if errors and partial_source is None:
        return Discovery("source_error", None, (), "; ".join(errors))
    return Discovery("not_available", None, (), "run not (fully) published yet")


# --------------------------------------------------------------------------- assembly


def _check_field(fld: BoxField, issue: dt.datetime) -> None:
    if fld.issue_time != issue:
        raise IngestError(f"{fld.short_name}: GRIB issue time {fld.issue_time} != {issue}")
    if fld.valid_time != issue + dt.timedelta(hours=fld.end_step_h):
        raise IngestError(f"{fld.short_name}: valid time inconsistent with step {fld.end_step_h}")
    if fld.short_name == "tp":
        if fld.step_type != "accum" or fld.start_step_h != 0:
            raise IngestError(
                f"tp step {fld.end_step_h}: expected accumulation from 0, got "
                f"{fld.step_type} {fld.start_step_h}-{fld.end_step_h}"
            )
    elif fld.short_name == "10fg":
        if fld.step_type != "max":
            raise IngestError(f"10fg step {fld.end_step_h}: expected max, got {fld.step_type}")
    elif fld.step_type != "instant":
        raise IngestError(f"{fld.short_name}: expected instant field, got {fld.step_type}")


def assemble_step_frame(
    fields: Sequence[BoxField],
    model: ModelConfig,
    issue: dt.datetime,
    steps: Sequence[int],
    params: Sequence[str],
    version: str,
    optional: Sequence[str] = (),
) -> pl.DataFrame:
    """Combine box fields of several steps into a FORECAST_GRID frame.

    Parameters in ``optional`` may be absent for some steps (their columns become null);
    e.g. IFS ``10fg`` exists in open data for 0-90 h and 150-360 h but not 93-144 h.

    Raises
    ------
    IngestError
        On missing/duplicate fields, inconsistent coordinates or times.
    """
    by_key: dict[tuple[int, str], BoxField] = {}
    for fld in fields:
        if fld.short_name not in params:
            continue
        _check_field(fld, issue)
        key = (fld.end_step_h, fld.short_name)
        if key in by_key:
            raise IngestError(f"duplicate field {key}")
        by_key[key] = fld
    missing = [(s, p) for s in steps for p in params if p not in optional and (s, p) not in by_key]
    if missing:
        raise IngestError(f"missing fields (step, param): {missing[:10]}")
    extra = sorted({s for s, _ in by_key} - set(steps))
    if extra:
        raise IngestError(f"unexpected steps in download: {extra}")

    ref = by_key[(steps[0], params[0])]
    cycle = model.cycle_for(issue)
    frames: list[pl.DataFrame] = []
    for step in steps:
        cols: dict[str, Any] = {}
        gen_ids = set()
        acc_start = 0
        acc_quantum = 0.0
        gust_start: int | None = None
        for p in params:
            maybe = by_key.get((step, p))
            if maybe is None:
                continue  # optional parameter absent at this step
            fld = maybe
            if not (
                np.array_equal(fld.lat_deg, ref.lat_deg)
                and np.array_equal(fld.lon_deg, ref.lon_deg)
            ):
                raise IngestError(f"grid of {p} step {step} differs from reference grid")
            unit, vals = convert(fld.quantity, fld.units, fld.values)
            column = STEP_COLUMNS[p]
            if unit != TARGET_UNITS[column]:
                raise IngestError(
                    f"{p}: converted to {unit}, column expects {TARGET_UNITS[column]}"
                )
            cols[column] = vals
            gen_ids.add(fld.gen_proc_id)
            if p == "tp":
                acc_start = fld.start_step_h
                _, q = convert(fld.quantity, fld.units, np.array([fld.packing_quantum]))
                acc_quantum = float(q[0])
            if p == "10fg":
                gust_start = fld.start_step_h
        if len(gen_ids) != 1:
            raise IngestError(f"step {step}: mixed generatingProcessIdentifier {gen_ids}")
        n = ref.lat_deg.size
        frames.append(
            pl.DataFrame(
                {
                    "model_id": [model.model_id] * n,
                    "model_cycle": [cycle] * n,
                    "grib_gen_proc_id": [gen_ids.pop()] * n,
                    "issue_time_utc": [issue] * n,
                    "valid_time_utc": [issue + dt.timedelta(hours=step)] * n,
                    "lead_h": [step] * n,
                    "member": [-1] * n,
                    "grid_lat_deg": ref.lat_deg,
                    "grid_lon_deg": ref.lon_deg,
                    "t2m_degC": cols["t2m_degC"],
                    "u10_m_s": cols["u10_m_s"],
                    "v10_m_s": cols["v10_m_s"],
                    "mslp_hPa": cols["mslp_hPa"],
                    "precip_acc_mm": cols["precip_acc_mm"],
                    "precip_acc_start_h": [acc_start] * n,
                    "precip_acc_quantum_mm": [acc_quantum] * n,
                    "gust10m_max_m_s": cols.get("gust10m_max_m_s", [None] * n),
                    "gust_window_start_h": [gust_start] * n,
                    "provenance": ["prognoos"] * n,
                    "source_uri": [f"ecmwf-opendata:{relative_key(model, issue, step)}"] * n,
                    "ingest_version": [version] * n,
                    "schema_version": [SCHEMA_VERSION] * n,
                },
                schema=FORECAST_GRID,
            )
        )
    return pl.concat(frames)


def assemble_static_frame(
    fields: Sequence[BoxField], model: ModelConfig, issue: dt.datetime, version: str
) -> pl.DataFrame:
    """Build the FORECAST_GRID_STATIC frame from step-0 ``z`` and ``lsm`` fields."""
    by_name: dict[str, BoxField] = {}
    for fld in fields:
        if fld.short_name in STATIC_COLUMNS and fld.end_step_h == 0:
            _check_field(fld, issue)
            if fld.short_name in by_name:
                raise IngestError(f"duplicate static field {fld.short_name}")
            by_name[fld.short_name] = fld
    if set(by_name) != set(STATIC_COLUMNS):
        raise IngestError(f"static fields missing: {set(STATIC_COLUMNS) - set(by_name)}")
    z, lsm = by_name["z"], by_name["lsm"]
    if not (np.array_equal(z.lat_deg, lsm.lat_deg) and np.array_equal(z.lon_deg, lsm.lon_deg)):
        raise IngestError("static field grids differ")
    _, orog = convert(z.quantity, z.units, z.values)
    _, frac = convert(lsm.quantity, lsm.units, lsm.values)
    n = z.lat_deg.size
    return pl.DataFrame(
        {
            "model_id": [model.model_id] * n,
            "model_cycle": [model.cycle_for(issue)] * n,
            "issue_time_utc": [issue] * n,
            "grid_lat_deg": z.lat_deg,
            "grid_lon_deg": z.lon_deg,
            "grid_orog_m": orog,
            "grid_lsm_frac": frac,
            "provenance": ["prognoos"] * n,
            "source_uri": [f"ecmwf-opendata:{relative_key(model, issue, 0)}"] * n,
            "ingest_version": [version] * n,
            "schema_version": [SCHEMA_VERSION] * n,
        },
        schema=FORECAST_GRID_STATIC,
    )


# --------------------------------------------------------------------------- run ingest


@dataclass
class RunResult:
    """Summary of one run attempt (also the manifest content)."""

    model_id: str
    issue_time_utc: str
    status: str
    detail: str = ""
    manifest: dict[str, Any] = field(default_factory=dict)


def _archived_ok(settings: Settings, model: ModelConfig, issue: dt.datetime) -> bool:
    mpath = ecmwf_manifest_path(settings.data_root, model.model_id, issue)
    if not mpath.exists():
        return False
    man = read_json(mpath)
    if man.get("status") != "complete":
        return False
    for info in man.get("files", {}).values():
        p = settings.data_root / info["path"]
        if not p.exists() or sha256_file(p) != info["sha256"]:
            LOG.warning(
                "%s %s: archived file missing or modified (%s); re-ingesting",
                model.model_id,
                run_tag(issue),
                info["path"],
            )
            return False
    return True


def ingest_run(
    settings: Settings,
    model: ModelConfig,
    issue: dt.datetime,
    fetchers: Sequence[Fetcher],
    now: dt.datetime,
    *,
    dry_run: bool = False,
) -> RunResult:
    """Archive a single run if possible; always returns a result (never raises for data).

    Parameters
    ----------
    settings : Settings
        Loaded configuration.
    model : ModelConfig
        Model definition.
    issue : datetime.datetime
        Run start (aware UTC).
    fetchers : sequence of Fetcher
        Mirrors in priority order.
    now : datetime.datetime
        Current time (injected for testability).
    dry_run : bool
        Only discover steps; do not download or write.
    """
    issue = require_utc(issue)
    tag = run_tag(issue)
    age_h = (require_utc(now) - issue).total_seconds() / 3600.0
    mpath = ecmwf_manifest_path(settings.data_root, model.model_id, issue)
    previous = read_json(mpath) if mpath.exists() else {}
    base: dict[str, Any] = {
        "model_id": model.model_id,
        "issue_time_utc": format_utc(issue),
        "model_cycle": model.cycle_for(issue),
        "steps_expected": list(model.expected_steps[issue.hour]),
        "attempts": int(previous.get("attempts", 0)) + 1,
        "first_attempt_utc": previous.get("first_attempt_utc", format_utc(now)),
        "last_attempt_utc": format_utc(now),
        "ingest_version": ingest_version(),
        "schema_version": SCHEMA_VERSION,
        "licence": "CC BY 4.0; source: ECMWF open data (IFS / AIFS Single)",
    }
    disc = discover_run(model, issue, fetchers, age_h, settings.ecmwf.partial_after_hours)
    base.update(source=disc.source, steps_available=list(disc.steps_available))
    if disc.status in ("not_available", "source_error"):
        LOG.info("%s %s: %s (%s)", model.model_id, tag, disc.status, disc.detail)
        man = {**base, "status": disc.status, "detail": disc.detail}
        if not dry_run and age_h >= settings.ecmwf.partial_after_hours:
            # Only record failures once the run should exist; younger runs are just early.
            write_json_atomic(man, mpath)
        return RunResult(model.model_id, format_utc(issue), disc.status, disc.detail, man)

    unexpected = sorted(set(disc.steps_available) - set(model.expected_steps[issue.hour]))
    if unexpected:
        LOG.warning(
            "%s %s: steps outside expected schedule present: %s", model.model_id, tag, unexpected
        )
    if dry_run:
        LOG.info(
            "%s %s: %s on %s, %d steps",
            model.model_id,
            tag,
            disc.status,
            disc.source,
            len(disc.steps_available),
        )
        return RunResult(model.model_id, format_utc(issue), f"dry_run:{disc.status}", "", base)

    fetcher = next(f for f in fetchers if f.name == disc.source)
    steps = list(disc.steps_available)
    params = [*settings.ecmwf.step_params, *model.extra_step_params]
    version = ingest_version()
    extractor = BoxExtractor(model_area(settings, model))
    t0 = time.monotonic()
    nbytes = 0
    frames: list[pl.DataFrame] = []
    try:
        with tempfile.TemporaryDirectory(prefix="pvt-grib-") as tmpdir:
            tmp = Path(tmpdir)
            static_file = tmp / "static.grib2"
            nbytes += fetcher.retrieve(model, issue, [0], settings.ecmwf.static_params, static_file)
            static_df = assemble_static_frame(
                read_box_fields(static_file, extractor), model, issue, version
            )
            static_file.unlink()
            size = settings.ecmwf.steps_per_batch
            for i in range(0, len(steps), size):
                batch = steps[i : i + size]
                gfile = tmp / f"batch_{i:04d}.grib2"
                nbytes += fetcher.retrieve(model, issue, batch, params, gfile)
                fields = read_box_fields(gfile, extractor)
                gfile.unlink()
                frames.append(
                    assemble_step_frame(
                        fields, model, issue, batch, params, version, model.extra_step_params
                    )
                )
                LOG.debug("%s %s: steps %s-%s done", model.model_id, tag, batch[0], batch[-1])
        grid_df = pl.concat(frames).sort(
            ["lead_h", "grid_lat_deg", "grid_lon_deg"], descending=[False, True, False]
        )
        validate(grid_df, FORECAST_GRID, FORECAST_GRID_KEY)
        validate(static_df, FORECAST_GRID_STATIC, FORECAST_GRID_STATIC_KEY)
        _check_accumulation(grid_df)
        grid_df, static_df, weights_df, point_df, skipped = reduce_to_stations(
            settings, grid_df, static_df, model_area(settings, model).grid_increment_deg
        )
    except (
        SourceUnavailableError,
        IngestError,
        GribContentError,
        SchemaError,
        UnitError,
        OSError,
    ) as exc:
        LOG.error("%s %s: ingest failed: %s", model.model_id, tag, exc)
        man = {**base, "status": "failed", "detail": f"{type(exc).__name__}: {exc}"}
        write_json_atomic(man, mpath)
        return RunResult(model.model_id, format_utc(issue), "failed", str(exc), man)

    gpath = ecmwf_grid_path(settings.data_root, model.model_id, issue, "grid")
    spath = ecmwf_grid_path(settings.data_root, model.model_id, issue, "static")
    wpath = ecmwf_grid_path(settings.data_root, model.model_id, issue, "weights")
    files = {
        "weights": {
            "path": str(wpath.relative_to(settings.data_root)),
            "sha256": write_parquet_atomic(weights_df, wpath),
            "rows": weights_df.height,
        },
        "grid": {
            "path": str(gpath.relative_to(settings.data_root)),
            "sha256": write_parquet_atomic(grid_df, gpath),
            "rows": grid_df.height,
        },
        "static": {
            "path": str(spath.relative_to(settings.data_root)),
            "sha256": write_parquet_atomic(static_df, spath),
            "rows": static_df.height,
        },
    }
    missing = sorted(set(model.expected_steps[issue.hour]) - set(steps))
    status = "complete" if disc.status == "available" and not missing else "partial"
    man = {
        **base,
        "status": status,
        "detail": disc.detail,
        "steps_archived": steps,
        "steps_missing": missing,
        "stations": point_df.get_column("station_id").n_unique(),
        "stations_skipped_outside_area": skipped,
        "optional_param_steps": {
            p: sorted(
                set(
                    grid_df.filter(pl.col(STEP_COLUMNS[p]).is_not_null())
                    .get_column("lead_h")
                    .to_list()
                )
            )
            for p in model.extra_step_params
        },
        "grib_gen_proc_id": sorted(set(grid_df.get_column("grib_gen_proc_id").to_list())),
        "retrieved_at_utc": format_utc(utc_now()),
        "bytes_downloaded": nbytes,
        "duration_s": round(time.monotonic() - t0, 1),
        "files": files,
    }
    write_json_atomic(man, mpath)
    LOG.info(
        "%s %s: %s from %s, %d steps, %.1f MB, %.0f s",
        model.model_id,
        tag,
        status,
        disc.source,
        len(steps),
        nbytes / 1e6,
        man["duration_s"],
    )
    return RunResult(model.model_id, format_utc(issue), status, disc.detail, man)


def reduce_to_stations(
    settings: Settings,
    grid_df: pl.DataFrame,
    static_df: pl.DataFrame,
    grid_increment_deg: float | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame, list[str]]:
    """Keep only the stencil grid points around the stations.

    Station values are NOT stored (they are a deterministic function of the stencil values
    and the weights, see :func:`pvt.extract.points.load_points`); they are derived here once
    to validate the run.

    Returns
    -------
    tuple
        (stencil grid, stencil static, weights, FORECAST_POINT frame, skipped station ids)
    """
    targets = station_targets(settings)
    if targets.is_empty():
        raise IngestError("no station targets (config/stations.toml empty?)")
    inc = grid_increment_deg or settings.ecmwf.area.grid_increment_deg
    weights, skipped = build_weights(static_df, targets, inc)
    if skipped:
        LOG.warning("stations outside the extraction area: %s", skipped)
    stencil = stencil_points(weights)
    on = ["grid_lat_deg", "grid_lon_deg"]
    grid_st = grid_df.join(stencil, on=on, how="semi")
    static_st = static_df.join(stencil, on=on, how="semi")
    weights_full = attach_targets(weights, targets)
    points = points_from_stencil(grid_st, static_st, weights_full)
    validate(points, FORECAST_POINT, FORECAST_POINT_KEY)
    return grid_st, static_st, weights_full, points, skipped


def _check_accumulation(df: pl.DataFrame, eps_mm: float = 1e-9) -> None:
    """Accumulated precipitation must not decrease with lead time (docs/06 section 2).

    Decoded GRIB values are exact only to +-quantum/2, and the quantum differs between
    steps (12-bit packing; observed 0.06-0.25 mm for IFS and AIFS, see reports/stage_1.md).
    A decrease is therefore an error only if it exceeds (q_prev + q_cur) / 2.
    """
    by_point = ["grid_lat_deg", "grid_lon_deg"]
    dec = (
        df.sort("lead_h")
        .with_columns(
            pl.col("precip_acc_mm").diff().over(by_point).alias("d"),
            ((pl.col("precip_acc_quantum_mm") + pl.col("precip_acc_quantum_mm").shift(1)) / 2.0)
            .over(by_point)
            .alias("tol"),
        )
        .filter(pl.col("d") < -(pl.col("tol") + eps_mm))
    )
    if dec.height:
        worst = dec.select(pl.col("d").min()).item()
        raise IngestError(
            f"precipitation accumulation decreases beyond packing precision at {dec.height} "
            f"points (worst {worst:.4f} mm)"
        )


def make_fetchers(settings: Settings, sources: Sequence[str] | None = None) -> list[Fetcher]:
    """Create fetchers for the configured mirrors (or ``sources`` if given)."""
    e = settings.ecmwf
    return [
        OpenDataFetcher(
            name=s,
            maximum_retries=e.maximum_retries,
            retry_after_seconds=e.retry_after_seconds,
            timeout_seconds=e.http_timeout_seconds,
            probe_pause_seconds=e.probe_pause_seconds,
        )
        for s in (sources or e.sources)
    ]


def ingest(
    settings: Settings,
    models: Sequence[str],
    *,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    now: dt.datetime | None = None,
    fetchers: Sequence[Fetcher] | None = None,
    force: bool = False,
    dry_run: bool = False,
    max_runs: int | None = None,
) -> list[RunResult]:
    """Archive all missing runs of ``models`` in ``[start, end]``.

    Defaults: ``end = now - min_age_hours``, ``start = now - lookback_hours``.

    Returns
    -------
    list of RunResult
        One entry per attempted run (skipped complete runs are not listed).
    """
    now = require_utc(now or utc_now())
    e_cfg = settings.ecmwf
    end = require_utc(end or now - dt.timedelta(hours=e_cfg.min_age_hours))
    start = require_utc(start or now - dt.timedelta(hours=e_cfg.lookback_hours))
    fetchers = list(fetchers) if fetchers is not None else make_fetchers(settings)
    todo: list[tuple[dt.datetime, ModelConfig]] = []
    for model_id in models:
        model = settings.models[model_id]
        if start < model.min_issue_time:
            LOG.warning(
                "%s: start %s before supported %s; clipping",
                model_id,
                format_utc(start),
                format_utc(model.min_issue_time),
            )
        runs = list(iter_runs(max(start, model.min_issue_time), end, model.runs_utc))
        pending = [r for r in runs if force or not _archived_ok(settings, model, r)]
        LOG.info(
            "%s: %d runs in window, %d already archived",
            model_id,
            len(runs),
            len(runs) - len(pending),
        )
        todo.extend((r, model) for r in pending)
    # Newest first across models, so a capped invocation keeps the archive current and
    # older gaps are filled by later invocations (the rolling archive is ~4 days deep).
    todo.sort(key=lambda x: (x[0], x[1].model_id), reverse=True)
    limit = max_runs if max_runs is not None else e_cfg.max_runs_per_invocation
    deadline = time.monotonic() + 60 * e_cfg.max_minutes_per_invocation
    results: list[RunResult] = []
    for issue, model in todo:
        if len(results) >= limit or time.monotonic() > deadline:
            LOG.warning(
                "stopping after %d runs (limit/deadline); %d left for next invocation",
                len(results),
                len(todo) - len(results),
            )
            break
        results.append(ingest_run(settings, model, issue, fetchers, now, dry_run=dry_run))
    return results
