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
| E1 | `pvt ingest-ecmwf`, `pvt monitor` | valmis – [reports/stage_1.md](reports/stage_1.md) |
| E1b | jaamaregister, vaatluste XML, KAURi prognoosi XML, kliima-API, GitHubi käitus | valmis; asukohaprognoos ootab andmeallikat – [reports/stage_1b.md](reports/stage_1b.md) |
| E2–E5 | paarid + QC, skoorid, sait, MOS | alustamata |

## Käitus (GitHub Actions)

| Töövoog | Ajastus (UTC) | Mida teeb |
|---|---|---|
| `ingest-ecmwf` | iga 2 h :17 | IFS + AIFS Single jaamade ümbrus (≤ 12 jooksu / käivitus, uuemad enne) |
| `ingest-kaur` | iga 10 min | vaatluste XML (T1) + „Eesti prognoos" XML |
| `ingest-kliima` | 05:41, 17:41 | kliima-API tunniandmed (T2), viimased 10 päeva |
| `monitor` | iga 6 h :53 | värskus + 14 päeva inventuur; punane = e-kiri omanikule |

Arhiiv: GitHub Release'id `archive-YYYY-MM` (üks tar andmestik-päeva kohta) ja `archive-meta`.

## Kasutamine lokaalselt

Nõuded: Python 3.12, [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

```bash
uv run pvt ingest-ecmwf            # puuduvad jooksud viimase 96 h jooksul, mõlemad mudelid
```

```bash
uv run pvt ingest-kliima           # T2: kliima-API, viimased 10 päeva
```

```bash
uv run pvt ingest-obs-xml          # T1: üks vaatluste XML-i hetktõmmis
```

```bash
uv run pvt ingest-kaur-fc          # KAURi prognoosi XML (salvestab ainult muutusel)
```

```bash
uv run pvt sync-stations           # config/stations.toml kliima-API-st uuesti
```

```bash
uv run pvt monitor                 # status/*.json; exit 1 = mõni allikas vananenud
```

Jaamaväärtused ühe ECMWF-i jooksu kohta (bilineaarne, lähim, lähim maapunkt):

```python
from pvt.extract.points import load_points
```

### Arhiivi struktuur

```
<data_root>/
  ecmwf/YYYY/MM/DD/<model>_<run>_{grid,static,weights}.parquet + <model>_<run>.json
  obs_xml/YYYY/MM/DD/obs_xml_<date>.parquet + raw/<HHMMSS>.xml.gz
  kaur_fc/YYYY/MM/DD/kaur_fc_{period,detail}_<date>.parquet + raw/<HHMM>_<lang>.xml.gz
  kliima/YYYY/MM/DD/kliima_hly_<date>.parquet
  meta/xml_met_stations.parquet
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

## Andmeallikad ja viited

| Allikas | Kasutus | Litsents / tingimus |
|---|---|---|
| ECMWF open data, IFS (oper, 0,25°) ja AIFS Single (0,25°), peeglid Google Cloud / AWS (`ecmwf-opendata`) | prognoos | CC BY 4.0. ECMWF-i näidisviide (docs/03 §8): „Adapted from 'ECMWF IFS 15-day Forecast Data' by ECMWF, licensed under CC BY 4.0" (AIFS-i puhul vastavalt) |
| Keskkonnaagentuur, vaatluste XML <https://www.ilmateenistus.ee/ilma_andmed/xml/observations.php> | T1 tõde | viide Keskkonnaagentuurile + link <https://www.ilmateenistus.ee> |
| Keskkonnaagentuur, „Eesti prognoos" XML <https://www.ilmateenistus.ee/ilma_andmed/xml/forecast.php> | KAURi prognoos (sisevaade, ADR-012) | viide Keskkonnaagentuurile + link |
| Keskkonnaagentuur, kliimaandmestik (CLIDATA) API <https://keskkonnaandmed.envir.ee/f_kliima_tund>, jaamad `f_kliima_jaam_vaatlus` | T2 tõde, jaamaregister | CC BY 4.0 |
