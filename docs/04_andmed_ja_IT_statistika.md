<!-- Extracted from the project package (v0.1, 2026-11-13). Numbered references [n] point to docs/README.md#allikad -->

# 04_andmed_ja_IT_statistika.md

**Pealkiri:** Andmeallikad, mahud, piirid ja arvutuskulu
**Versioon:** 0.1 · **Kuupäev:** 2026-11-13 · **Soovitatud failinimi:** `docs/04_andmed_ja_IT_statistika.md`

### 1. Andmeallikad
| Allikas | Sisu | Uuendus | Ajalugu | Litsents | Allika järk |
|---|---|---|---|---|---|
| ECMWF open data (data.ecmwf.int/forecasts + AWS/GCP/Azure) | IFS oper/enfo 0,25° ja 0,1° (alates 20.10.2026); AIFS Single/ENS 0,25° | 4 jooksu ööpäevas | Rullarhiiv: „Data are retained for the most recent 12 forecast runs, corresponding to approximately 2–3 days of forecasts" (ECMWF Open data leht) vs „kuni neli päeva" (AIFS How-To) | CC BY 4.0 | ECMWF ametlik (mõlemad); kasuta konservatiivset 2 päeva |
| ECMWF arhiiv (MARS) | AIFS Single alates 2024-02, AIFS ENS alates 2025-07; IFS ajalugu\[3\] | – | Pikk | CC BY 4.0; registreerimine ja teenustasud võivad kehtida | ECMWF ametlik\[35\] |
| Vaatluste XML (ilmateenistus.ee/ilma_andmed/xml/observations.php) | name, wmocode, longitude, latitude, airtemperature, windspeed, windspeedmax, winddirection, airpressure, relativehumidity, precipitations (viimase tunni mm) jm\[34\] | 10 min või tund (parameetri järgi)\[34\] | Puudub (hetkepilt) | Viide KAURile + link; keskkonnaportaalis CC BY 4.0 | KAUR ametlik\[34\] |
| BUFR (keskkonnaportaal) | Valideerimata 10 min ja 1 h andmed viimase 24 h kohta;\[23\] 25 jaama 10-min loendis, 22 jaama 1-h loendis | 10 min/1 h | 24 h | CC BY 4.0 | KAUR ametlik\[13\] |
| Kliimaandmestik (keskkonnaandmed.envir.ee API, JSON) | Valideeritud 10M (alates 2011), HLY (2004), DLY ja MLY (1991); elemendid nt PR1H, DPREC, TA, WS10M, WSX1H, PA0\[12\] | 1× ööpäevas | Pikk | CC BY 4.0 | KAUR ametlik\[12\]\[22\] |
| Eesti prognoos XML (forecast.php, ?lang=eng, ?lang=rus) | 4 ööpäeva + järgmise öö/päeva punktiprognoos\[29\] | Keskpäevaks, vajadusel muudetakse hommikul\[29\] | Teadmata (arhiveerida ise) | Viide KAURile + link | KAUR ametlik\[29\] |
| CLIDATA kliimanormid 1991–2020 (geoportaali metaandmed, EPSG:3301) | Jaamapõhised normid | – | 1991–2020 | Kontrolli | KAUR ametlik\[36\] |

- **Jaamade arv – vastuolu:** ilmateenistus.ee avalehe tekst: „vaatlusandmed 108-st seirejaamast"; kolmanda osapoole (GitHubi issue) kontroll observations.php-st: 154 `<station>` elementi (sisaldab ka hüdromeetria- ja rannikujaamu; kuupäev teadmata).\[37\]\[38\] Kõrgema järgu allikas on KAUR; täpne arv **mõõdetakse** esimesel allalaadimisel.
- **API piir:** keskkonnaportaali allalaadija juhend: ühe päringu piirang 20 000 rida; API kasutaja peab pärima 20 000 rea kaupa.\[39\] Uuenduse kellaaeg (3–5) – **Teadmata**, ametlikust kirjeldusest ei leitud.
- **Ajatsoon:** KAURi mõõtmised toimuvad UTC järgi (kliimaandmestiku kirjeldus).\[12\] Vaatluste XML-i ajatempli atribuut ja formaat – **Teadmata**, kontrolli esimeselt allalaadimiselt.
- **Ajalooliste ilmaandmete levitused:** keskkonnaportaali „Ajaloolised ilmaandmed" levitust uuendatakse kord aastas I kvartalis, ilmateenistus.ee samanimeline leht ütleb, et andmed uuenevad kord ööpäevas.\[22\]\[32\] **Tõlgendus:** kaks erinevat levitust; T2 jaoks kasuta API-t ja salvesta päringu ajatempel.
- **Jaamade ID-d:** kliimaandmestiku kirjeldus loetleb 25 jaama koodidega (nt Tallinn-Harku AJHARK01, Tartu-Tõravere AJTART01, Pärnu AJPARN01); vaatluste XML-is on `wmocode` (näide: Virtsu 26128).\[12\]\[34\] Ülejäänud: **Teadmata – kontrolli** (API metaandmed `f_kliima_element`; vaatlusvõrgu alamlehed annavad koordinaadid ja EH2000 kõrguse).

### 2. Mahuhinnangud (kõik **Hinnang**)
| Näitaja | Hinnang | Arvutus/eeldus | Kuidas mõõta |
|---|---|---|---|
| Prognoosiread ööpäevas (25 jaama) | ~11 900 | IFS: 2×85 + 2×31 = 232 jooksu-sammu; AIFS: 4×61 = 244; (232+244)×25 | `COUNT(*)` päeva partitsioonis |
| Prognoosiread ööpäevas (100 jaama) | ~47 600 | sama × 100 | sama |
| Parquet kasv kuus (25 jaama) | ~5–20 MB | ~25 veergu, zstd, 15–50 baiti/rida | `du -sh` kuu partitsioonil |
| Allalaaditud GRIB ööpäevas, 0,25°, 6 parameetrit | ~1–3 GB | ~2 600 välja × 0,4–1 MB (bits-per-value vähendamine 20.10.2026 vähendab mahtu) | summeeri indeksifaili kirjete pikkused |
| Sama 0,1° IFS-i korral | ~6× IFS-i osas | (0,25/0,1)² = 6,25 | sama |
| Arvutusaeg jooksu kohta (0,25°) | ~3–10 min | võrk + eccodes dekodeerimine | CI töö kestus, p50/p95 |
| Vaatluste XML hetkepildid | ~144 faili ööpäevas, ~22 000 jaama-rida | iga 10 min, 154 jaama | ridade loendus |
| Kliima-API päringud ööpäevas | ~1–5 | 25–100 jaama × 24 h × ~8 elementi < 20 000 rida | logi |
| Skoorid saidil | ~10–50 MB | eelagregeeritud | artefakti maht |
| Retentsioon | prognoosipunktid ja XML hetkepildid: lõputu; toores GRIB: ei säilitata (ainult indeks + räsi) | – | – |

- **Tõlgendus:** maht ei ole piirav; piiravad on rullarhiivi lühidus ja ühenduste piir. GRIB töödeldakse jooksu kaupa ja kustutatakse kohe (runneri ketas 14 GB).\[5\]
