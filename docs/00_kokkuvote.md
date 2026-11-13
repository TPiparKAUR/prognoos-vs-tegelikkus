<!-- Extracted from the project package (v0.1, 2026-11-13). Numbered references [n] point to docs/README.md#allikad -->

# 00_kokkuvote.md

**Pealkiri:** Prognoos vs tegelikkus – otsusematerjal juhtrühmale
**Versioon:** 0.1 (mustand) · **Kuupäev:** 2026-11-13 · **Soovitatud failinimi:** `docs/00_kokkuvote.md`

### Palve juhtrühmale (otsus ees)
1. **Kinnitada arhiveerimise kohene käivitamine** (prototüüp 2 nädala jooksul). Põhjus (Fakt): ECMWF avaandmeid hoitakse portaalis rullarhiivina ainult viimased 12 jooksu; kõik, mida me täna ei salvesta, tuleb hiljem taotleda ECMWF-i arhiivist või on kadunud.\[4\]
2. **Valida hostinguvariant** (vt valikud allpool). Soovitus: **Variant B – sisemine GitLab**.
3. **Nimetada avaldamise kinnitaja** (soovitavalt prognoositalituse juht + andmehalduse esindaja), kes otsustab, millal ja millises ulatuses skooriliht avalikuks tehakse.
4. **Lubada ECMWF-i arhiivi (MARS) ligipääsu taotlemine** ajaloo täitmiseks (backfill), et ML-katse ei peaks ootama 12+ kuud uut arhiivi.
5. **Kinnitada ulatus:** MVP = IFS + AIFS Single (0,25°), 4 muutujat, jaamad kinnitatud ID-dega, sisemine veebileht, tõlgendatav MOS katsena.

### Valikud ja kompromissid

| Variant | Kirjeldus | Plussid | Miinused | Soovitus |
|---|---|---|---|---|
| A – avalik GitHub (Actions + Pages) | Kõik avalikus repos | Null-infra, tasuta runnerid (avalikus repos 4 vCPU/16 GB RAM/14 GB SSD), lihtne jagada\[5\] | Sait on avalik algusest peale; ajastus lülitub 60 päeva tegevusetuse järel välja; saidi piir 1 GB; arhiivi ei saa repos kasvatada\[6\]\[7\] | Ainult hilisemaks avalikuks peegelduseks |
| B – sisemine GitLab (gitlab.sise.envir.ee CI + Pages + sisemine salvestus) | Kõik KAURi võrgus | Vastab „kõigepealt sisemine" nõudele; andmed KAURi kontrolli all; arhiiv võib kasvada | Vajab runnerit, välisvõrgu ligipääsu ECMWF-ile/pilvepeeglitele ja Pages'i lubamist instantsil (Teadmata) | **Soovitatud** |
| C – hübriid | Arhiiv ja arvutus sisemiselt, avalik koondsait GitHub Pages'is hiljem | Parim pikaajaline tasakaal | Kaks CI-d hooldada | Faas 3 |

### Mida juhtrühm saab (MVP, hinnanguliselt 3 kuud arendust + jooksev arhiiv)
- Arhiiv: IFS (4 jooksu ööpäevas) ja AIFS Single (4 jooksu) punktprognoosid jaamades, Parquet, versioonitud skeem.
- Veebileht: kaart (vead jaamade kaupa, mudel A − mudel B), skoorikõverad etteande kaupa, scorecard, Taylori diagramm, sademete performance diagram.
- ML-katse aruanne: kas MOS parandab MAE-d statistiliselt olulisel määral (Tõlgendus: 2 m temperatuuri puhul on see kirjanduse põhjal tõenäoline, sademete puhul vähem kindel).

### Peamised riskid (täpsemalt dok 07)
Ajaloo puudumine (lühike treeningrida), ECMWF mudelivahetused (ECMWF-i uudis 12.05.2026: „Cycle 50r1, has gone live today (12 May 2026) alongside an update to the Artificial Intelligence Forecasting System (AIFS v2)"), sademete ööpäevapiiri teadmatus KAURi päevasummas, KAURi prognoosi avaliku hindamise mainerisk.
