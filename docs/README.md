# Projektikomplekt

# „Prognoos vs tegelikkus" – taustauuring ja projektikomplekt (dokumendid 00–08)

Parim lahendus on alustada kohe pidevat, idempotentset ECMWF IFS-i ja AIFS Single'i punktprognooside arhiveerimist KAURi jaamade koordinaatidel (ECMWF avaandmeid hoitakse ainult viimase 12 jooksu ehk umbes 2–3 päeva jagu, nii et iga vahele jäänud päev on avaandmetest jäädavalt kadunud), verifitseerida jaamapõhiselt iga etteande (lead time) kohta kahel tõetasemel (toorvaatlus ja KAURi kvaliteedikontrollitud kliimaandmestik) ning lubada ML-järeltöötlus (MOS) skoorilehele alles siis, kui see ületab ajalise valideerimisega ja olulisustestiga nii toorest mudelit kui ka lihtsat liikuva akna bias-korrektsiooni.\[1\]

**TL;DR**
- **Arhiiv on kriitiline tee ja tuleb käivitada kohe:** ECMWF avaandmete portaal on rullarhiiv (ECMWF Open data leht: „Data are retained for the most recent 12 forecast runs, corresponding to approximately 2–3 days of forecasts based on the four daily IFS and AIFS cycles (00, 06, 12 and 18 UTC)"; ECMWF AIFS-i juhend: „kuni neli päeva"), seega on vaja vähemalt kord 6 tunni jooksul käivituvat allalaadijat, mis võtab GRIB-indeksi abil välja ainult vajalikud väljad ja salvestab jaamapunktid Parquetisse; ajalugu (AIFS Single alates 2024-02, AIFS ENS alates 2025-07) on saadaval ainult ECMWF-i registreeritud arhiivist (MARS) ja selle kasutamise tingimused tuleb enne kontrollida.\[2\]\[3\]
- **Metoodika:** pidevatele muutujatele ME, MAE, RMSE, korrelatsioon, MSE dekompositsioon ja skill score referentsi (persistence, jaamapõhine klimatoloogia 1991–2020, toores IFS) suhtes; tuulele eraldi kiirus, ringstatistikaga suund ja vektorviga; sademetele 24 h kogused, kategoorilised skoorid ja SEEPS; ebakindlus plokk-bootstrapiga ning mudelite paarisvõrdlus Diebold–Mariano testiga koos Harvey–Leybourne–Newboldi korrektsiooniga; KAURi tekstiprognoosi (eesti-prognoos XML) hinnatakse ainult vahemiku- ja kategooriaskooridega, mitte RMSE-ga.
- **IT ja avaldamine:** soovitan esmaseks platvormiks KAURi sisemist GitLabi (gitlab.sise.envir.ee: ajastatud pipeline + Pages + sisemine salvestus), sest avalik GitHub Pages ei sobi „kõigepealt sisemine" nõudega (GitHubi dokumentatsiooni „GitHub Pages limits" järgi on Pages „available in public repositories with GitHub Free", „Published GitHub Pages sites may be no larger than 1 GB" ja kehtib „soft bandwidth limit of 100 GB per month"; dokumentatsiooni „Disabling and enabling a workflow" järgi „In a public repository, scheduled workflows are automatically disabled when no repository activity has occurred in 60 days"); veebileht on staatiline (MapLibre GL JS kaart + eelarvutatud skoorid, DuckDB-WASM uurimisvaade), märgistusega „eksperimentaalne, mitteametlik".

**Assumptsioonid (kehtivad kõigis dokumentides):** publik on juhtrühm ja spetsialistid; esmalt sisemine leht, avalik hiljem; MVP muutujad on 2 m temperatuur, 10 m tuul, 24 h sademed ja merepinna rõhk; mudelid on IFS ja AIFS Single (deterministlik) ning KAURi prognoos niivõrd, kuivõrd see on arvuline; baseline'id on persistence ja klimatoloogia; jaamade hulk piirdub nendega, mille ID ja koordinaadid on allikaga kinnitatud; ML-i esimene versioon on tõlgendatav MOS. Väidete märgistus: **Fakt** (allikast), **Tõlgendus**, **Soovitus**, **Hinnang** (arvuline hinnang koos mõõtmisviisiga), **Teadmata**.

## Allikad

1. [open data](https://www.ecmwf.int/en/forecasts/datasets/open-data)
2. [AIFS How To: Access AIFS model output data - User Documentation - ECMWF Confluence Wiki](https://confluence.ecmwf.int/display/UDOC/AIFS+How+To:+Access+AIFS+model+output+data)
3. [aifs machine learning data](https://ecmwf.int/en/forecasts/dataset/aifs-machine-learning-data)
4. [Open data](https://www-ecmwf-int.translate.goog/en/forecasts/datasets/open-data?_x_tr_sl=en&_x_tr_tl=id&_x_tr_hl=id&_x_tr_pto=tc)
5. [GitHub Actions runner specs: ubuntu-latest CPU, RAM and disk (2026)](https://sengi.run/blog/github-actions-runner-specs)
6. [github pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)
7. [Disabling and enabling a workflow - GitHub Docs](https://docs.github.com/actions/managing-workflow-runs/disabling-and-enabling-a-workflow)
8. [WeatherBench 2: A Benchmark for the Next Generation of Data‐Driven Global Weather Models - Rasp - 2024 - Journal of Advances in Modeling Earth Systems - Wiley Online Library](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2023MS004019)
9. [WeatherBench 2: A benchmark for the next generation of data-driven global weather models](https://arxiv.org/html/2308.15560v1)
10. [\[2308.15560\] WeatherBench 2: A benchmark for the next generation of data-driven global weather models](https://arxiv.org/abs/2308.15560)
11. [(PDF) Evaluation of ECMWF forecasts, including the 2021 upgrade](https://www.researchgate.net/publication/363485331_Evaluation_of_ECMWF_forecasts_including_the_2021_upgrade)
12. [Kliimaandmestiku kirjeldus](https://keskkonnaportaal.ee/et/avaandmed/kliimaandmestik/kliimaandmestiku-kirjeldus)
13. [Meteoroloogilise seire andmestiku kirjeldus | Keskkonnaportaal](https://keskkonnaportaal.ee/et/avaandmed/ilmavaatluste-andmestik/meteoroloogilise-seire-andmestiku-kirjeldus)
14. [A new equitable score suitable for verifying precipitation in numerical weather prediction - Rodwell - 2010 - Quarterly Journal of the Royal Meteorological Society - Wiley Online Library](https://rmets.onlinelibrary.wiley.com/doi/abs/10.1002/qj.656)
15. [ESSD - SEEPS4ALL: an open dataset for the verification of daily precipitation forecasts using station climate statistics](https://essd.copernicus.org/articles/18/713/2026/)
16. [ecmwf-opendata · PyPI](https://pypi.org/project/ecmwf-opendata/)
17. [ECMWF open data: real-time forecasts from IFS and AIFS - Data and Charts - ECMWF Confluence Wiki](https://confluence.ecmwf.int/spaces/DAC/pages/272310539/ECMWF+open+data+real-time+forecasts+from+IFS+and+AIFS)
18. [Crps fair · Issue #461 · xarray-contrib/xskillscore · GitHub](https://github.com/xarray-contrib/xskillscore/issues/461)
19. [statsmodels.tsa.stattools.diebold\_mariano\_test — statsmodels 0.15.1 (+1244)](https://www.statsmodels.org/devel/generated/statsmodels.tsa.stattools.diebold_mariano_test.html)
20. [Section 9.2.1 Causes of errors in forecast temperature and humidity - Forecast User Guide - ECMWF Confluence Wiki](https://confluence.ecmwf.int/display/FUG/Section+9.2.1+Causes+of+Errors+in+Forecast+Temperature+and+Humidity)
21. [Sõrve rannikujaam |Keskkonnaagentuur](https://www.ilmateenistus.ee/meist/vaatlusvork/sorve-rannikujaam/)
22. [Kliimaandmestik](https://keskkonnaportaal.ee/et/avaandmed/kliimaandmestik)
23. [Meteoroloogilise seire andmestik](https://keskkonnaportaal.ee/et/avaandmed/meteoroloogilise-seire-andmestik)
24. [Statistical Postprocessing for Weather Forecasts: Review, Challenges, and Avenues in a Big Data World in: Bulletin of the American Meteorological Society Volume 102 Issue 3 (2021)](https://journals.ametsoc.org/view/journals/bams/102/3/BAMS-D-19-0308.1.xml)
25. [Statistical Postprocessing for Weather Forecasts: Review, Challenges, and Avenues in a Big Data World](https://www.researchgate.net/publication/347580555_Statistical_Postprocessing_for_Weather_Forecasts_Review_Challenges_and_Avenues_in_a_Big_Data_World)
26. [EUPPBench: A forecast dataset to benchmark statistical postprocessing methods](https://www.ecmwf.int/en/newsletter/179/news/euppbench-forecast-dataset-benchmark-statistical-postprocessing-methods)
27. [Self-attentive Transformer for Fast and Accurate Postprocessing of Temperature and Wind Speed Forecasts](https://arxiv.org/pdf/2412.13957)
28. [ESSD - The EUPPBench postprocessing benchmark dataset v1.0](https://essd.copernicus.org/articles/15/2635/2023/)
29. [Eesti prognoos XML |Keskkonnaagentuur](https://www.ilmateenistus.ee/teenused/ilmainfo/eesti-prognoos-xml/)
30. [ECMWF open data: what's new at 0.1° - Data and Charts - ECMWF Confluence Wiki](https://confluence.ecmwf.int/spaces/DAC/pages/738041087/ECMWF+open+data+what+s+new+at+0.1%C2%B0)
31. [My GitHub Actions workflows are not starting](https://devopsjournal.io/blog/2022/08/12/workflows-not-starting)
32. [Ajaloolised ilmaandmed |Keskkonnaagentuur](https://www.ilmateenistus.ee/kliima/ajaloolised-ilmaandmed/)
33. [GitHub-Hosted Runners: Specs, Pricing and 7 Alternatives](https://craci.com/alternatives/github-hosted-runners)
34. [Eesti vaatlusandmed XML |](https://www.ilmateenistus.ee/teenused/ilmainfo/eesti-vaatlusandmed-xml/)
35. [AIFS How To: Access AIFS model output data - User Documentation - ECMWF Confluence Wiki](https://confluence.ecmwf.int/spaces/UDOC/pages/599165903/AIFS+How+To+Access+AIFS+model+output+data)
36. [Eesti ilmastiku ja kliima andmed (CLIDATA)](https://metadata.geoportaal.ee/geonetwork/srv/api/records/c399a632-ce4b-4460-99a2-a9a52a5329e3)
37. [Measured current conditions from Ilmateenistus stations · Issue #3 · urmasrehkalt/ilmajaam · GitHub](https://github.com/urmasrehkalt/ilmajaam/issues/3)
38. [Keskkonnaagentuur](https://www.ilmateenistus.ee/page/2/)
39. [Kasutusjuhend](https://keskkonnaportaal.ee/et/avaandmed/avaandmete-allalaadija/kasutusjuhend)

