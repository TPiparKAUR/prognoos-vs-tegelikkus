<!-- Extracted from the project package (v0.1, 2026-11-13). Numbered references [n] point to docs/README.md#allikad -->

# 03_arhitektuur.md

**Pealkiri:** IT-arhitektuur ja andmevoog
**Versioon:** 0.1 · **Kuupäev:** 2026-11-13 · **Soovitatud failinimi:** `docs/03_arhitektuur.md`

### 1. Andmevoog
```
[ECMWF open data / AWS / GCP / Azure peeglid]
      │  ecmwf-opendata (index-põhine valik) → GRIB2 (temp)
      ▼
[ingest_ecmwf] → point extraction (earthkit/eccodes) → forecast_point.parquet
[ingest_obs_xml]  (iga 10 min / tund) → obs_raw.parquet  (toormõõtmine)
[ingest_kliima]   (1× ööpäevas, 20 000 rea kaupa) → obs_qc.parquet (kvaliteedikontrollitud)
[ingest_kaur_fc]  (iga tund hetkepilt) → kaur_forecast_snapshot.parquet (+ toores XML)
      ▼
[pair] (ühine valim, QC lipud, kõrguskorrektsioon) → pairs.parquet
      ▼
[score] (ME/MAE/RMSE/…, bootstrap, DM-HLN) → scores/*.parquet + site/data/*.json
[mos]   (laienev aken) → forecast_point (model_id = mos_*) + ml_report
      ▼
[build_site] → staatiline sait (Pages)        [monitor] → värskuse mõõdik + teavitus
```

### 2. Repo struktuur (ettepanek)
```
prognoos-vs-tegelikkus/
  pyproject.toml  uv.lock  Dockerfile  .gitlab-ci.yml  .github/workflows/
  config/settings.toml  config/stations.toml  config/params.toml
  src/pvt/ingest/{ecmwf.py,obs_xml.py,kliima_api.py,bufr.py,kaur_forecast.py}
  src/pvt/extract/points.py  src/pvt/qc/obs_qc.py
  src/pvt/verify/{continuous.py,wind.py,categorical.py,seeps.py,probabilistic.py,significance.py}
  src/pvt/ml/{baselines.py,mos.py,cv.py}
  src/pvt/site/build.py  src/pvt/monitor/freshness.py
  tests/  site/ (index.html, js/, data/)  docs/00–08
```

### 3. Skeemid (ettepanek, `schema_version = "1.0.0"`)
**forecast_point** (üks rida = mudel × jooks × valid × jaam × liige): `model_id`, `model_cycle`, `issue_time_utc`, `valid_time_utc`, `lead_h` (int16), `station_id`, `member` (deterministlik = −1), `t2m_degC`, `t2m_hcorr_degC`, `u10_m_s`, `v10_m_s`, `wind10m_speed_m_s`, `wind10m_dir_deg`, `mslp_hPa`, `precip_acc_mm`, `grid_lat_deg`, `grid_lon_deg`, `grid_orog_m`, `grid_lsm_frac`, `interp_method`, `provenance` (= `prognoos`), `source_uri`, `retrieved_at_utc`, `ingest_version`, `schema_version`.
**obs**: `station_id`, `valid_time_utc`, `t2m_degC`, `wind10m_speed_m_s`, `wind10m_dir_deg`, `gust10m_m_s`, `mslp_hPa`, `precip_1h_mm`, `provenance`, `source` (`ilmateenistus_xml` / `kaur_bufr` / `kaur_kliima_hly`), `qc_flags` (bitmask), `retrieved_at_utc`.
**station**: `station_id`, `wmo_code` (kui allikas annab), `name`, `lat_deg`, `lon_deg` (EPSG:4326), `x_3301_m`, `y_3301_m`, `height_m_EH2000`, `source_uri`, `verified` (bool).
**score**: `model_id`, `ref_model_id`, `variable`, `truth_level`, `lead_h`, `issue_hour_utc`, `station_id` (või `ALL`), `period`, `n`, `n_eff`, `me`, `mae`, `rmse`, `corr`, `ss_mae`, `ss_mse`, `ci_low`, `ci_high`, `dm_stat`, `dm_p`, `dm_p_fdr`.

### 4. Ajastus
- `ingest_ecmwf`: iga 2 h minutil :17 (GitHubi dokumentatsioon hoiatab, et ajastatud käivitused võivad suure koormuse ajal, eriti täistunnil, hilineda);\[31\] töö kontrollib iga jooksu ja mudeli kohta, kas see on juba arhiveeritud, ning laeb alla puuduvad, mis on veel rullarhiivis (**idempotentne**). **Fakt:** ecmwf-opendata README (ECMWF, GitHub): „The data is available between 7 and 9 hours after the forecast starting date and time, depending on the forecasting system and the time step specified"; AIFS avaldatakse kohe valmimisel, 0,1° IFS 2 h pärast 0,25°.
- `ingest_obs_xml`: iga 10 min, sest XML-il pole ajalugu.
- `ingest_kaur_fc`: iga tund hetkepilt; salvestada ainult, kui sisu räsi muutus.
- `ingest_kliima`: 1× ööpäevas (KAUR: andmed uuenevad kord ööpäevas; kellaaeg Teadmata – mõõda `max(valid_time)` muutumisest).\[12\]\[32\]
- `score` + `build_site`: 1× ööpäevas 08:00 UTC.

### 5. Variant A – GitHub Actions + Pages
- Runner: avalikus repos `ubuntu-latest` 4 vCPU, 16 GB RAM, 14 GB SSD; töö maksimaalne kestus 6 h (privaatses repos 2 vCPU/8 GB).\[5\]\[33\]
- Keepalive: igakuine automaatne commit (`status/heartbeat.json`) või väline jälgija + workflow uuesti lubamine API kaudu.
- Arhiivi ei hoita git-ajaloos (repo soovituslik piir 1 GB); kuuarhiivid Release'i varadena või väliselt.\[6\]
- Pages: ainult sait + koondandmed (≤ 1 GB), deploy custom Actions workflow'ga.
- Saladused: GitHub Secrets (MVP ei vaja – ECMWF ja KAURi avaandmed ei nõua võtit).

### 6. Variant B – GitLab (gitlab.sise.envir.ee) CI + Pages (soovitatud)
- `.gitlab-ci.yml` etapid `lint → test → ingest → score → pages`; ajastus „Pipeline schedules" kaudu (UTC cron).
- Runner: KAURi sisemine Docker-runner (Teadmata: olemasolu, ressursid, välisvõrk).
- Salvestus: võrguketas või S3-ühilduv objektisalvestus (Teadmata); varundus KAURi standardi järgi.
- Pages: GitLab Pages, ligipääsukontroll kui instants toetab (Teadmata). Saladused: CI/CD masked variables.

### 7. Monitooring
- `freshness.json`: iga allika viimane aeg ja vanus; lävi: ECMWF > 18 h, vaatlused > 2 h, kliima > 48 h → pipeline punaseks + teavitus (kanal Teadmata).
- Puuduvate jooksude raport: oodatud 4 + 4 jooksu ööpäevas vs arhiveeritud; saidi „Andmete seis" lehel.

### 8. Turvalisus, litsentsid, õigus
- **ECMWF:** CC BY 4.0 ja ECMWF-i kasutustingimused; kogu reaalaja kataloog on avatud alates 01.10.2025; ECMWF-i näidisviide: „Adapted from 'ECMWF IFS 15-day Forecast Data' by ECMWF, licensed under CC BY 4.0". ECMWF Confluence'i DAC-lehe järgi on portaali ligipääs „limited to between 500 to 2000 simultaneous connections"; data.ecmwf.int avaleht ütleb 2000 ja ecmwf-opendata README 500 – konservatiivne eeldus on 500.
- **KAUR:** XML-i kasutamise tingimus on viide Keskkonnaagentuurile ja link ilmateenistus.ee-le; keskkonnaportaali levitused on CC BY 4.0.\[22\]\[29\]\[34\]
- **GDPR:** isikuandmeid ei töödelda; veebianalüütikat MVP-s ei kasutata (Soovitus); serverilogid (IP) – kontrolli andmekaitsespetsialistiga.
- **TI määrus (Tõlgendus, vajab juristi kinnitust):** eksperimentaalne järeltöötlus sisemiseks analüüsiks ei paista kuuluvat suure riskiga valdkondade alla; sellegipoolest märgistus „eksperimentaalne, mitteametlik", inimjärelevalve ja ML-i ei kasutata hoiatuste koostamisel.
