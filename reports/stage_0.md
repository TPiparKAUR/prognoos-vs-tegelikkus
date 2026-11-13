# Etapp E0 – repo skelett, CI, testid

**Kuupäev:** 2026-11-13 · **Haru:** `claude/modest-johnson-mo063h`

## Mis tehti
- `pyproject.toml` (Python 3.12, uv, hatchling), `uv.lock`, `.python-version`, `.gitignore`
  (GRIB, `data/`, Parquet välja), `Dockerfile` (python:3.12-slim-bookworm, ecCodes `eccodeslib`-rattast,
  mitte-root kasutaja), `scratch/README.md`.
- `config/settings.toml`, `config/params.toml`, `config/stations.toml` (TOML, `tomllib`).
- Pakk `src/pvt`: `cli` (`pvt <step>`, kõik docs/08 sammud olemas; rakendamata sammud lõpetavad
  koodiga 2 ja ütlevad, mis etapis need tulevad), `config`, `timeutil` (naiivne datetime → viga),
  `units` (ainult nimetatud teisendused, tundmatu ühik → viga), `schemas` (schema_version 1.0.0,
  valideerimine: veerud, tüübid, päritolu, duplikaatvõtmed, `lead_h == valid − issue`), `storage`
  (aatomiline, deterministlik Parquet/JSON), `provenance` (`ingest_version` = git-räsi).
- CI: `.gitlab-ci.yml` (primaarne) ja `.github/workflows/{ci,ingest,keepalive}.yml` (alternatiiv).
- `docs/00–08` projektikomplektist (sisu muutmata) + `docs/README.md` allikaloendiga.

## Kõrvalekalded vaikimisi standardist (teadlikud)
| Mis | Miks |
|---|---|
| GRIB-i lugemiseks `eccodes` otse, mitte earthkit/xarray | ecCodes on earthkiti alus; vaja on ainult sõnumite võtmeid ja kasti väljalõiget. Üks sõltuvus vähem (earthkit-data toob kaasa kümneid). |
| `pyarrow` puudub | Polars kirjutab Parquetit ise. |
| `eccodeslib` eraldi sõltuvusena | `eccodes` deklareerib selle dünaamilise markeriga, mida uv ei lahenda → ilma selleta „Cannot find the ecCodes library". |
| Repo litsents määramata | Ei ole minu otsustada (vt avatud küsimused). |

## Testid
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` (strict, `src/pvt` + `ci/`),
`uv run pytest` – tulemused koos E1-ga: [stage_1.md](stage_1.md#testid).

## Avatud küsimused
1. Repo litsents ja nähtavus (avalik/privaatne)? GitHubi variandis sõltub sellest Pages ja
   runnerite ressursid (docs/03 §5).
2. GitLabi CI pilt: kas Docker Hub (`python:3.12-slim-bookworm`) on sisevõrgust kättesaadav või
   tuleb kasutada sisemist registrit (`PVT_CI_IMAGE`)?

## Mida kontrollida
- `uv sync --frozen` puhtalt masinalt (lukufail tehti 2026-11-13; eccodes 2.50.1, eccodeslib 2.50.0).
- `docker build --build-arg PVT_INGEST_VERSION=$(git rev-parse --short=12 HEAD) .` – Dockerfile'i
  pole arenduskeskkonnas ehitatud (Docker puudub).
