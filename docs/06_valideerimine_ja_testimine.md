<!-- Extracted from the project package (v0.1, 2026-11-13). Numbered references [n] point to docs/README.md#allikad -->

# 06_valideerimine_ja_testimine.md

**Pealkiri:** Testistrateegia ja vastuvõtukriteeriumid
**Versioon:** 0.1 · **Kuupäev:** 2026-11-13 · **Soovitatud failinimi:** `docs/06_valideerimine_ja_testimine.md`

### 1. Ühiktestid tuntud väärtustega
- f = [1, 2, 3], o = [1, 1, 1] → ME = 1, MAE = 1, RMSE = √(5/3) ≈ 1,29099.
- Ringviga: f = 350°, o = 10° → d = −20°.
- 2×2 tabel a = 10, b = 5, c = 5, d = 80: POD = 0,6667; FAR = 0,3333; CSI = 0,5; bias = 1,0; ETS = 7,75/17,75 ≈ 0,4366; PSS ≈ 0,6078; HSS ≈ 0,6078.
- Fair CRPS: ansambel [0, 2], vaatlus 1 → CRPS_fair = 0; tavaline ansambli CRPS = 0,5.
- Skill score: MSE_f = 1, MSE_ref = 4 → SS = 0,75.
- DM-HLN: võrdle statsmodels'i (kui olemas) või R-i `forecast::dm.test` väljundiga fikseeritud sünteetilistel andmetel.
- Ajad: test kukub läbi naiivse datetime'i korral.

### 2. Andmekvaliteedi kontrollid
- Skeem (veerud, tüübid, ühik veerunimes), `lead_h == (valid − issue)/1h`, duplikaatvõtmete puudumine.
- Füüsikalised vahemikud ja QC-lipud; sademe akumulatsioon mittekahanev.
- Jaama koordinaat Eesti piirides; lähima ruudupunkti kaugus < 20 km (0,25°).
- Idempotentsus: sama jooksu kaks korda allalaadimine annab baidiliselt sama Parqueti.

### 3. Reprodutseeritavus
- `uv.lock`, Dockerfile (Python 3.12, fikseeritud eccodes), `ingest_version` git-räsi igas reas, konfiguratsioon `config/*.toml`.
- Skooride regressioonitest fikseeritud sünteetilisel näidisnädalal.

### 4. Vastuvõtukriteeriumid (MVP)
1. 14 järjestikust päeva: ≥ 95% oodatud IFS- ja AIFS-jooksudest arhiveeritud; iga puudumine raportis põhjusega.
2. Iga saidi skoor on taasarvutatav ühe käsuga, kokkulangevus ≤ 1e-9.
3. Kaart töötab klaviatuuriga, kontrast vastab WCAG 2.1 AA-le (axe-kontroll + käsitsi).
4. ML-aruanne sisaldab baseline'e, laieneva akna tulemusi, DM-HLN p-väärtusi ja FDR-i; koodis pole juhuslikku jaotust (staatiline kontroll: `shuffle=True` keelatud).
5. Iga saidi arv näitab päritolu ja tõetaset.
