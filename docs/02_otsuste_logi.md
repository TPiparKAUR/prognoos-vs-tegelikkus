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
