# Handoff contract — `sites_scored.csv`

The dashboard reads exactly one file: `data/sites_scored.csv`.
One row per **site cluster** (not per OpenCelliD cell).

Member 2 produces this. The dashboard does no computation beyond filtering, sorting and display — all scoring lives upstream.

| Column | Type | Required | Notes |
|---|---|---|---|
| `site_id` | str | ✅ | Unique. Any stable string |
| `lat` | float | ✅ | EPSG:4326 |
| `lon` | float | ✅ | EPSG:4326 |
| `state` | str | ✅ | Malaysian state name |
| `region` | str | ✅ | `Peninsular` / `Sabah` / `Sarawak` |
| `n_cells` | int | ✅ | OpenCelliD cells collapsed into this site |
| `operators` | int | | Distinct MNCs at the site |
| `radio_mix` | str | | e.g. `GSM,LTE` |
| `in_electrified` | bool | ✅ | Sampled from GridFinder `targets.tif` |
| `dist_to_grid_km` | float | ✅ | Nearest GridFinder line |
| `grid_line_source` | str | ✅ | `osm` (confirmed) or `predicted` |
| `dist_to_road_km` | float | ✅ | Nearest OSM primary/secondary road |
| `slope_deg` | float | | NASADEM |
| `terrain_distance_km` | float | ✅ | `dist_to_road_km × (1 + slope_factor)` |
| `pvout_kwh_kwp_day` | float | ✅ | Global Solar Atlas PVOUT |
| `displaced_fraction` | float | ✅ | 0.60–0.70 |
| `displaced_litres` | float | ✅ | Litres/year |
| `avoided_tco2e` | float | ✅ | `displaced_litres × 2.63 / 1000` |
| `delivered_cost_per_litre_usd` | float | ✅ | Calibrated so the median site hits US$21,000/yr |
| `annual_savings_usd` | float | ✅ | |
| `capex_usd` | float | ✅ | `42000 × (1 + logistics_multiplier)` |
| `payback_years` | float | ✅ | `capex_usd / annual_savings_usd` |
| `population_served` | int | ✅ | WorldPop within radius |
| `facilities_served` | int | | OSM schools + clinics within radius |
| `ookla_avg_d_kbps` | float | | Null where no tile |
| `ookla_tests` | int | | Null where no tile |
| `ookla_devices` | int | | Null where no tile |
| `predicted_d_kbps` | float | | Model output |
| `residual_kbps` | float | | `observed − predicted`. Negative = underperforming |
| `confidence_tier` | str | ✅ | `strong` / `thin` / `unknown` — see below |
| `rank_carbon_per_1k` | float | ✅ | `avoided_tco2e / (capex_usd/1000)` |
| `rank_payback` | float | ✅ | Same as `payback_years`; lower is better |
| `rank_people_per_tonne` | float | ✅ | `population_served / avoided_tco2e` |
| `rank_combined` | float | ✅ | Mean of percentile ranks, 0–100, higher better |
| `top_factors` | str | | `pvout:+0.31\|dist_road:+0.22\|pop:-0.10` — pipe-separated, used verbatim in the site inspector |

### Confidence tiers

- **`strong`** — nearest grid line is `osm`-confirmed **and** Ookla tile has ≥15 tests and ≥5 devices
- **`thin`** — predicted line only, or Ookla below threshold. Shown greyed, excluded from rankings
- **`unknown`** — no Ookla tile at all. Rendered as "we cannot say", never as zero

### Notes for Member 2

- Rows with `confidence_tier = unknown` should still be included — the dashboard renders them as a distinct layer and counts them for the evidence-coverage statistic. Dropping them hides the most important governance finding.
- If a column is genuinely unavailable, ship it as empty rather than omitting it — the app degrades gracefully but only if the header exists.
- Also ship `data/threshold_runs.csv` if you can: the same file re-scored at `dist_to_grid` thresholds of 3, 5 and 10 km, with an extra `threshold_km` column. That drives the sensitivity view. Optional — the app works without it.
