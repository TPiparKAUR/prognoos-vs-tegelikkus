<!-- Extracted from the project package (v0.1, 2026-11-13). Numbered references [n] point to docs/README.md#allikad -->

# 01_metoodika.md

**Pealkiri:** Verifitseerimis- ja ML-metoodika
**Versioon:** 0.1 · **Kuupäev:** 2026-11-13 · **Soovitatud failinimi:** `docs/01_metoodika.md`

### 1. Põhimõtted
- **Soovitus:** verifitseerime punktis (jaam) mõõtmise vastu, mitte ruudustikus reanalüüsi vastu. **Fakt:** WeatherBench 2 (Rasp et al. 2024, JAMES, doi:10.1029/2023MS004019) on globaalne keskpika ulatusega (1–14 päeva) raamistik, mille tõeks on ERA5; IFS-i hinnatakse seal operatiivanalüüsi vastu, et vältida ebaõiglast viga ajasammul 0, ja sademete ERA5-tõde nimetavad autorid ise ajutiseks asenduseks („placeholder").\[8\]\[9\]\[10\] **Tõlgendus:** WB2 metoodika (skoorid etteande kaupa, scorecard'id, ühtne tõde kõigile mudelitele) kandub üle, kuid tõe valik mitte: regionaalse kasutaja jaoks on mõõtmine relevantsem ning reanalüüsi kaart on ainult lisavaade, päritoluga „reanalüüs".
- **Fakt:** ECMWF-i enda SYNOP-verifitseerimine kasutab lähima ruudupunkti meetodit ja 2 m temperatuurile standardset kõrguskorrektsiooni 0,0065 K/m mudeli orograafia ja jaama kõrguse vahe jaoks (ECMWF „Evaluation of ECMWF forecasts, including the 2021 upgrade").\[11\]
- Iga arv kannab päritolu silti: `toormõõtmine`, `kvaliteedikontrollitud`, `lünki_täidetud`, `homogeniseeritud`, `mudeli_analüüs`, `reanalüüs`, `prognoos`, `tuletatud_indeks`. Erinevaid päritolusid ei agregeerita kokku.

### 2. Ajatelg ja stratifikatsioon
- Võtmed: `issue_time_utc`, `valid_time_utc`, `lead_h = valid − issue` (tundides). Kõik ajad on UTC-teadlikud (ISO 8601); avalikus väljundis teisendatakse Eesti aega (EET/EEST) ja märgistatakse.
- Stratifitseeri: etteanne (IFS 00/12: 0–144 h iga 3 h, 150–360 h iga 6 h; IFS 06/18: ECMWF Confluence'i avaandmete leht annab `oper` jaoks 0–90 h iga 3 h, kuid ECMWF Open data leht ütleb „For times 06z & 18z: 0 to 144 by 3" – allikad on vastuolus, kontrolli tegelikku sammude loetelu indeksifailist; AIFS Single: iga 6 h kuni 360 h), väljastusaeg (00/06/12/18 UTC), ööpäevatsükkel, hooaeg (DJF/MAM/JJA/SON), jaam, režiim (rannik/sisemaa; hiljem ilmastikurežiim).
- **Soovitus (ausus):** mudelite võrdlus tehakse ainult **ühisel valimil** – samad (jaam, valid_time, lead_h) kolmikud, kus kõigil võrreldavatel mudelitel ja vaatlusel on väärtus. AIFS-i 6 h samm määrab ühise võrdluse sammu; IFS-i 3 h samme näidatakse eraldi vaates.

### 3. Deterministlikud pidevad muutujad (küsimus A)
| Mõõdik | Valem / märkus | Millal |
|---|---|---|
| ME (bias) | mean(f − o) | Süstemaatiline viga; kaardil divergentne skaala |
| MAE | mean(\|f − o\|) | Peamine kommunikeeritav mõõdik (robustne, samas ühikus) |
| RMSE | sqrt(mean((f − o)²)) | Tundlik suurtele vigadele; ECMWF/WB2 standard |
| Korrelatsioon r | Pearson; anomaaliakorrelatsioon klimatoloogia suhtes | Faasi/mustri kooskõla |
| MSE skill score | SS = 1 − MSE_f / MSE_ref | Referents: persistence, klimatoloogia, toores IFS |
| MAE skill score | 1 − MAE_f / MAE_ref | Robustsem alternatiiv |
| Murphy (1988) dekompositsioon | MSESS_klim = r² − (r − s_f/s_o)² − ((f̄ − ō)/s_o)² | Jagab skilli faasiks, amplituudi- ja bias-veaks |
| Jaotuse võrdlus | kvantiil-kvantiil graafik | Kas mudel taastoodab ekstreeme |

- **Kirjandus:** Murphy & Winkler (1987) üldine verifitseerimisraamistik (f ja o ühisjaotus); Murphy (1988) MSE skill score dekompositsioon; Wilks „Statistical Methods in the Atmospheric Sciences"; Jolliffe & Stephenson „Forecast Verification".
- **Robustsus (Soovitus):** näita lisaks mediaanset absoluutviga ja absoluutvea 90. protsentiili, kui jaotus on tugevalt asümmeetriline (tuul, sademed). Primaarne otsustusmõõdik jääb MAE-ks/RMSE-ks, sest need on kirjanduses võrreldavad.
- **Autokorrelatsioon:** järjestikused prognoosivead on korreleeritud. Efektiivne valimimaht AR(1) lähendusega n_eff ≈ n·(1 − ρ₁)/(1 + ρ₁) (Wilks). **Tõlgendus:** ρ₁ = 0,6 korral on 90 päeva n_eff ≈ 22 – seetõttu ei tohi ühe jaama ühe kuu skoori erinevusi tõlgendada. Geer (2016, Tellus A) näitas ECMWF-i kontekstis, et skooride erinevuste olulisustestid peavad autokorrelatsiooni arvestama.

### 4. Tuul (küsimus B)
- Kiirus: ME, MAE, RMSE nagu pideval muutujal.
- Suund: ringviga d = ((f − o + 180) mod 360) − 180; MAE_suund = mean(|d|). **Soovitus:** suunda hinnatakse ainult siis, kui vaadeldud ja prognoositud kiirus ≥ 2 m/s (lävi on töö-otsus, mitte allikast).
- Vektorviga: RMSE_vec = sqrt(mean((u_f − u_o)² + (v_f − v_o)²)); vaatluse u = −V·sin(θ), v = −V·cos(θ) (θ = päritolusuund).
- **Fakt:** KAURi BUFR-is on tuule suund 10 min valdav, kiirus 10 min keskmine ja eraldi maksimaalne puhang 10 m kõrgusel (Keskkonnaportaal, meteoroloogilise seire andmestiku kirjeldus).\[12\]\[13\] ECMWF 10u/10v on mudeli hetkväärtus valiidsusajal. **Tõlgendus:** see on ajalise esinduslikkuse erinevus; puhanguid verifitseeritakse eraldi muutujana ainult siis, kui avaandmetes on vastav puhangu-parameeter (Teadmata – kontrolli parameetritabelist).
- Rannikujaamad (nt Vilsandi, Ristna, Sõrve) ja mudeli maa/mere mask tekitavad süstemaatilist biasi; seda näidatakse jaamakaardil, mitte ei „parandata" varjatult.

### 5. Sademed (küsimus C)
- **Ööpäevasumma ja piir:** **Fakt:** KAURi kliimaandmestiku ööpäevasumma elemendikood on DPREC („Sademete ööpäeva summa, mm"), kuid ööpäeva piiri (06–06 UTC vs 00–24 UTC) ametlikust kirjeldusest ei leitud (**Teadmata**).\[12\] **Soovitus:** MVP-s arvutame 24 h summad ise tunnisummadest (PR1H kliimaandmestikus või `precipitations` vaatluste XML-is), mõlema piiriga (06–06 ja 00–00 UTC); DPREC-iga võrdleme pärast KAURi kinnitust. IFS-i `tp` on akumuleeritud jooksu algusest; AIFS-i akumulatsiooniperiood – kontrolli GRIB `stepRange`-ist.
- **Kategoorilised skoorid** (a = tabamus, b = valehäire, c = möödalask, d = õige eitus): POD = a/(a+c); FAR = b/(a+b); CSI = a/(a+b+c); ETS = (a − a_r)/(a + b + c − a_r), a_r = (a+b)(a+c)/n; Peirce/Hanssen–Kuipers PSS = a/(a+c) − b/(b+d); Heidke HSS; frequency bias = (a+b)/(a+c).
- **Läved (Soovitus):** 0,2; 1; 5; 10; 20 mm/24 h. 10 ja 20 mm valim jääb väikeseks – näita alati juhtumite arvu.
- **SEEPS** (Rodwell et al. 2010, QJRMS 136:1344–1363, doi:10.1002/qj.656): kolm kategooriat „kuiv", „nõrk", „tugev", mille piirid tulevad jaama klimatoloogilisest jaotusest; skoor on ekvitaabel ja valimimüra suhtes stabiilsem.\[14\] **Fakt:** SEEPS4ALL (ESSD 2026) avaldas jaamavaatlused 2022–2024 ja kliimastatistika 1991–2020 SEEPS-i arvutamiseks.\[15\] **Soovitus:** SEEPS-i kliimastatistika arvutame KAURi kliimaandmestikust 1991–2020 jaama ja kuu kaupa; SEEPS4ALL-i kasutame ristkontrolliks, kui Eesti jaamad on selles olemas (Teadmata).
- **Double penalty ja ruumilised meetodid:** punktverifitseerimisel karistatakse nihkunud sadu kaks korda. FSS (Roberts & Lean 2008) eeldab ruudustikus vaatlust (radar) – see on **faas 3**.
- **Vähese sajuga jaamad:** avalda bootstrap-usaldusvahemik ja jäta skoor näitamata, kui a + c < 10 (Soovitus).

### 6. Tõenäosuslik verifitseerimine (küsimus D) – faas 2
- **Fakt:** avaandmetes on IFS ENS (`enfo`, 50 häiritud liiget) ja AIFS ENS (`model=aifs-ens`, 6-tunnine samm kuni 360 h, ainult 0,25°).\[16\]\[17\]
- CRPS ansamblile: **fair CRPS** (Ferro 2014, QJRMS 140:1917–1923, doi:10.1002/qj.2270): CRPS_fair = (1/M)Σ|x_m − y| − 1/(2M(M−1)) ΣΣ|x_i − x_j|; eemaldab lõpliku ansambli suuruse kallutatuse.\[18\]
- Lisaks Brier score, reliability diagram, rank histogram, spread–skill suhe, ROC.
- **Soovitus:** ansambleid MVP-sse ei võeta (maht kasvab ~50×), kuid skeem on valmis (`member` veerg).

### 7. Statistiline olulisus (küsimus E)
- **Paarisvõrdlus:** sama valimi kaotusvahe d_t = L(e_A,t) − L(e_B,t), L = |e| või e².
- **Diebold–Mariano + Harvey–Leybourne–Newbold (1997):** statistikut skaleeritakse teguriga sqrt((T + 1 − 2h + h(h−1)/T)/T) ja võrreldakse t-jaotusega T − 1 vabadusastmega. **Fakt:** statsmodels'i arendusversiooni dokumentatsioon kirjeldab funktsiooni `diebold_mariano_test` parameetriga `harvey_adj` (kontrolli stabiilse versiooni olemasolu; muidu implementeeri ise ja testi tuntud väärtustega).\[19\]
- **Tõlgendus:** d_t on jaamade vahel korreleeritud; DM-test tehakse **ruumiliselt keskmistatud** päevasel kaotusvahel (iga valid-päev üks väärtus).
- **Plokk-bootstrap:** liikuva ploki bootstrap valid-päevade kaupa, ploki pikkus ≥ max(7 päeva, etteanne päevades + 1); 2000 kordust; 95% protsentiilvahemik skoorile ja skill score'ile.
- **Mitmene testimine:** Benjamini–Hochberg FDR (Wilks 2016, BAMS) üle etteannete × jaamade × muutujate.
- **Minimaalne valim (Soovitus):** koondtulemus alates 30 valid-päevast; hooajaline järeldus ainult siis, kui hooajas on ≥ 60 valid-päeva **ja** DM-HLN p < 0,05 pärast FDR-i; aastaringne järeldus pärast 12 kuud.

### 8. Visualiseeringud (küsimus F)
ECMWF-stiilis **scorecard** (värv = suhteline erinevus, sümbol = olulisus); **Taylori diagramm** (Taylor 2001); **performance diagram** (Roebber 2009); reliability diagram (faas 2); skoor vs etteanne koos usaldusribaga; ööpäevatsükli graafik.

### 9. Esinduslikkusviga (küsimus G)
- **Soovitus MVP:** lähim maapunkt + bilineaarne interpolatsioon paralleelselt diagnostikana; 2 m temperatuurile ΔT = −0,0065 K/m · (z_jaam − z_mudel), z_jaam EH2000, z_mudel mudeli orograafiast. Korrektsioon eraldi veergu, toorväärtust ei kirjutata üle.
- **Fakt (vastuolu, kaks ECMWF-i allikat):** ECMWF-i verifitseerimisaruanne kasutab 0,0065 K/m; ECMWF Forecast User Guide kirjeldab 2 m temperatuuri assimilatsioonis ja meteogrammides 5,5 °C/km.\[11\]\[20\] **Tõlgendus:** Eestis on kõrguste vahe väike, mõju suurusjärgus kümnendikud kraadi; valime verifitseerimise standardi 0,0065 K/m.
- Rannikujaamad: kui lähim ruudupunkt on meri (land-sea mask < 0,5), valitakse lähim maapunkt; mõlemad salvestatakse ja kaardil näidatakse lipuga.
- Kõrgused: jaama kõrgus EH2000 KAURi jaamalehtedelt (nt Sõrve rannikujaam 2,70 m EH2000).\[21\] BK77 kõrgusi ei segata teisendamata.

### 10. Tõe hierarhia (küsimus H)
| Tase | Allikas | Päritolu silt | Kasutus |
|---|---|---|---|
| T1 kiire | Vaatluste XML (hetkepilt), BUFR 10 min/1 h | `toormõõtmine` | Operatiivne „eelmise päeva" skoor |
| T2 lõplik | KAURi kliimaandmestik (valideeritud 10M/HLY/DLY/MLY, JSON, CC BY 4.0)\[22\] | `kvaliteedikontrollitud` | Ametlikum skoor, ML treening |

- **Fakt:** BUFR-failides on „toorandmed ehk automaatjaamade poolt mõõdetud valideerimata andmed"; kliimaandmestik on „valideeritud" aegread (Keskkonnaportaal).\[13\]\[22\]\[23\]
- **Soovitus:** iga skoor arvutatakse mõlemal tasemel; T1 vs T2 erinevus on ise kvaliteedinäitaja. Kui T2 väärtust hiljem muudetakse, arvutatakse skoor ümber (versioonitud).
- **Oma QC T1-le (Soovitus):** vahemik (T −45…+40 °C; tuul 0…60 m/s; rõhk 940…1060 hPa), hüpe (|ΔT| > 8 K/10 min), tasane joon (≥ 6 h sama väärtus), ruumiline kooskõla (robustne z > 5 naabrite mediaani suhtes). QC ainult lipustab.
- Mõõteviga: skoor sisaldab vaatlus- ja esinduslikkusviga; ECMWF on vaatlusebakindlust arvestanud DESS-skooris (Ben Bouallègue et al. 2020)\[11\] – MVP-s ei modelleerita, dokumenteeritakse piiranguna.

### 11. ML-järeltöötlus (küsimus I)
- **Ülevaade:** Vannitsem et al. (2021), BAMS 102(3):E681–E699, doi:10.1175/BAMS-D-19-0308.1 – käsitleb deterministliku ja ansambli järeltöötluse meetodeid ning eraldi probleemi, et sagedased mudelivahetused mõjutavad statistilise korrektsiooni kvaliteeti.\[24\]\[25\]
- **Benchmark:** EUPPBench (Demaeyer et al. 2023, ESSD 15:2635–2653, doi:10.5194/essd-15-2635-2023) – EUMETNET-i võrdlusandmestik: IFS-i ansambli prognoosid ja reforecast'id ning vaatlused Kesk-Euroopa osas, sh jaamaandmed (Zenodo doi:10.5281/zenodo.7708362).\[26\]\[27\]\[28\] **Tõlgendus:** Eesti jaamu see ei kata; väärtus on metoodikas ja koodis.
- **Meetodid (keerukuse järgi):**
  1. Liikuva akna bias-korrektsioon (jaam × etteande-ämber × väljastusaeg, aken 30 päeva) – **kohustuslik baseline**.
  2. Kalman-filtri bias-korrektsioon (adaptiivne, sobib lühikese reaga ja mudelivahetustega).
  3. Klassikaline MOS (Glahn & Lowry 1972): ridge-regressioon prediktoritega toores prognoos, ööpäeva- ja aastatsükli siinus/koosinus, kõrguste vahe, maa/mere osakaal.
  4. GAM (silujad aasta- ja ööpäevatsüklile).
  5. Piiratud LightGBM (sügavus ≤ 3, monotoonsuspiirang, SHAP) – ainult väljakutsujana pärast ≥ 12 kuud andmeid.
  6. Faas 2: EMOS/NGR (Gneiting et al. 2005), kvantiilregressioon, kvantiilregressioonimetsad (Taillardat et al. 2016), analoogansambel (Delle Monache et al. 2013), väikesed närvivõrgud (Rasp & Lerch 2018).
- **Tõlgendus:** lühikese rea ja vähese jaamade arvu korral on jaamade ülene (pooled) mudel jaamapõhiste vabaliikmetega stabiilsem kui mudel iga jaama kohta; prediktoreid alla ~10.
- **Riskid:** leakage, mittestatsionaarsus, mudelivahetus. **Fakt:** ECMWF-i uudise (12.05.2026) järgi „Cycle 50r1, has gone live today (12 May 2026) alongside an update to the Artificial Intelligence Forecasting System (AIFS v2)"; ECMWF-i AIFS-blogi „Adapting the AIFS for 50r1" järgi „We utilised five months of prototype data from early versions of IFS Cycle 50r1" ning suurem kokkupuude 50r1 andmetega parandab AIFS-i edasi ja seda kasutatakse AIFS v3 arenduses. **Soovitus:** igale prognoosireale `model_cycle`; ML treenitakse sama tsükli andmetel või tsükli indikaatoriga; tsüklivahetuse järel 30 päeva tagasi bias-korrektsioonile.

### 12. ML valideerimisprotokoll (küsimus J)
- **Juhuslikku jaotust ei kasutata.** Laienev aken kuu kaupa: treeni kuni kuu k−1, testi kuul k.
- **Gap/purging:** treeningu ja testi vahel vahe = maksimaalne etteanne (15 päeva) + vaatluse latentsus.
- **Hüperparameetrid:** ainult treeningosa sees (nested ajaline CV).
- **Baseline'id:** persistence (viimane vaatlus väljastusajal, sama kellaaeg), klimatoloogia 1991–2020 jaama ja aastapäeva kohta (silutud), toores IFS, toores AIFS, bias-korrektsioon, KAURi prognoos (kus arvuline).
- **Otsustusreegel:** ML „on parem" ainult siis, kui MAE skill score vs **parim** baseline > 0 ja DM-HLN p < 0,05 pärast FDR-i, ning paranemine ei tulene ühest kuust (leave-one-month-out tundlikkus).
- **Minimaalne treeningrida (Soovitus):** bias-korrektsioon 2–4 nädalat; lineaarne MOS ≥ 3 kuud; aastatsükliga MOS/GAM ≥ 12 kuud; gradient boosting ≥ 24 kuud või arhiivi backfill.

### 13. KAURi prognoosi hindamine (küsimus L)
- **Fakt (KAURi leht „Eesti prognoos XML"):** prognoos valmib keskpäevaks ja vajadusel muudetakse hommikul; nelja ööpäeva prognoos sisaldab iga öö ja päeva kohta nähtust, temperatuurivahemikku ja teksti; täpsem prognoos järgnevaks ööks ja päevaks sisaldab nähtust ja max/min temperatuuri kuue punkti kohta ning tuule suunda, kiirusevahemikku ja vajadusel puhanguid kolme punkti kohta; lisaks mere ja Peipsi tekstid.\[29\] Elemendid: `tempmin`, `tempmax` (°C), `direction` (°), `speedmin`, `speedmax`, `gust` (m/s), `phenomenon` (27 nähtusest koosnev loend).\[29\]
- **Soovitus:** hinnata ainult arvulisi elemente: (a) temperatuurivahemiku tabamus, vahemiku laius ja keskpunkti MAE (märgis „tuletatud"); (b) tuule kiirusevahemiku tabamus; (c) nähtus kategoorilisena (sademega/sademeta) POD/FAR. Punktide ja jaamade vastavus tuleb KAURiga kokku leppida (Teadmata).
- **Mida mitte väita:** KAURi tekstiprognoosile ei arvutata RMSE-d ega võrrelda seda IFS-iga sama skaala peal; öö/päeva definitsioon (kohalik aeg) tuleb kinnitada.
