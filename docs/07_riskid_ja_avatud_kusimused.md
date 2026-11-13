<!-- Extracted from the project package (v0.1, 2026-11-13). Numbered references [n] point to docs/README.md#allikad -->

# 07_riskid_ja_avatud_kusimused.md

**Pealkiri:** Riskid, leevendused ja küsimused tellijale
**Versioon:** 0.1 · **Kuupäev:** 2026-11-13 · **Soovitatud failinimi:** `docs/07_riskid_ja_avatud_kusimused.md`

### 1. Riskiregister
| # | Risk | Tõenäosus | Mõju | Leevendus |
|---|---|---|---|---|
| R1 | ECMWF jooksud kaovad rullarhiivist enne allalaadimist | Keskmine | Kõrge | Iga 2 h idempotentne töö, kolm peeglit, teavitus, MARS-backfill |
| R2 | Lühike treeningrida → ML ülesobitub | Kõrge | Keskmine | Bias-korrektsiooni baseline, pooled mudel, backfill |
| R3 | Mudelivahetus (50r1/AIFS v2 12.05.2026; tulevased tsüklid) | Kindel | Keskmine | `model_cycle` veerg, tsüklipõhine raport, ML-i reset |
| R4 | AIFS-i pikkuskraadi konventsioon muutub | Toimunud | Kõrge | **Fakt:** AIFS v2 avaandmetes muutus pikkuskraad tahtmatult; ECMWF parandas, alates 13.05.2026 06 UTC algab pikkuskraad −180°-st. Koordinaadid loetakse GRIB-ist |
| R5 | Sademete päevapiir vale | Keskmine | Keskmine | ADR-004, KAURi kinnitus |
| R6 | KAURi prognoosi skoori avalikustamine → mainerisk | Keskmine | Kõrge | Sisemine vaade, avaldamise kinnitaja, kontekstitekst |
| R7 | Avaliku GitHubi ajastus lülitub välja | Kõrge (variant A) | Kõrge | Keepalive, väline jälgija, variant B |
| R8 | Segadus ametliku prognoosi/hoiatustega | Madal–keskmine | Kõrge | Märgistus, hoiatusi ei kuvata |
| R9 | Vaatluste XML struktuur muutub | Keskmine | Keskmine | Skeemivalideerimine, häire, toore XML-i säilitamine |
| R10 | Litsents/viitamine puudulik | Madal | Keskmine | Viited igal lehel ja failide metaandmetes |

### 2. Küsimused tellijale (vastata enne arendust)
1. Kas gitlab.sise.envir.ee-l on lubatud GitLab Pages ja kas seda saab piirata sisevõrguga?
2. Kas CI-runneril on välisvõrgu ligipääs data.ecmwf.int-ile ja/või AWS/GCP/Azure peeglitele? Kas on puhverserver?
3. Kus hoitakse arhiivi ja kes vastutab varunduse eest?
4. Mis on DPREC-i ajaline piir UTC-s?
5. Mis kellaajal (UTC) uueneb kliimaandmestik API-s ja kas valideeritud andmeid muudetakse hiljem (nt pärast I kvartali lõppkontrolli)?
6. Kas KAUR arhiveerib oma eesti-prognoosi XML-i või sisemist arvulist prognoosi? Kus ja kas seda saab kasutada?
7. Kuidas vastavad eesti-prognoosi „place" ja tuulepunktid vaatlusjaamadele? Mis on „öö" ja „päev" täpne ajavahemik?
8. Kas KAURil on ECMWF-i arhiivi (MARS) ligipääs ja kas IFS/AIFS ajalugu saab tasuta tellida?
9. Kas KAURi regionaalmudeli väljund võetakse võrdlusesse (faas 2)?
10. Kes kinnitab skoorilehe avalikustamise ja millistel kriteeriumidel?
11. Kas jaamaloendisse lisada ka hüdromeetria- ja rannikujaamad (XML-is olemas)?
12. Kas TI määruse ja andmekaitse hinnangu teeb KAURi jurist/andmekaitsespetsialist enne avalikku faasi?

### 3. Avaliku kommunikatsiooni põhimõtted
- „Eksperimentaalne, mitteametlik" igal lehel; ebakindlus alati nähtav (usaldusvahemik, n).
- Hoiatusi ei näidata ega segata prognoosiga.
- KAURi prognoosi skoor esmalt ainult sisevaates; avalikustamisel selgitusega, et tekstiprognoos ja mudeli punktprognoos ei ole sama toode.
- Uudsust ei väideta: Eesti jaamapõhist avalikku IFS/AIFS/KAUR võrdlust selles uuringus ei leitud, kuid see ei tõesta, et seda pole tehtud.
