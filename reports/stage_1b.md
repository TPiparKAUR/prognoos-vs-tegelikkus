# Etapp E1b – KAURi allikad, jaamaregister, jaamapõhine ECMWF-arhiiv, GitHubi käitus

**Kuupäev:** 2026-11-13 · **Haru (= repo vaikeharu):** `claude/modest-johnson-mo063h`

## Tellija otsused, mis siin ellu viidi
| Otsus | Teostus |
|---|---|
| Kõigi jaamade koordinaadid; ECMWF salvestada ainult jaamade kohal | `config/stations.toml` kliima-API-st; ADR-015 muudetud: arhiveeritakse ainult jaamade stencil-punktid |
| Väike, kuid detailne arhiiv | Toorväärtused 4 ümbritsevas + lähimas maapunktis, kaalud; jaamaväärtused tuletatakse (`load_points`) |
| Sademed: täpsem variant | ADR-005 muudetud: veapiir kaasa, kolmene klassifikatsioon (jah/ei/ebamäärane) – teostus E2 |
| Backfilli ei tehta | lookback 96 h, ühe käivituse piirang 12 jooksu / 75 min |
| Rakendus jookseb GitHubis | töövood `ingest-ecmwf` (iga 2 h), `ingest-kaur` (iga 10 min), `ingest-kliima` (2× päevas), `monitor` (iga 6 h); arhiiv avalikes Release'ides |

## Mis tehti
- **Jaamaregister** (`pvt sync-stations`): 25 kliimajaama tabelist `f_kliima_jaam_vaatlus`
  (keskkonnaandmed.envir.ee, PostgREST 12), **kehtiva perioodi** koordinaadid ja kõrgus. Kolinud
  jaamad (Kunda 2013, Kuusiku 2003, Narva 2013, Pakri 2003, Pärnu 2018, Ruhnu 2019, Valga 2011)
  saavad praeguse asukoha. Kontroll: Pakri 59,3895/24,0401 ja Pärnu 58,38457/24,48512 ühtivad
  vaatluste XML-iga. WMO-koodid 23 jaamale XML-ist.
- **Vaatluste XML** (`pvt ingest-obs-xml`, T1): ajatempel = Unix epohh (UTC); veerunimed
  järgivad XML-i elemente + ühikuid; toores XML (gzip) ja päeva-Parquet; duplikaadid
  (sama ajatempel või räsi) jäetakse vahele; uued XML-jaamad registrisse
  `meta/xml_met_stations.parquet` (kinnitamata, ECMWF arhiveeritakse ka nende kohal).
- **Eesti prognoos XML** (`pvt ingest-kaur-fc`): est + eng; salvestatakse ainult sisu
  muutumisel; tabelid `kaur_fc_period` ja `kaur_fc_detail` (kohad ja tuulepunktid).
- **Kliima-API** (`pvt ingest-kliima`, T2): `f_kliima_tund`, elemendid TA, PR1H, WS10M, WD10M,
  WSX1H, PA0, RH; lehekülgede kaupa; ühik kontrollitakse API vastusest; viimased 10 päeva
  laaditakse uuesti; päevafail kirjutatakse ainult muutusel.
- **ECMWF jaamapõhiselt**: stencil-arhiiv + kaalud; meetodid `bilinear`, `nearest`,
  `nearest_land`; `t2m_hcorr_degC` (0,0065 K/m), tuule kiirus/suund u/v-st; IFS puhang `10fg`.
- **Salvestus** `data/<andmestik>/AAAA/KK/PP/`; GitHubi Release'ides üks tar andmestik-päeva kohta.
- **Monitor**: värskus kõigile neljale allikale + 14 päeva ECMWF-inventuur.

## Vaatlused ja mõõtmised (Fakt, 2026-11-13)
| # | Leid | Mõju |
|---|---|---|
| G1 | Kliima-API tunniandmed: eilne 23 UTC avaldati 05:02 EET (03:02 UTC); 600 jaam-tundi ööpäevas (25 × 24). | T2 viide ~1 ööpäev; monitori lävi 48 h. |
| G2 | API hoiab **revideeritud väärtuste varasemaid versioone** (nt AJNARV01 2026-11-11 20 UTC PA0: 1002,7 → 1002,8, avaldusajad 06:00 ja 07:00 EET); kahe päeva peale 21 asendatud väärtust. | Kasutatakse viimast avaldust; sama avaldusajaga erinevad väärtused = viga. |
| G3 | IFS `10fg` (puhang): `stepType=max`, aken 1 h (0–90 h, iga 3 h) ja 6 h (150–360 h); **sammudel 93–144 puudub** (indeksid 00Z ja 06Z). AIFS-il puhangut pole. | Puhang on valikuline parameeter; manifest loetleb sammud. |
| G4 | Tallinn-Harku, IFS 2026-11-12 12Z, analüüs: t2m `nearest` 6,75 °C (lsm 0,16; 12,7 km), `nearest_land` 5,50 °C (lsm 1,0; 17,5 km), `bilinear` 6,07 °C. | Rannikujaamades on meetodi valik suurusjärgus 1 °C – mõlemad salvestatakse, E3 võrdleb. |
| G5 | Arhiivi maht 25 jaamaga: IFS 00/12 ~121 KB, AIFS ~80 KB jooksu kohta (grid + static + weights) → ~0,7 MB ööpäevas (kastiga oli ~2 MB). | XML-i lisajaamadega kasvab stencil ~3–4×. |
| G6 | Punktifail (tuletatud väärtused) oli 2,5× suurem kui toorstencil. | Punkte ei salvestata; `load_points()` tuletab need deterministlikult. |
| G7 | Repo on avalik ja vaikeharu on `claude/modest-johnson-mo063h`; GitHubi CI oli kõigil commit'idel roheline. | Pärast pushi jooksevad ajastatud töövood kohe. |
| G8 | GitHubist on ilmateenistus.ee kättesaadav; `ingest-kaur-fc` ja `ingest-kliima` töötasid esimesel käivitusel, Release `archive-2026-11` loodi. | Ahel GitHub → Release toimib. |
| G9 | Vaatluste XML-i `timestamp` = **päringu aeg** (päring 08:38:43Z → 08:38:43Z), mitte mõõtmisaeg. | Duplikaadid tuvastatakse sisu räsiga ilma ajatemplita; mõõtmisaeg tuletatakse E2-s. |
| G10 | Päris XML-is **korduvad jaamanimed** (esimene jooks: 2, teine 37 konflikti meie võtmega). | Jaama tunnus = nimi + asukoht + WMO; kliimajaam eraldi veerus `kliima_station_id`; konfliktid nimetatakse veateates. |
| G12 | Päris XML 2026-11-13 08:41Z: 153 kohta, kõigil koordinaadid; õhutemperatuur 95, tuul 40, sademed 49, õhurõhk 27 jaamal; Tooma kliimajaama 1 km raadiuses ~37 kaevu/veetaseme punkti; nimi „Uue-Lõve" kahe eri jaama nimena. | ECMWF arhiveeritakse ainult meteoparameetreid mõõtvatel XML-jaamadel (`meta/xml_met_stations.parquet`). |
| G11 | KAURi prognoosi XML muutus 08:37 → 08:38 UTC (päevatekst ja Peipsi tekst uuendati) – kaks versiooni salvestati õigesti. | Muutuse tuvastus töötab; KAUR uuendab prognoosi ka hommikul. |

## Testid
`uv run pytest`: **76 passed** (võrguta). Uued: XML-parserid fixture'itel (sinu kleebitud
näidete alamhulk, `tests/fixtures/README.md`), duplikaadid, vigane XML, prognoosi muutuse
tuvastus, kliima revisjonid/ühikud/lehekülgede kaupa pärimine, stencil ja kaalud (bilineaarne
täpne lineaarsele väljale, lähim maapunkt merejaamale), tuule suund, valikuline puhang,
käivituse piirang, tar-pakkide determinism. `ruff`, `mypy --strict`: puhtad.
Päris andmetel: ECMWF IFS + AIFS 2026-11-12 12Z; kliima-API 2026-11-11…13.

## Kontrollitud GitHubis (2026-11-13)
- `ingest-kliima`: õnnestus esimesel käivitusel.
- `ingest-kaur`: prognoosi-XML õnnestus kohe; vaatluste XML kukkus kahel esimesel käivitusel
  (G9, G10), parandatud – kolmas käivitus õnnestus, arhiiv `obs_xml_2026-11-13.tar` ja
  `meta.tar` Release'is.
- `ingest-ecmwf`: esimene käsitsi käivitus õnnestus (17 min): 12 jooksu (IFS 00Z: 85 sammu,
  280 MB, 122 s; AIFS: 61 sammu, 142 MB, ~60 s; Google-peegel), Release'is
  `ecmwf_2026-11-11/12/13.tar`; 18 jooksu jäi limiidi tõttu järgmisele käivitusele →
  limiit tõstetud 40-le (75 min ajapiir jääb kaitseks).
- `ingest-ecmwf` teine käsitsi käivitus (09:32–09:44 UTC) arhiveeris ülejäänud 18 jooksu
  (kuni 2026-11-09 12Z); 96 h aken on täis, piirangu hoiatust polnud. Google-peeglist
  IFS 00/12 ~55 s, IFS 06/18 ~32 s, AIFS ~30 s jooksu kohta.
- **Ajastatud käivitusi (cron) ei olnud ka 10:33 UTC seisuga ühelgi töövool** (ka mitte
  `ci`/`keepalive`), kuigi töövood on olekus „active" ja vaikeharul. Repo seadeid ma ei muuda;
  omanik peab kontrollima Settings → Actions → General (Actions lubatud, töövood lubatud).

## Avatud küsimused
1. **Asukohaprognoos** (ADR-017, sinu peamine soov): vajan andmepäringu URL-i. Kas lubad
   `www.ilmateenistus.ee` keskkonna võrguseadetes või saadad brauseri DevToolsist
   (Network → Fetch/XHR) meteogrammi päringu URL-i ja vastuse näidise?
2. Kliima-API kõrgus „above mean sea level (Amsterdam)" – kas see on EH2000? (Tõenäoliselt
   jah, kuid kinnita KAURist; vastasel juhul `verified` ümber.)
3. XML `airpressure`: jaama- või merepinna rõhk? (Tallinn-Harku XML 984,1 vs PA0 merepinnal
   990,2 eri aegadel – ei saa otsustada.)
4. PR1H: kas tund `tund = h` tähendab summat (h−1, h] UTC? (Eeldatud.)
5. Avalikud Release'id sisaldavad KAURi toorandmeid (viide + link igas Release'i kirjelduses).
   Kas see sobib või hoiame arhiivi privaatses kohas?

6. **BUFR-toorandmed (kandidaat T1-allikaks):** Keskkonnaportaali „Meteoroloogilise seire
   andmestik" kirjeldab BUFR-faile (10 min ja 1 h, viimased 24 h, mõõtmisaeg failis, õhurõhk
   eraldi jaama kõrgusel ja merepinnal) failihoidlas `https://avaandmed.keskkonnaportaal.ee/dhs/Active`.
   See lahendaks XML-i mõõtmisaja ja rõhu küsimused (G9, küsimus 3). Host on siin blokeeritud
   ja failiteid ma ei oleta – kas lubad hosti või saadad failihoidla kataloogi näite?

## Järgmine etapp (E2)
Paarid ja QC: jaamaväärtused (`load_points`) × T1/T2 vaatlused ühisel valimil, 24 h sademed
veapiiriga (ADR-005), QC-lipud (docs/01 §10), KAURi prognoosi vastavus kohtadele.
