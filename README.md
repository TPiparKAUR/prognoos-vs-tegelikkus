# Prognoos vs tegelikkus

> **Eksperimentaalne, mitteametlik.** Ei asenda Keskkonnaagentuuri (KAUR) ametlikku
> prognoosi ega hoiatusi.

ECMWF IFS-i (oper, 0,25°) ja AIFS Single'i (0,25°) prognooside jaamapõhine
verifitseerimine KAURi vaatluste vastu. Projektikomplekt (metoodika, ADR-id,
arhitektuur, testid, riskid): [`docs/`](docs/README.md). Etappide aruanded:
[`reports/`](reports/).

## Seis

| Etapp | Sisu | Seis |
|---|---|---|
| E0 | repo skelett, CI, testid | valmis |
| E1 | `pvt ingest-ecmwf`, `pvt monitor` | valmis, kontrollitud päris andmetel; ajastus veel käivitamata – vt [reports/stage_1.md](reports/stage_1.md) |
| E1b | vaatluste XML, kliima-API, KAURi prognoosi XML | **ootab sisendit** (vt aruande avatud küsimused) |
| E2–E5 | paarid + QC, skoorid, sait, MOS | alustamata |

## Kasutamine

Nõuded: Python 3.12, [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

```bash
uv run pvt ingest-ecmwf            # kõik puuduvad jooksud viimase 96 h jooksul, mõlemad mudelid
```

```bash
uv run pvt ingest-ecmwf --model aifs-single --start 2026-11-12T00Z --end 2026-11-12T18Z
```

```bash
uv run pvt monitor                 # status/freshness.json + status/ecmwf_inventory.json; exit 1 = vananenud
```

Arhiivi juurkaust: `config/settings.toml` → `[paths] data_root` või keskkonnamuutuja
`PVT_DATA_ROOT`. Arhiiv ei kuulu git-i.

### Arhiivi struktuur

```
<data_root>/
  forecast_grid/source=ecmwf_opendata/model=<ifs|aifs-single>/year=YYYY/month=MM/<model>_<YYYYMMDDTHHZ>_grid.parquet
  forecast_static/source=ecmwf_opendata/model=.../<model>_<run>_static.parquet   # orograafia, maa/mere mask
  manifests/ecmwf_opendata/model=.../year=YYYY/<model>_<run>.json                 # olek, sammud, räsid, allikas
  status/freshness.json, status/ecmwf_inventory.json
```

## Arendus

```bash
uv run ruff check . && uv run ruff format --check .
```

```bash
uv run mypy
```

```bash
uv run pytest                      # võrguta testid
```

```bash
uv run pytest -m network           # 1 samm päris ECMWF peeglist (vajab võrku)
```

## Litsentsid ja viited

- ECMWF open data: CC BY 4.0. Viide: „Adapted from 'ECMWF IFS 15-day Forecast Data'
  by ECMWF, licensed under CC BY 4.0" (AIFS-i puhul vastavalt AIFS Single).
- KAURi andmed: viide Keskkonnaagentuurile ja link <https://www.ilmateenistus.ee>;
  keskkonnaportaali levitused CC BY 4.0.
