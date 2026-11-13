# Etapp E1 – `pvt ingest-ecmwf` + `pvt monitor`

**Kuupäev:** 2026-11-13 · **Haru:** `claude/modest-johnson-mo063h` · **Staatus:** valmis ja päris
andmetel kontrollitud; **ajastatud käivitus veel puudub** (vt avatud küsimus 1).

## Mis tehti

| Osa | Fail | Sisu |
|---|---|---|
| Ingest | `src/pvt/ingest/ecmwf.py` | Iga mudeli (IFS, AIFS Single) iga jooksu kohta look-back-aknas (vaikimisi 96 h): kui jooks pole `complete`, leitakse peegel, mille indeksifailides on viimane oodatud samm; **tegelikud sammud loetakse indeksifailide olemasolust**; allalaadimine `ecmwf-opendata` indeksipõhiste baidivahemikega 12 sammu kaupa; GRIB kustutatakse kohe; Parquet + manifest kirjutatakse aatomiliselt. |
| GRIB | `src/pvt/ingest/ecmwf_grib.py` | ecCodes; koordinaadid loetakse GRIB-ist ja normaliseeritakse [−180, 180); kast 57,25–60,25° N × 21,00–28,75° E (416 punkti, ADR-015); ainult lubatud (shortName, typeOfLevel) paarid; pakkimiskvant salvestatakse. |
| Ühikud | `src/pvt/units.py` | Teisendus GRIB-i `units`-võtme järgi: K→°C, Pa→hPa, `m`→mm (IFS tp), `kg m**-2`→mm (AIFS tp), m²/s²→m (÷9,80665). Tundmatu ühik → jooks `failed`. |
| Kontrollid | `ingest_run`, `schemas.validate` | jooksu- ja kehtivusaeg GRIB-ist = oodatud; tp akumuleeritud algusest (`stepRange 0-N`); kõik (samm, parameeter) täpselt üks kord; ühine ruudustik; skeem/tüübid/päritolu/võtme unikaalsus/`lead_h`; tp ei kahane rohkem kui pakkimistäpsus lubab. |
| Monitor | `src/pvt/monitor/freshness.py` | `status/freshness.json` (vanus vs lävi 18 h), `status/ecmwf_inventory.json` (14 päeva oodatud vs arhiveeritud jooksud koos põhjusega), `generatingProcessIdentifier` muutuse hoiatus; exit 1 = vananenud või (täielikult kaetud aknas) < 95 % jooksudest. |
| CI | `.gitlab-ci.yml`, `.github/workflows/ingest.yml`, `ci/github_release_sync.py` | GitLab: ajastus `17 */2 * * *` UTC, `resource_group` (üks kirjutaja), nõuab püsivat `PVT_DATA_ROOT`. GitHub: sama ajastus, arhiiv kuupõhistes Release'ides `ecmwf-archive-YYYY-MM`, keepalive. |

Arhiivi skeem `forecast_grid` (schema_version 1.0.0): `model_id, model_cycle, grib_gen_proc_id,
issue_time_utc, valid_time_utc, lead_h, member, grid_lat_deg, grid_lon_deg, t2m_degC, u10_m_s,
v10_m_s, mslp_hPa, precip_acc_mm, precip_acc_start_h, precip_acc_quantum_mm, provenance (=prognoos),
source_uri, ingest_version, schema_version`; `forecast_static`: `grid_orog_m, grid_lsm_frac` jooksu
kaupa. `retrieved_at_utc`, peegel, baidid ja kestus on manifestis, mitte Parquetis – nii annab sama
jooksu kordusallalaadimine baidiliselt sama faili (docs/06 §2). docs/03 `forecast_point` (jaamapunkt
koos `retrieved_at_utc`-ga) tuletatakse sellest etapis E2.

## Vaatlused ja mõõtmised (Fakt = vaadeldud 2026-11-13; allikas sulgudes)

| # | Leid | Mõju |
|---|---|---|
| F1 | IFS 06/18 UTC jooksul on sammud **0–144 h iga 3 h** (49 sammu), 00/12 UTC 85 sammu, AIFS kõigil 61 sammu (AWS-i objektiloend, jooksud 2026-11-12). | docs/01 §2 vastuolu lahendatud vaatlusega; Confluence'i „0–90 h" on vananenud. Kood ei eelda – kontrollib iga jooksu. |
| F2 | AWS-peeglis on kuupäevakaustad **alates 2023-01-18**; IFS ja AIFS olemas nt 2024-03-01, 2025-06-01, 2026-03-01 (S3 ListObjects). | Ajaloo täitmine võib olla võimalik ilma MARS-ita (ADR-016). AWS-i säilituspoliitikat ei leitud – arhiiv ei tohi sellele toetuda. |
| F3 | tp ühik: IFS `m`, AIFS `kg m**-2`; mõlemal akumuleeritud jooksu algusest (GRIB `units`, `stepRange`). | Kaudne teisendus oleks andnud AIFS-ile 1000× vea. |
| F4 | Mõlemad mudelid: `longitudeOfFirstGridPoint = 180`, ecCodes annab −180…179,75 (GRIB). | Kast leitakse GRIB-i koordinaatidest; test katab 0…360 ja −180…180 konventsiooni. |
| F5 | IFS-i ja AIFS-i `z` ja `lsm` erinevad (nt 59,5° N 24,5° E: lsm 0,16 vs 0,49; z/g 6,4 m vs 12,8 m) (GRIB). | Kõrguskorrektsioon ja lähim maapunkt tuleb teha **mudelipõhiselt** (E2). |
| F6 | **tp pakkimiskvant** (12 bitti): IFS 0,06 → 0,24 mm (06Z, 0–144 h), AIFS 0,06 → 0,25 mm (0–360 h). Akumulatsioon kahanes päris andmetes kuni poole kvandi võrra (IFS 60 korda, min −0,122 mm; AIFS 3 korda, −0,0625 mm). | Esimene päris-ingest lükati QC-ga tagasi; parandatud: tolerants (q₁+q₂)/2, kvant salvestatakse veergu `precip_acc_quantum_mm`. **Metoodiline mõju: vt avatud küsimus 5.** |
| F7 | `generatingProcessIdentifier`: IFS 161, AIFS 5 (GRIB). | Salvestatakse; monitor hoiatab muutusel (võimalik mudelivahetus). |
| F8 | data.ecmwf.int, www.ilmateenistus.ee, keskkonnaandmed.envir.ee: arenduskeskkonna võrgupoliitika keelas (403 CONNECT). AWS: korduvalt 503 SlowDown; Google: 1,5–3,5 MB/s ilma vigadeta. | Peeglite järjekord `google → aws → azure → ecmwf`. KAURi allikad: vt avatud küsimused 2–4. |

**Päris-ingest, jooks 2026-11-12 06 UTC** (AWS, koos 503-kordustega; ingest_version `d60730152b66`):

| Mudel | Samme | Ridu | Parquet | Kestus | Märkus |
|---|---|---|---|---|---|
| IFS | 49 | 20 384 | 186 KB (+ 7,7 KB static) | 379 s | `complete` |
| AIFS Single | 61 | 25 376 | 216 KB (+ 7,8 KB static) | 489 s | `complete` |

Mälu max 203 MB. Väärtused mõistlikud: analüüsihetkel Tallinna lähedal (59,5° N 24,75° E) IFS 4,38 °C /
997,34 hPa, AIFS 4,59 °C / 997,32 hPa. Kordusjooks: mõlemad vahele jäetud 0,4 s-ga, võrgupäringuid ei
tehtud. Monitor: exit 1 („stale", vanus 24,9 h) – õige, sest arhiveeritud oli ainult üks jooks.

**Idempotentsus päris andmetel:** AIFS-i sama jooks uuesti `--force --source google` → 142,3 MB
allalaadimist, 105 s, ja **baidiliselt identne** Parquet AWS-ist laaditud failiga (SHA-256 võrdne).
Seega on ka peeglid omavahel vahetatavad.

**Hinnang mahule** (mõõdetud failidest ekstrapoleeritud): arhiiv IFS 00/12 ~0,33 MB, 06/18 ~0,19 MB,
AIFS ~0,22 MB jooksu kohta → ~2 MB ööpäevas, ~0,7 GB aastas. Allalaadimine: AIFS 142 MB jooksu kohta
(mõõdetud), IFS-i jaoks hinnanguliselt ~140 MB (06/18) ja ~240 MB (00/12) → ~1,3 GB ööpäevas. Kestus:
Google ~2 min, AWS 6–8 min jooksu kohta → 8 jooksu ööpäevas ≈ 15–60 min runneri aega.

## Testid

- `uv run pytest`: **63 passed** (võrguta). `uv run pytest -m network`: **2 passed** (IFS ja AIFS,
  päris peegel, 1 samm + static).
- `ruff check`, `ruff format --check`, `mypy` (strict, `src/pvt` + `ci/`): puhtad.
- Kaetud: naiivne datetime, ühikud (sh tundmatu ühik), kasti väljalõige kolme pikkuskraadi
  konventsiooniga, rõhupinna-väljade vahelejätmine, vale ruudusamm, peegli varuvalik, osaline jooks ja
  selle hilisem lõpetamine, noor/vana puuduv jooks, rikutud arhiivifaili taastamine, baidiline
  idempotentsus (`--force`; päris andmetel vt eespool), katkestus, puuduv parameeter, kahanev akumulatsioon (üle/alla
  pakkimistäpsuse), monitori vananemine ja inventuur, `shuffle=True`/naiivse `now()` staatiline keeld.

## Eeldused (kontrollimata või töö-otsused)
1. Mudelitsükkel määratakse tabelist (`config/params.toml`): IFS 50r1 ja AIFS v2 alates 2026-05-12
   (ECMWF uudis). **Kas 2026-05-12 ja täna vahel on uus tsükkel tulnud – ei kontrollinud.**
2. Backfill enne 2026-05-13 06 UTC on koodis keelatud (vt ADR-016).
3. `partial_after_hours = 14`: kui jooks on 14 h vana ja mõni oodatud samm puudub, arhiveeritakse
   olemasolev (`partial`) ja proovitakse uuesti, kuni jooks on look-back-aknas.
4. Värskuse lävi 18 h, inventuuri aken 14 päeva, 95 % (docs/03 §7, docs/06 §4).

## Avatud küsimused (vajavad sinu otsust/sisendit)

1. **Kus ajastatud ingest jookseb?** Kood on valmis, kuid arhiiv ei kogune enne, kui üks variant töötab:
   (a) GitLab: vaja runnerit välisvõrguga (Google/AWS peeglid) ja püsivat kataloogi `PVT_DATA_ROOT`
   (docs/07 K1–K3); (b) GitHub: `ingest.yml` hakkab tööle alles pärast mestimist vaikeharusse
   (ajastus töötab ainult seal) ja hoiab arhiivi Release'ides. Kumba alustada?
2. **E1b on blokeeritud:** vaatluste XML-i ja eesti-prognoosi XML-i formaati (ajatempli atribuut, jaamade
   arv) ei saanud kontrollida – www.ilmateenistus.ee on selle keskkonna võrgupoliitikaga keelatud. Kas
   lubad hosti keskkonna seadetes või lisad näidisfailid (`observations.php`, `forecast.php`,
   `forecast.php?lang=eng`) repo `tests/fixtures/` alla?
3. **Kliima-API:** keskkonnaandmed.envir.ee on samuti keelatud. Keskkonnaportaali kasutusjuhendist on
   kinnitatud ainult: levitus `f_kliima_paev` ja metaandmed `f_kliima_element`; veerud `element_kood`,
   `jaam_nimi`, `aasta`, `kuu` (UTC); 20 000 rida päringu kohta; uuendus „tavaliselt öösel kella 3–5
   vahel" (ajavöönd märkimata). **Teadmata:** tunniandmete levituse nimi, filtrite ja lehekülgede
   süntaks. Peatun siin docs/08 järgi – palun API näidis-URL (allalaadija „Loo rakendusliidese
   aadress") või hosti lubamine.
4. **Jaamade koordinaadid ja EH2000 kõrgused:** `config/stations.toml` sisaldab 25 jaama koodi ja nime
   (kliimaandmestiku kirjeldusest), kõik `verified = false`. Allikas („Seirejaamade metainfo",
   ilmateenistus.ee vaatlusvõrgu lehed) ei olnud ligipääsetav. Lisaks: kas XML-i `wmocode` ↔ kliima
   kood (AJ…) vastavustabel on KAURis olemas?
5. **Sademete täpsus (F6):** avaandmete tp lahutus on 0,06–0,25 mm (pikematel etteannetel IFS 00/12
   tõenäoliselt suurem – mõõtmata). 24 h summa kui kahe akumulatsiooni vahe on täpne ±(q₁+q₂)/2, s.t
   samas suurusjärgus kui ADR-005 lävi 0,2 mm ja SEEPS-i „kuiva" piir 0,25 mm. Ettepanek E2-ks:
   kanda 24 h summale veapiir kaasa, negatiivne vahe → 0 lipuga, ja tõsta väikseim kategooriline lävi
   ≥ 0,5 mm **või** rakendada läve ainult siis, kui veapiir seda lubab. Kas see sobib või muudame
   ADR-005-t?
6. **Backfill AWS-ist (F2):** kas soovid ajalugu (nt 2026-05-13 → täna, ~6 kuud ≈ 1 440 jooksu; hinnanguliselt
   ~240 GB allalaadimist ja 50–170 h runneri aega mõõdetud kiirustel)? Enne 2026-05-13 vajab eraldi tööd.

## Mida kontrollida
- `uv run pvt ingest-ecmwf --dry-run` sihtkeskkonnas (runneri välisvõrk, peeglite kiirus).
- `uv run pytest -m network` sihtkeskkonnas.
- Pärast ajastuse käivitamist: 14 päeva järel `status/ecmwf_inventory.json` → vastuvõtukriteerium 1
  (≥ 95 % jooksudest).
- ECMWF-i muudatuste leht: kas pärast 50r1/AIFS v2 on tulnud uus tsükkel (uuenda `model_cycles`).
