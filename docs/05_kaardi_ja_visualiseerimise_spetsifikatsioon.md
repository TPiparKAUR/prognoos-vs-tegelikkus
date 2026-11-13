<!-- Extracted from the project package (v0.1, 2026-11-13). Numbered references [n] point to docs/README.md#allikad -->

# 05_kaardi_ja_visualiseerimise_spetsifikatsioon.md

**Pealkiri:** Kaardi ja visualiseerimise spetsifikatsioon
**Versioon:** 0.1 · **Kuupäev:** 2026-11-13 · **Soovitatud failinimi:** `docs/05_kaardi_ja_visualiseerimise_spetsifikatsioon.md`

### 1. Vaated
1. **Vigade kaart (põhivaade):** jaamad punktidena; **bias/ME divergentse skaalaga** (null keskel), **MAE/RMSE järjestikuse skaalaga**; sümboli suurus = valimi suurus n; õõnes sümbol, kui n < miinimum. Filtrid: muutuja, mudel, etteanne (liugur), väljastusaeg, hooaeg/kuu, tõetase (T1/T2).
2. **Mudel A − mudel B kaart:** värv = MAE_A − MAE_B (divergentne), kontuur = oluline (DM-HLN + FDR).
3. **Skoor vs etteanne:** mudelite jooned bootstrap-usaldusribaga; referentsid katkendjoonena.
4. **Scorecard**, **Taylori diagramm**, **performance diagram**, ööpäevatsükli graafik, jaama detailvaade (vaatlus, IFS, AIFS, MOS).
5. **Andmete seis:** puuduvad jooksud, värskus, versioonid.
6. **Lisa (faas 3):** ruudustiku vigade kaart ERA5 või analüüsi vastu märgisega „reanalüüs/analüüs ≠ mõõtmine".

### 2. Interpoleerimine
- **Soovitus:** vigade pinda MVP-s **ei interpoleerita** – harva võrgu korral loob pind veenva, kuid toetamata välja ning vead sõltuvad kohalikust ekspositsioonist (rannik). Hiljem ainult kriging'u kaudu koos standardhälbe kaardiga ja maskiga kaugemal kui X km lähimast jaamast.

### 3. Tehnoloogia
- MapLibre GL JS; jaamad GeoJSON-ina (EPSG:4326); veebikaardi projektsioon EPSG:3857; EPSG:3301 andmetes/ekspordis.
- Aluskaart: iseteenindatav PMTiles fail või Maa- ja Ruumiameti aluskaart (kasutustingimused – kontrolli).
- Diagrammid: Observable Plot või ECharts; üks teek kogu saidil.
- Päringud: eelarvutatud JSON; DuckDB-WASM Parquetile uurimisvaates (HTTP range-päringute tugi – kontrolli).
- Tõeliselt interaktiivse päringu vajadusel: väike sisemine API (FastAPI + DuckDB) – mitte MVP.

### 4. UX ja ligipääsetavus
- WCAG 2.1 AA: kontrast ≥ 4,5:1; kaardi info ka tabelina; klaviatuuriga navigeeritav; värv pole ainus infokanal.
- Värvid: Okabe-Ito mudelijoontele; ColorBrewer RdBu bias'ile, viridis järjestikusele.
- Aeg: Eesti aeg märgisega „EET/EEST", tööriistavihjes ka UTC.
- Päis igal lehel: „Eksperimentaalne, mitteametlik. Ei asenda KAURi ametlikku prognoosi ega hoiatusi." + viited (KAUR, ECMWF CC BY 4.0).
- Mobiil: kaart + üks diagramm vertikaalselt; filtrid sahtlis.
