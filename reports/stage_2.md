# Etapid E2–E4 (esimene versioon) – paarid, skoorid, veebileht

**Kuupäev:** 2026-11-13 · **Haru:** `main`

## Mis tehti
| Osa | Fail | Sisu |
|---|---|---|
| E2 paarid | `src/pvt/pair.py`, `pvt pair` | ECMWF jaamaväärtused (`load_points`, ainult kinnitatud jaamad) × T2 kliima-API tunniandmed ja T1 XML-i hetktõmmised; meetodid `nearest_land` (põhi, ADR-006), `bilinear`, `nearest`; persistents; 24 h sademed 00–00 ja 06–06 UTC koos pakkimisvea piiriga (ADR-005); T1 vahemiku-QC (ainult lipustab/nullib). |
| E3 skoorid | `src/pvt/verify/*`, `src/pvt/score.py`, `pvt score` | ME, MAE, RMSE, r; tuule suund ringveana (kiirus ≥ 2 m/s), vektor-RMSE; MAE/MSE oskus persistentsi suhtes; IFS − AIFS paarisvahe; plokk-bootstrap CI (valiidsuspäevade kaupa, ≥ 10 päeva); 2×2 tabel POD/FAR/CSI/ETS/PSS/HSS/sagedusnihe; „ebamäärased" sademejuhtumid eraldi. Ühine valim = IFS, AIFS ja persistents kõik olemas. |
| E4 sait | `src/pvt/site/build.py` (`pvt build-site`), `site/` | Kaart (jaamad värvitud valitud näitaja järgi, IFS/AIFS/vahe), jaama aegrida (vaatlus T2/T1, viimased jooksud, 24–30 h vana prognoos), skoor vs etteanne, scorecard, 24 h sademed, andmete seis. Iga graafiku kõrval tabelivaade, klaviatuur, hele/tume teema, Eesti aeg EET/EEST. |
| Käitus | `.github/workflows/site.yml`, `ci.yml` | Pages 2× ööpäevas (07:23, 19:23 UTC) + push'il; CI ehitab saidi igal push'il. |

## Esimesed tulemused (Fakt, arhiiv 09.–12.11, T2, lähim maapunkt, ühine valim)
Ainult 4 valiidsuspäeva → **usaldusvahemikke veel pole; järeldusi teha ei saa** (docs/01 §7: vähemalt 30 päeva).

| Muutuja, 1. päev | IFS MAE | AIFS MAE | Persistents MAE | n |
|---|---|---|---|---|
| 2 m temperatuur (kõrguskorr.) | 0,79 °C | 0,72 °C | 2,59 °C | 1104 |
| Merepinna rõhk | 0,27 hPa | 0,28 hPa | 8,36 hPa | 1104 |

- PA0 vs mudeli MSLP MAE 0,27 hPa → **PA0 on merepinnale taandatud rõhk** (kinnitab `settings.toml` eeldust).
- T1 paare veel pole: XML-i hetktõmmised tehti 32–41 min pärast täistundi (aken 10–30 min). Paarid tekivad, kui `ingest-kaur` ajastus töötab.

## Testid
`uv run pytest`: **92 passed**. Uued: docs/06 §1 tuntud väärtused (ME/MAE/RMSE, ringviga −20°, 2×2 tabel, oskusskoor 0,75), bootstrap (korduvus, liiga vähe päevi), persistentsi infoaeg, ühine valim, sademete aknad ja kolmene klassifikatsioon, QC. `ruff`, `mypy --strict`: puhtad. Sait: `tsc --strict` + Vite build; Playwrightiga renderdatud 1440 px hele/tume ja 390 px mobiil, konsoolivigu pole.

## Eeldused
1. PR1H tund h = summa (h−1, h] UTC. 2. XML-i hetktõmmis 10–30 min pärast täistundi esindab tundi h. 3. Persistents = vaatlus (valiidsusaeg − ⌈etteanne/24⌉·24 h). 4. Tuule suund ainult kui mõlemad kiirused ≥ 2 m/s (töö-otsus). 5. Saidi aken 45 päeva (`WINDOW_DAYS`).

## Avatud / vajab sinult
1. **GitHub Pages sisse lülitada:** Settings → Pages → Build and deployment → Source: **GitHub Actions**. Seejärel käivita töövoog `site` (või see käivitub ise). **Leht on avalik.**
2. **Asukohaprognoosi näidis** (ADR-017) – faili `tests/fixtures/location_forecast_sample.json` repos ei ole.
3. Klimatoloogia baseline ja SEEPS vajavad 1991–2020 jaamanorme (kliima-API päevaandmed) – järgmine samm.
4. DM-HLN test (docs/01 §7) – lisatakse, kui andmeid on ≥ 30 päeva; seni ainult bootstrap.
