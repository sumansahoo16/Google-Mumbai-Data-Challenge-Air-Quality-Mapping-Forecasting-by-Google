# Four Breaths of Mumbai

A one-page, long-scroll, fully static air-quality field guide for the Google Mumbai Data Challenge creative submission. Open `index.html` directly in a browser. No server, network, JavaScript, API key, map tile, or live data call is needed.

## Creative premise

**A city average is an incomplete answer.** Four Breaths of Mumbai shows what four monitors agree on, where they differ at the same hour, and when missing observations limit the story. The signature view subtracts the median of the other three stations from each station's reading at the same hour. Its four hour-of-day curves make local differences visible while keeping the shared time context fixed.

This is designed as a field guide for people reviewing air-quality evidence: the headline seasonal shift supplies context; station coverage checks the quality of the comparison; the peer comparison suggests where further local monitoring may be valuable. It does not claim to locate a pollution source or estimate exposure between monitors.

**ClimateVerse data:** the challenge's CPCB/OpenAQ PM₂.₅ observations are paired with cached Open-Meteo historical weather listed in ClimateVerse's Google Air Quality Forecasting Challenge catalog. **Google tools:** Google Colab runs the included audit and reproducible build notebook; local Google Fonts shape the published design. The final page itself is entirely offline.

## What is here

| Path | Purpose |
|---|---|
| `index.html` | Finished standalone page, with inline CSS and SVG charts |
| `build.py` | Complete data preparation, analysis and HTML generation code |
| `data/station_pm25_hourly.csv.gz` | Cached, cleaned four-station challenge observations |
| `data/stations.csv` | Cached station coordinates and identifiers |
| `data/weather_hourly.csv.gz` | Cached Open-Meteo historical weather at the four station coordinates |
| `data/weather_raw/*.json` | Original API responses for audit |
| `data/*provenance.json` | Source URLs, dates, cleaning and licence notes |
| `data/analysis_metrics.json` | Numbers printed in the page |
| `assets/*.woff2` | Locally cached Google Fonts |
| `cache_fonts.py` | One-time Google Fonts cache script |
| `rebuild_in_colab.ipynb` | Google Colab data audit and rebuild workflow |
| `colab_bundle.zip` | Offline build inputs for the Colab notebook |

## Rebuild offline

From this folder, with Python 3.11+, pandas and NumPy installed:

```bash
python build.py
```

The command reads only this folder's cached files and rewrites `index.html`. It does not fetch data. To refresh the challenge snapshot from `air_quality/input`, use `python build.py --prepare-cache`. To refresh weather from the public API, use `python build.py --fetch-weather` with network access. The latter is an explicit action and is not needed to inspect or rebuild the delivered page.

For Google Colab, open `rebuild_in_colab.ipynb`, upload the included `colab_bundle.zip`, and run its cells. The notebook independently audits the matched-station comparison, rebuilds the page, and checks the resulting figures. It downloads a small `four_breaths_offline_page.zip` containing the HTML and font assets; extract it and open `index.html`. Google Fonts are served locally in the delivered page.

## Method

- The challenge source timestamp marks the **end** of each observed hour. The build shifts it back one hour before computing local day and hour.
- Negative readings, values above 1,000 µg/m³, and `flag_high_1000` rows are excluded. The resulting cache has 48,114 station-hours.
- Daily station values are medians of observed hourly PM₂.₅. A station-day needs at least 12 hours for daily trend lines and city summaries.
- The headline August–October comparison is the median of valid station-day medians in each month. It is descriptive, not a causal or population-weighted city estimate.
- The weather panel uses the median of four modelled grid-cell daily mean wind speeds and the median of valid station-day PM₂.₅ values, with at least three stations. Spearman correlation is a descriptive association across the seasonal transition.
- The peer comparison uses only the 653 hours between 1 October and 6 November 2026 when all four stations have a valid reading. For each station-hour it subtracts the median of the other three readings at that exact hour. The plotted curve then takes the median difference for each local clock hour. The night statistic is the median of all matched differences from 20:00 through 07:59, not the median of the plotted hourly medians.
- 2026 Diwali has no observed hours in the cached challenge train file for November 8. The page shows the coverage explicitly and does not fill that gap.

## Sources and licences

- [Google Mumbai Data Challenge](https://zindi.world/competitions/google-mumbai-data-challenge/data), CPCB CAAQMS through OpenAQ; challenge data are [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) per the Zindi rules. The local four-station cache is a derived snapshot of the user's downloaded challenge files.
- [ClimateVerse Open-Meteo catalog record](https://india.climateverse.net/dataset.xhtml?persistentId=doi:10.71646/XXOBKO), DOI `10.71646/XXOBKO`, which identifies the weather dataset and its limitations. Weather values were downloaded directly from the [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api); ClimateVerse lists the source licence as CC BY 4.0. These are modelled grid-cell values, not station observations.
- [DM Sans](https://fonts.google.com/specimen/DM+Sans) and [Space Grotesk](https://fonts.google.com/specimen/Space+Grotesk) from Google Fonts, bundled as WOFF2 under the SIL Open Font License 1.1.

This page is for exploratory understanding. Four stations cannot identify exposure for every neighborhood or attribute a pollution change to a single cause.
