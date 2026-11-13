<!-- Extracted from the project package (v0.1, 2026-11-13). Numbered references [n] point to docs/README.md#allikad -->

# 02_otsuste_logi.md

**Pealkiri:** Arhitektuuri- ja metoodikaotsuste register (ADR)
**Versioon:** 0.1 · **Kuupäev:** 2026-11-13 · **Soovitatud failinimi:** `docs/02_otsuste_logi.md`

Formaat: kontekst · alternatiivid · poolt/vastu · valik · tagajärjed · allikad · staatus · mis muudaks otsust. Kõigi staatus: ettepanek.

**ADR-001 Punktverifitseerimine jaamades (mitte ruudustik)**
- Alternatiivid: (a) jaamapunkt; (b) ruudustik ERA5/analüüsi vastu (WB2-stiil); (c) mõlemad.
- Poolt (a): mõõtmine on tõde, mida juhtrühm mõistab; ECMWF-i SYNOP-verifitseerimine teeb sama. Vastu: esinduslikkusviga, vähe punkte.
- Valik: (a) MVP; (b) lisavaatena faasis 3, märgisega „reanalüüs ≠ mõõtmine". Allikad: Rasp et al. 2024; ECMWF hindamisaruanne. Muudaks: KAURi radari-/analüüsiandmestiku kasutamise soov.

**ADR-002 Mudelid MVP-s: IFS (oper, 0,25°) + AIFS Single (0,25°)**
- Poolt: AIFS on avaandmetes ainult 0,25°; sama ruudustik annab õiglase võrdluse; maht väike. Vastu: 0,1° IFS (alates 20.10.2026, avaldatakse 2 h hiljem, pind ja rõhunivood eraldi failides) oleks rannikul esinduslikum.\[17\]\[30\]
- Valik: 0,25° mõlemale; 0,1° IFS lisatakse teise IFS-variandina pärast mahu mõõtmist. Allikad: ECMWF Confluence avaandmete lehed. Muudaks: KAURi regionaalmudeli väljundi saadavus.

**ADR-003 Tõetasemed T1 ja T2** – vt 01 §10. Muudaks: kui T2 on kättesaadav piisavalt kiiresti (siis T1 ainult monitooringuks).

**ADR-004 Sademete 24 h summa tunnisummadest, mõlema piiriga** – kõik 24 tunnisummat peavad olemas olema, muidu päev välja. Muudaks: KAURi ametlik DPREC-i definitsioon.

**ADR-005 Sademete läved 0,2/1/5/10/20 mm + SEEPS** – alternatiiv protsentiilipõhised läved; absoluutsed on juhtrühmale arusaadavad, SEEPS katab klimatoloogilise konteksti (Rodwell et al. 2010). Muudaks: soov joondada KAURi hoiatuskriteeriumidega.

**ADR-006 Lähim maapunkt + 0,0065 K/m; bilineaarne diagnostikana** – vastuolu 0,0065 vs 5,5 K/km dokumenteeritud. Muudaks: kui bilineaarne annab süstemaatiliselt väiksema MAE.

**ADR-007 ML: tõlgendatav MOS (ridge/GAM) + kohustuslik bias-korrektsiooni baseline; GBM väljakutsujana** – poolt: lühike rida, tõlgendatavus, mudelivahetuste mõju (Vannitsem et al. 2021); vastu: GBM võib leida mittelineaarsusi. Muudaks: 2+ aasta backfill.

**ADR-008 Valideerimine: laienev aken + 15-päevane gap, DM-HLN + plokk-bootstrap + FDR** – juhuslik k-fold on **keelatud** (leakage). Allikad: Harvey et al. 1997; Geer 2016; Wilks 2016.

**ADR-009 Salvestus: Parquet, partitsioon `source/model/year/month`, skeemi versioon** – alternatiivid CSV (standardiga keelatud), Zarr (gridded, MVP-s pole vaja), PostgreSQL/PostGIS (vajab serverit). Muudaks: ruudustiku arhiivi vajadus (siis Zarr + xarray).

**ADR-010 Hosting: sisemine GitLab (primaarne), GitHub avalik peegeldus hiljem** – Fakt (GitHubi dokumentatsioon „GitHub Pages limits"): Pages on „available in public repositories with GitHub Free"; „Published GitHub Pages sites may be no larger than 1 GB"; „deployments will timeout if they take longer than 10 minutes"; „soft bandwidth limit of 100 GB per month"; dokumentatsiooni „Disabling and enabling a workflow" järgi „In a public repository, scheduled workflows are automatically disabled when no repository activity has occurred in 60 days". Muudaks: kui KAURi GitLabil puudub Pages või välisvõrk (siis sisemine VM + nginx).

**ADR-011 Staatiline sait: eelarvutatud JSON/Parquet + MapLibre GL JS; DuckDB-WASM uurimisvaates** – alternatiiv dünaamiline server (FastAPI + DB). Muudaks: vajadus suvaliste päringute järele suurel andmestikul.

**ADR-012 KAURi prognoosi skoor ainult sisevaates kuni avaldamisotsuseni** – mainerisk; vt dok 07.

**ADR-013 Ansamblid (IFS ENS, AIFS ENS) faasis 2** – maht ja keerukus; skeem toetab `member` veergu.

**ADR-014 Python 3.12, uv, Ruff, MyPy (strict uutes moodulites), pytest** – 3.14 ei kasutata, sest eccodes/cfgrib/earthkit binaarrataste tugi tuleb enne kontrollida (Tõlgendus).

---

## Lisatud etapis E1 (2026-11-13)

**ADR-015 Arhiveeritakse Eesti kohal 0,25° ruudupunktide kast, jaamapunkt tuletatakse sellest** (staatus: ettepanek)
- Kontekst: arhiiv peab kohe käivituma, kuid ühegi jaama koordinaadid/EH2000 kõrgus ei ole allikaga kinnitatud (allikas ilmateenistus.ee ei olnud arenduskeskkonnast ligipääsetav). Jaamapõhine väljavõte praegu = tühi arhiiv.
- Alternatiivid: (a) oodata jaamade kinnitamist; (b) väljavõte kinnitamata koordinaatidel; (c) kast 57,25–60,25° N × 21,00–28,75° E (13 × 32 = 416 punkti), jaamapunkt (lähim maapunkt / bilineaarne / kõrguskorrektsioon, ADR-006) tuletatakse etapis E2.
- Poolt (c): arhiiv ei sõltu jaamaloendist; uue jaama lisamine ei vaja uut allalaadimist; bilineaarne interpolatsioon ja lähima maapunkti valik on võimalikud tagantjärele; mudelipõhine orograafia ja maa/mere mask salvestatakse (IFS-i ja AIFS-i `z`/`lsm` erinevad – vaadeldud 2026-11-12 06 UTC jooksus, Tallinna lähedal lsm 0,16 vs 0,49). Vastu: maht ~16× suurem kui 25 jaama korral (mõõdetud väärtus: reports/stage_1.md).
- Valik: (c). Salvestus Parquet (ADR-009); ADR-009 „muudaks"-tingimus (ruudustiku arhiiv → Zarr) ei rakendu, sest kast on väike ja käsitletav punktitabelina. Muudaks: kasti laiendamine või 0,1° IFS (siis Zarr + xarray).

**ADR-016 Pilvepeeglid on esmased allikad; AWS-peeglis on avaandmete ajalugu pikem kui 2–4 päeva** (staatus: ettepanek)
- Fakt (vaatlus 2026-11-13, AWS S3 nimekiri `ecmwf-forecasts`): kuupäevakaustad alates 2023-01-18; IFS 0,25° ja AIFS (`aifs/`, hiljem `aifs-single/`) olemas nt 2024-03-01, 2025-06-01, 2026-03-01. ECMWF-i enda portaal (data.ecmwf.int) hoiab ametlikult ~12 jooksu.
- Tõlgendus: ajaloo täitmine (backfill) võib olla võimalik ilma MARS-ita. Teadmata: AWS-i säilituspoliitika (pole dokumenteeritud allikat leitud) – sellele ei tohi arhiivi ohutus toetuda.
- Valik: allikate järjekord `google → aws → azure → ecmwf` (settings.toml; AWS vastas mõõtmisel korduvalt 503 SlowDown); backfill enne 2026-05-13 06 UTC on koodis keelatud (06/18 UTC `scda` voog enne 50r1; AIFS v2 pikkuskraadi viga), kuni see on eraldi läbi testitud.

---

## Muudatused 2026-11-13 (tellija otsused)

**ADR-005 (muudetud) Sademete läved jäävad, 24 h summale kantakse kaasa pakkimisvea piir** (staatus: kinnitatud tellija poolt)
- Kontekst: ECMWF avaandmete tp lahutus on 0,06–0,25 mm (reports/stage_1.md F6), samas suurusjärgus kui lävi 0,2 mm ja SEEPS-i „kuiv" piir.
- Valik (tellija: „täpsem variant, kontrollitav ja detailne tulemus"): prognoositud 24 h summa = akumulatsioonide vahe ± (q_alg + q_lõpp)/2 (veerg `precip_acc_quantum_mm`). Iga läve puhul klassifitseeritakse sündmus kolmeks: **jah** (alumine piir ≥ lävi), **ei** (ülemine piir < lävi), **ebamäärane** (muidu). Skoorid arvutatakse kindlatel juhtudel; tundlikkusanalüüs arvestab ebamäärased mõlemat pidi ja nende arv avaldatakse. Negatiivne vahe veapiiri sees → 0 lipuga `clipped_to_zero`.
- Vaatluse lahutus (PR1H, XML `precipitations`): 0,1 mm – samuti kirja.
- Tagajärg: läved 0,2/1/5/10/20 mm jäävad (ADR-005 algne), kuid 0,2 mm tulemusega kaasneb alati ebamääraste juhtude osakaal.

**ADR-010 (muudetud) Käituskeskkond: GitHub (avalik repo)** (staatus: kinnitatud tellija poolt)
- Fakt: repo `TPiparKAUR/prognoos-vs-tegelikkus` on avalik. Tellija otsus 2026-11-13: kogu töö ja edasine arendus harul **`main`**, mis peab olema repo vaikeharu (Settings → General → Default branch); ajastatud töövood käivituvad ainult vaikeharult. Varasem vaikeharu `claude/modest-johnson-mo063h` on `main`-i eellane ega saa enam muudatusi.
- Arhiiv: GitHub Release'id `archive-YYYY-MM`, üks tar andmestik-päeva kohta, `archive-meta` jaamaregistrile. Release'id on avalikud → sisaldavad ainult avaandmeid (ECMWF CC BY 4.0, KAUR CC BY 4.0 / viitamise tingimusega XML) ja viidet allikatele. KAURi prognoosi **skoore** ei avaldata (ADR-012); toorarhiiv ei ole skoor.
- Teavitus: punane ajastatud töövoog → GitHubi e-kiri repo omanikule.

**ADR-015 (muudetud) ECMWF-ist salvestatakse ainult jaamade ümbrus** (staatus: kinnitatud tellija poolt)
- Eesti kast laaditakse alla ainult otsinguks; arhiveeritakse iga jaama 4 ümbritsevat ruudupunkti + lähim maapunkt 4×4 plokist (stencil), staatilised väljad samades punktides ning interpolatsioonikaalud koos kasutatud jaama metaandmetega (`*_weights.parquet`).
- Jaamaväärtused (bilineaarne, lähim, lähim maapunkt; kõrguskorrektsioon; tuule kiirus/suund) on deterministlik funktsioon arhiivist: `pvt.extract.points.load_points()`. Neid ei salvestata eraldi, sest punktifail oli mõõtmisel 2,5× suurem kui toorandmed.
- Jaamad: 25 kliimajaama (kinnitatud) + vaatluste XML-i lisajaamad (kinnitamata, skooridesse ei lähe).

**ADR-017 KAURi asukohaprognoos (ilmateenistus.ee „asukoha-prognoos") on peamine KAURi võrdlusprognoos** (staatus: KAURi teenus keeldub automaatsetest päringutest; sisu alus taastatakse ECMWF avaandmetest, ADR-021)
- Kontekst: tellija soovib eelkõige valideerida asukohapõhist prognoosi (tunnipõhine temperatuur, rõhk, tuul, sademed, nähtus). Leht kuvab Highchartsi meteogrammi, mille andmed laaditakse JavaScriptiga.
- Fakt (2026-11-13, asukohaprognoosi lehe HTML, muutuja `_var["meteogramDataUri"]`): leht laeb andmed JSONP-päringuga `https://ilmmicroservice.envir.ee/api/forecasts/modelForecastByLocation?locationId=<id>&lang=et&coordinates=<lat>;<lon>&showWarnings=1` (`meteogram_loader.js`: `$.getJSON(uri + '&callback=?')`). Tellija lubas teenust selle projekti jaoks pärida.
- Fakt (13.11.2026): `ilmmicroservice.envir.ee` sulgeb ühenduse vastuseta nii arenduskeskkonnast kui GitHubi runnerilt (töövoog `probe-location-fc`, ka täpselt lehe JSONP-kujul `&callback=`). Brauseri päiseid ega küpsiseid ei jäljendata.
- Vaja: KAURi IT lubab projekti kliendi (User-Agent `prognoos-vs-tegelikkus/…`, GitHub Actions) või annab ametliku ligipääsu; parseri jaoks vastuse näidis. Lehel on KAURi asukohaprognoos olemas „ootel" mudelina.
- Plaan: hetktõmmis igal jooksul jaamade koordinaatidel, toorvastus + Parquet ainult muutusel; skoorid ainult sisevaates kuni avaldamisotsuseni (ADR-012).

**ADR-018 Veebileht: Vite + TypeScript, OpenLayers (EPSG:3301), ECharts; Maa- ja Ruumiameti hallkaart** (staatus: teostatud; muudetud 2026-11-13 tellija soovil)
- Ülesehitus (tellija: „lihtsusta; alguses üldine võrdlus, siis analüüs jaama kohta"): 1) võitjatabel muutuja × etteanne + MAE ja nihe (ME) etteande järgi; 2) kaart ja jaamade loend „kumb mudel on täpsem"; 3) jaama analüüs (viga etteande järgi, mõõdetud vs prognoositud); 4) andmed ja metoodika. Kogu vaade on URL-is; tundmatud või andmeteta valikud lingis asendatakse vaikeväärtusega.
- Aluskaart: **Maa- ja Ruumiameti hallkaart** `https://kaart.maaamet.ee/wms/hallkaart`, kiht `kaart_ht` (GetCapabilities 13.11.2026: ainult EPSG:3301, tasuta, AccessConstraints none). Seetõttu on kaardivaade L-EST97-s ja teek OpenLayers (MapLibre vajab EPSG:3857). WMS-i pärib külastaja brauser – külastaja IP jõuab Maa- ja Ruumiametisse. Saidiga kaasas OSM-i kontuur (ODbL) on varuaba, kui WMS ei vasta.
- Värvid: IFS sinine, AIFS oranž, KAUR asukohaprognoos aqua (slot 3), persistents hall katkendjoon; kaardil „kumb parem" sinine↔oranž hallikas keskpunktis (värv = mudeli identiteet).

**ADR-012 (muudetud 2026-11-13) KAURi prognoosi skoorid avalikul lehel** (staatus: tellija otsus)
- Tellija otsustas, et KAURi asukohaprognoosi võrdlus (IFS vs AIFS vs KAUR) on avalikul lehel. Leht kannab märgistust „Eksperimentaalne, mitteametlik".

**ADR-019 XML-i vaatlusjaamad analüüsis** (staatus: tellija otsus 2026-11-13)
- Kontekst: tellija soovib kasutada ka jaamu, kus mõõdetakse vaid osa suurusi (nt ainult tuul või temperatuur). docs/08 välistas kinnitamata jaamad skooridest.
- Valik: vaatluste XML-i jaamad (koordinaadid KAURi XML-ist; > 1 km kliimajaamast) on analüüsis **ainult T1-ga** ja eraldi võrgustikuna („Kõik vaatlusjaamad"); kliimajaamade koondtulemus jääb eraldi. Kõrgus on teadmata → temperatuur ilma kõrguskorrektsioonita (`t2m_nocorr`), XML-i rõhku ei võrrelda.
- XML-i kirje seotakse kliimajaamaga ainult siis, kui WMO-kood või nimi ühtib (mitte ainult kauguse järgi: nt „Tooma soojaam 1–4" samades koordinaatides kui Tooma).

**ADR-020 Varuajasti** (staatus: tellija kinnitas 2026-11-13)
- Fakt: GitHub ei käivitanud selle repo `schedule`-sündmusi kordagi (vana ja uue vaikeharu peal). Töövoog `scheduler.yml` käivitab ingesti ise (`workflow_dispatch`): XML iga 10 min, ECMWF iga 2 h, kliima ja leht 2× ööpäevas; jookseb ~5,8 h ja käivitab end uuesti. Peatamine: töövoo keelamine. Tavalised cron'id jäävad alles.

**ADR-021 KAURi asukohaprognoosi alus = ECMWF IFS 9 km avaandmetest** (staatus: teostatud 2026-11-13)
- Fakt (asukohaprognoosi leht, 13.11.2026): „Asukohapõhine prognoos baseerub ECMWF … (ECMWF IFS) andmetel … ruudu küljepikkuseks on meie laiustel ~9 km … interpoleeritakse lähima ruudu mudelprognoosid … Mudeli väljund uueneb [talveajal] kell 5:30, 11:30, 17:30, 23:30."
- Fakt (ECMWF avaandmed, 13.11.2026): IFS 0,1° on olemas (`ifs/0p1/oper`, failid `-sfc`/`-pl`, ka Google'i ja AWS-i peeglis), sammud samad mis 0,25° puhul; `z` ja `lsm` sammul 0.
- Valik: mudel `ifs-0p1` (sama ingest, oma ala 57,2–60,3° N × 21,0–28,8° E, 0,1° samm; 2528 punkti). Lehel „IFS 9 km (KAURi asukohaprognoosi alus)"; KAURi lehe meetodile vastab interpolatsioon „Lähim ruudupunkt".
- Piirang (Tõlgendus): see on sama mudel ja meetod, mitte KAURi serveri väärtused. KAUR võib kasutada ECMWF-i liikmesriigi levitust (natiivne ruudustik, varasem kättesaadavus) ja lisatöötlust. Kokkulangevust tuleb kontrollida mõne KAURi lehelt käsitsi salvestatud näidisega.
- Maht (mõõdetud 2 sammu: 28,9 MB): ~1,2 GB 00/12 jooksu ja ~0,7 GB 06/18 jooksu kohta → ~3,8 GB allalaadimist ööpäevas; arhiivi jääb ainult jaamade ümbrus.

**ADR-022 Täiendavad tasuta prognoosiallikad (kandidaadid)** (staatus: ettepanek; kontrollitud GitHubi runnerilt 13.11.2026)
- FMI avaandmed (CC BY 4.0, WFS): `fmi::forecast::meps::surface::point::*` (MEPS/HARMONIE), `fmi::forecast::edited::weather::scandinavia::point::*` (FMI sünoptikute toimetatud prognoos), `ecmwf::forecast::surface::point::*`. Eesti katvus: kontrollimisel.
- MET Norway Locationforecast 2.0 (api.met.no): Tallinn-Harku punkt vastas tunniandmetega; tingimused nõuavad User-Agentis rakenduse nime ja kontakti (kasutame repo URL-i, mitte isikuandmeid); ainult viimane prognoos → tuleb ise arhiveerida.
- Open-Meteo: 7 mudelit (ICON-EU, MET Nordic, DMI HARMONIE, KNMI HARMONIE, ECMWF IFS 0,25, GFS, ARPEGE) ja Previous Runs API (ajalugu alates 2024) – kõik vastasid. **Tasuta API ainult mittekaubanduslikuks kasutuseks** (andmed CC BY 4.0) – KAURi kasutus vajab otsust/kinnitust.
- DWD ICON-EU GRIB (opendata.dwd.de, CC BY 4.0): kättesaadav, suur maht.
- SMHI pmp3g: 404 (lõpp-punkt või ala) – ei kasuta.
