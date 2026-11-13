"""Load TOML configuration (settings, model parameters, stations)."""

from __future__ import annotations

import datetime as dt
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pvt.timeutil import parse_utc

REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(ValueError):
    """Raised for missing or inconsistent configuration."""


def _expand_steps(ranges: list[list[int]]) -> tuple[int, ...]:
    steps: set[int] = set()
    for item in ranges:
        if len(item) != 3:
            raise ConfigError(f"step range must be [start, stop, by], got {item!r}")
        start, stop, by = item
        if by <= 0 or stop < start:
            raise ConfigError(f"invalid step range {item!r}")
        steps.update(range(start, stop + 1, by))
    return tuple(sorted(steps))


@dataclass(frozen=True)
class ModelCycle:
    """A model cycle valid from a given issue time."""

    cycle: str
    valid_from: dt.datetime
    source: str


@dataclass(frozen=True)
class ModelConfig:
    """ECMWF open data model definition (see config/params.toml)."""

    model_id: str
    client_model: str
    resol: str
    stream: str
    type: str
    runs_utc: tuple[int, ...]
    candidate_steps: tuple[int, ...]
    expected_steps: dict[int, tuple[int, ...]]
    min_issue_time: dt.datetime
    cycles: tuple[ModelCycle, ...]

    def cycle_for(self, issue_time: dt.datetime) -> str:
        """Return the model cycle label for a run, or ``"unknown"``."""
        label = "unknown"
        for c in sorted(self.cycles, key=lambda c: c.valid_from):
            if issue_time >= c.valid_from:
                label = c.cycle
        return label


@dataclass(frozen=True)
class Area:
    """Inclusive lat/lon box in EPSG:4326 degrees (longitudes in [-180, 180))."""

    lat_min_deg: float
    lat_max_deg: float
    lon_min_deg: float
    lon_max_deg: float
    grid_increment_deg: float


@dataclass(frozen=True)
class EcmwfSettings:
    """Ingest behaviour for ECMWF open data."""

    sources: tuple[str, ...]
    lookback_hours: int
    min_age_hours: int
    partial_after_hours: int
    steps_per_batch: int
    maximum_retries: int
    retry_after_seconds: int
    http_timeout_seconds: int
    probe_pause_seconds: float
    area: Area
    step_params: tuple[str, ...]
    static_params: tuple[str, ...]


@dataclass(frozen=True)
class MonitorSettings:
    """Freshness thresholds and inventory window."""

    max_age_hours_ecmwf: int
    max_age_hours_obs_xml: int
    max_age_hours_kliima: int
    inventory_days: int
    min_completeness_fraction: float


@dataclass(frozen=True)
class Station:
    """One station from config/stations.toml."""

    station_id: str
    name: str
    verified: bool
    lat_deg: float | None = None
    lon_deg: float | None = None
    height_m_eh2000: float | None = None
    wmo_code: str | None = None
    coord_source_uri: str | None = None
    height_source_uri: str | None = None


@dataclass(frozen=True)
class Settings:
    """All configuration needed by the CLI."""

    config_dir: Path
    data_root: Path
    ecmwf: EcmwfSettings
    models: dict[str, ModelConfig]
    monitor: MonitorSettings
    stations: tuple[Station, ...]


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"configuration file missing: {path}") from exc


def _parse_models(params: dict[str, Any]) -> dict[str, ModelConfig]:
    models: dict[str, ModelConfig] = {}
    cycles_cfg = params.get("model_cycles", {})
    for model_id, m in params["models"].items():
        expected = {int(h): _expand_steps(r) for h, r in m["expected_steps"].items()}
        runs = tuple(int(h) for h in m["runs_utc"])
        if set(expected) != set(runs):
            raise ConfigError(f"{model_id}: expected_steps keys {sorted(expected)} != runs {runs}")
        candidates = _expand_steps(m["candidate_steps"])
        for h, steps in expected.items():
            if not set(steps) <= set(candidates):
                raise ConfigError(f"{model_id} {h:02d}Z: expected steps not within candidates")
        cycles = tuple(
            ModelCycle(c["cycle"], parse_utc(c["valid_from_utc"]), c["source"])
            for c in cycles_cfg.get(model_id, [])
        )
        models[model_id] = ModelConfig(
            model_id=model_id,
            client_model=m["client_model"],
            resol=m["resol"],
            stream=m["stream"],
            type=m["type"],
            runs_utc=runs,
            candidate_steps=candidates,
            expected_steps=expected,
            min_issue_time=parse_utc(m["min_issue_time_utc"]),
            cycles=cycles,
        )
    return models


def _parse_stations(raw: dict[str, Any]) -> tuple[Station, ...]:
    stations: list[Station] = []
    seen: set[str] = set()
    for s in raw.get("station", []):
        st = Station(
            station_id=str(s["station_id"]),
            name=str(s["name"]),
            verified=bool(s["verified"]),
            lat_deg=s.get("lat_deg"),
            lon_deg=s.get("lon_deg"),
            height_m_eh2000=s.get("height_m_EH2000"),
            wmo_code=s.get("wmo_code"),
            coord_source_uri=s.get("coord_source_uri"),
            height_source_uri=s.get("height_source_uri"),
        )
        if st.station_id in seen:
            raise ConfigError(f"duplicate station_id {st.station_id}")
        seen.add(st.station_id)
        if st.verified:
            missing = [
                name
                for name in (
                    "lat_deg",
                    "lon_deg",
                    "height_m_eh2000",
                    "coord_source_uri",
                    "height_source_uri",
                )
                if getattr(st, name) is None
            ]
            if missing:
                raise ConfigError(f"station {st.station_id} verified=true but missing {missing}")
            lat, lon = float(s["lat_deg"]), float(s["lon_deg"])
            # Generous Estonia envelope incl. islands (docs/06 section 2).
            if not (57.3 <= lat <= 59.95 and 21.5 <= lon <= 28.3):
                raise ConfigError(f"station {st.station_id} coordinates outside Estonia")
        stations.append(st)
    return tuple(stations)


def load_settings(config_dir: Path | None = None, data_root: Path | None = None) -> Settings:
    """Load settings from ``config_dir`` (default: ``$PVT_CONFIG_DIR`` or ``./config``).

    Parameters
    ----------
    config_dir : pathlib.Path, optional
        Directory containing settings.toml, params.toml and stations.toml.
    data_root : pathlib.Path, optional
        Overrides ``[paths] data_root`` and ``$PVT_DATA_ROOT``.

    Returns
    -------
    Settings
        Parsed configuration.
    """
    cdir = config_dir or Path(os.environ.get("PVT_CONFIG_DIR", REPO_ROOT / "config"))
    s = _read_toml(cdir / "settings.toml")
    p = _read_toml(cdir / "params.toml")
    st = _read_toml(cdir / "stations.toml")

    root = data_root or Path(os.environ.get("PVT_DATA_ROOT", s["paths"]["data_root"]))
    if not root.is_absolute():
        root = REPO_ROOT / root

    e = s["ecmwf"]
    ecmwf = EcmwfSettings(
        sources=tuple(e["sources"]),
        lookback_hours=int(e["lookback_hours"]),
        min_age_hours=int(e["min_age_hours"]),
        partial_after_hours=int(e["partial_after_hours"]),
        steps_per_batch=int(e["steps_per_batch"]),
        maximum_retries=int(e["maximum_retries"]),
        retry_after_seconds=int(e["retry_after_seconds"]),
        http_timeout_seconds=int(e["http_timeout_seconds"]),
        probe_pause_seconds=float(e["probe_pause_seconds"]),
        area=Area(**{k: float(v) for k, v in e["area"].items()}),
        step_params=tuple(p["fields"]["step_params"]),
        static_params=tuple(p["fields"]["static_params"]),
    )
    m = s["monitor"]
    monitor = MonitorSettings(
        max_age_hours_ecmwf=int(m["max_age_hours_ecmwf"]),
        max_age_hours_obs_xml=int(m["max_age_hours_obs_xml"]),
        max_age_hours_kliima=int(m["max_age_hours_kliima"]),
        inventory_days=int(m["inventory_days"]),
        min_completeness_fraction=float(m["min_completeness_fraction"]),
    )
    return Settings(
        config_dir=cdir,
        data_root=root,
        ecmwf=ecmwf,
        models=_parse_models(p),
        monitor=monitor,
        stations=_parse_stations(st),
    )
