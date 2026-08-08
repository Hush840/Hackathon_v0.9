# Data audit — `jendela_phase2_esg_matrix_*.parquet`

Run against Member 1 and Member 2's delivered files, 8 Aug 2026.
Malaysia: 2,815 rows · Indonesia: 3,482 · Singapore: 145.
Updated after reviewing `models/model_pipeline.py` in the team repo.

---

## Headline: the data is older than the code

`model_pipeline.py` min-max normalises `priority_score` to 0–100 and adds a
`national_rank` column. **Our parquet files have neither** — scores run to
1.17 × 10¹⁰ and `national_rank` is absent. The files we are building on were
produced by an earlier version of the script.

**Re-running the current pipeline is the single highest-value action available.**
It fixes the score range and adds `national_rank` for free.

Note also that the script writes to `data/jendela_phase2_esg_scored.parquet`,
but our files are named `..._matrix_<country>.parquet`. Worth confirming with
the team which artefact is authoritative.

---

## Why the score misbehaves — root cause found

```python
numerator = (abatement * off_grid_likelihood * solar_viability) \
            * (population_total + essential_service_weight) \
            * underperformance_residual
raw_score = numerator / logistics_difficulty
```

**The score is multiplicative across five unbounded terms.** That is the whole
problem. Min-max normalising afterwards makes the range 0–100 but not the
*distribution* — it stays so skewed that almost every site lands near zero and a
handful near 100. Re-running alone will not make the ranking usable.

**Fix:** combine percentile ranks additively with explicit weights, as the
dashboard now does. Multiplying raw magnitudes lets one factor swamp the rest.

### Which factor swamps it

```python
df['underperformance_residual'] = predicted - observed
df['underperformance_residual'] = ...apply(lambda x: max(x, 1.0))
```

A site that is not underperforming multiplies by **1**. One that is can multiply
by **75,000**. Meanwhile `off_grid_likelihood` only spans about 0.01 to 4.9. That
single clamp is why the residual rank-correlates 0.898 with the final score and the
ESG terms correlate below 0.13. The ESG project is being ranked almost entirely by
one telecoms variable.

### `off_grid_likelihood` is not a likelihood

```python
(distance_to_power_m / 5000)*0.5 + (distance_to_road_m / 2000)*0.3
+ (1.0 / (night_radiance + 0.1))*0.2
```

Unbounded on every term. A fully dark tile contributes `1/0.1 × 0.2 = 2.0` on its
own. Hence the observed maximum of 4.94. If it is going to be named a likelihood —
or multiplied by anything — it needs bounding.

### `essential_service_weight` is decorative

It adds **50** to `population_total`, whose median is 1,238. A roughly 4% nudge.
The Social pillar is currently not doing meaningful work in the score.

---

Six data issues follow. Four are fixed in the dashboard's correction layer.

---

## Fixed in the dashboard (no upstream work needed)

### 1. `priority_score` is not 0–100

Actual range **189 → 11,691,170,000** (1.17 × 10¹⁰). Mean 4.0 × 10⁸. The handoff note says "normalised cleanly to a 0–100 scale, top site = 100.00" — it isn't. The symptom is characteristic of multiplying several unbounded terms rather than combining bounded ones.

Worse, the score is **90% driven by one variable**. Rank correlations against `priority_score`:

| Component | Correlation |
|---|---|
| `underperformance_residual` | **+0.898** |
| `population_total` | +0.311 |
| `night_radiance_nw_cm2_sr` | +0.257 |
| `solar_viability` | +0.122 |
| `off_grid_likelihood` | +0.092 |
| `essential_service_weight` | +0.094 |
| `logistics_difficulty` | −0.086 |

The ESG components contribute almost nothing. It is a residual ranking wearing an ESG label.

**Correction:** rebuilt from percentile ranks with explicit, user-adjustable weights, bounded 0–100.

### 2. Abatement is a constant

`indicative_abatement_tco2e_yr` = **22.23 for all 2,815 rows**, standard deviation 0.00. The arithmetic is right (13,000 L × 0.65 × 2.63 kg ÷ 1000) but it's applied as a flat constant, so carbon cannot distinguish any site from any other.

Consequence: `people_connected_per_tonne_co2` is exactly `population_total / 22.23` — verified numerically. It is a population count in carbon units. If a judge divides two rows and notices, the E pillar collapses.

**Correction:** abatement is probability-weighted by off-grid likelihood, giving expected tCO₂e/yr from 0.04 to 22.22. A tile that probably has grid power no longer gets credited with a full diesel offset.

### 3. The residual is clipped, not signed

`underperformance_residual`: min 1.0, 25th 1.0, median 1.0 — **53% of rows sit exactly at 1.0** — then jumps to 75,149 at max. Signed underperformance (negative = worse than predicted) is gone, so "which sites underperform" cannot be read from it.

**Correction:** the floor is treated as "no signal" and the factor is weighted 0 by default.

### 4. Indices exceed their nominal range

`off_grid_likelihood` reaches **4.94** (135 rows above 1.0); `logistics_difficulty` reaches **3.23** (21 rows). Both are named and used as if bounded 0–1.

**Correction:** converted to percentile ranks.

---

## Needs a re-export from Member 2

### 5. Only one confidence tier is present — and it is not Member 2's fault

Every row reads `Sufficient Evidence - Ranked Screening Approved`.

Member 2's `apply_governance_confidence_mask()` is **correct** — it assigns all three
tiers and drops nothing:

```python
if row['tests'] >= 15 and row['devices'] >= 5:  'Sufficient Evidence...'
elif row['tests'] > 0:                          'Thin Evidence - Masked...'
else:                                           'No Data - Excluded'
```

But our data has minimum `tests` = 15 and minimum `devices` = 5, so **thin and
no-data rows never reach the model at all.** The filter lives upstream in the ETL.

**This ask goes to Member 1, not Member 2.** The extraction needs to keep tiles below
the activity threshold so the masking layer has something to mask. Without them, the
"Sabah and Sarawak blind spots" finding — the strongest governance point in the pitch —
cannot be displayed, because the rows do not exist.

### 6. The evidence filter biases against the target population

Ranking only tiles with sufficient Speedtest activity systematically excludes remote off-grid sites, because remote sites have few tests. Evidence:

- East Malaysia is **12% of rows** (338 of 2,815) despite being the JENDELA Phase 2 priority region
- Under the delivered score, the **top 10 tiles are all urban** — Klang Valley, Johor Bahru, Melaka
- Top 100 under the delivered score: 82 urban, 18 peri-urban, **0 rural**

An off-grid rural diesel project whose top-ranked site is central Kuala Lumpur does not survive its first question.

**Root cause:** `population_total` carries positive weight. Population is an impact measure, not a priority driver — weighting it pulls dense cities to the top by construction.

**Correction (dashboard):** population weight defaults to 0. With off-grid 0.50 / solar 0.30 / logistics 0.20, the top 100 becomes **43 rural, 36 peri-urban, 21 urban** and East Malaysia's share doubles to 24%. The weight sliders make this visible live — set population to 0.5 during the demo and watch the ranking jump to 83% urban. That is a strong, honest moment on stage.

---

## The R² figure belongs to Indonesia, not Malaysia

Recomputed from the shipped `download_kbps` and `cv_predicted_speed` columns:

| Country | Out-of-block R² | In-sample R² |
|---|---|---|
| Malaysia | **0.604** | 0.752 |
| Indonesia | **0.448** | — |
| Singapore | 0.976 (145 tiles — degenerate) | — |

The handoff note quotes 0.447, which matches **Indonesia**. If someone asks about the Malaysia model on stage, the answer is 0.604. Know which number goes with which country before the pitch.

## The signed residual was recoverable after all

`download_kbps − cv_predicted_speed` gives a proper signed residual: range −85,837 to +60,193, with **45.6% of Malaysian tiles underperforming** their prediction. The dashboard now computes this itself, so the "service shortfall" dimension is live without waiting for a re-export. Ask 2 in the message below is therefore a nice-to-have rather than a blocker — worth saying so when you send it.

## Also worth knowing

- **Rows are Ookla zoom-16 tiles, not towers.** `site_id` is a 16-character quadkey. Say "tiles" or "candidate sites" in the pitch — "towers" would be wrong and checkable.
- `national_rank` does not exist in the file, though the handoff note says to render it.
- `solar_radiation_mj` is 0.00 for 29 rows — failed samples, should be null.
- Off-grid inference uses VIIRS night-lights plus road and power distance, not GridFinder. Fine, but the caveat framing in the handoff note is right and must stay in the pitch.

---

## Resolved: remoteness lowers priority

**Team decision — the dashboard now follows `model_pipeline.py`.** Logistics
difficulty reduces priority: harder to reach means mobilisation and installation cost
more, so those sites are worse value per ringgit. The slider is labelled **Ease of
access** and the underlying percentile is inverted so the additive score preserves
Member 2's direction.

### What that decision cost and bought

Top 50 for Malaysia, at weights 0.45 / 0.25 / 0.20 / 0.10 / 0.00:

| | Rural | Peri-urban | Urban | East Malaysia | Median distance to road |
|---|---|---|---|---|---|
| Difficulty **raises** priority | 23 | 23 | 4 | 26% | 1,023 m |
| Difficulty **lowers** priority (chosen) | **38** | 10 | 2 | **10%** | **103 m** |

Only **5 of 50 sites appear on both lists** — this is not a tweak, it is a different
shortlist.

**Bought:** a markedly more rural shortlist (38 vs 23) and a clean ROI story — rural,
off-grid, sunny, and cheap to install.

**Cost:** East Malaysia's share drops from 26% to 10%, which weakens the JENDELA
Phase 2 alignment, since Phase 2 explicitly prioritises Sabah and Sarawak precisely
*because* they are hard to reach.

**Say this before a judge finds it:** "We rank easy-access sites higher because
installation cost dominates at this stage. That biases us away from the hardest parts
of Sabah and Sarawak, which is exactly where JENDELA Phase 2 is focused — so this is a
first-wave list, not a complete one. The hard sites need a different instrument, and
that's in our roadmap."

That answer is stronger than pretending the trade-off doesn't exist.

### One caveat on the factor itself

`logistics_difficulty` is clipped at 0.1 in the pipeline, and **50.9% of Malaysian
tiles sit exactly on that floor.** Ease of access therefore cannot separate half the
dataset — within that tied group the ranking is decided entirely by the other three
factors. The clip should be removed or the floor lowered on the next re-run.

## Two more things in the repo

- **`run_pipeline()` reads `parquet_files[0]`** — whichever file `glob` happens to
  return first — and always writes to the same output name. Running it for a second
  country silently overwrites the first. Fine for a hackathon, worth knowing before
  someone re-runs it on Tuesday.
- **The data files are gitignored.** The README says they are "excluded from version
  control due to file size" and live on Google Drive. But the three matrices total
  **5.2 MB** — trivially committable. See the deployment note below.

## Deployment blocker

Streamlit Community Cloud builds from the GitHub repo only. If the parquet files are
not committed, **the deployed app crashes on startup with a file-not-found**, no
matter how well it runs locally.

Repo currently contains `data_pipeline/`, `models/`, `notebook/`, `.gitignore`,
`README.md`. There is no `app/` and no root `requirements.txt`, so the dashboard
folder slots in without collision. Needed:

1. Commit `data/jendela_phase2_esg_matrix_*.parquet` (5.2 MB — add a negation rule to
   `.gitignore`)
2. Add `requirements.txt` at the repo root
3. Streamlit Cloud main file path: `app/app.py`

## Message to send Member 2

> Great work on this — the spatial blocking is properly done, the caveats list is exactly right, and having three countries makes the scalability slide write itself.
>
> I read through `model_pipeline.py` while wiring the dashboard. Main thing: **the parquet files we're working from are older than your code.** Your script normalises `priority_score` to 0–100 and adds `national_rank`; our files have scores up to 1.17e10 and no `national_rank`. So a re-run gets us both for free. Can you regenerate?
>
> Three things I'd change while you're in there:
>
> 1. **The score is multiplicative across five unbounded terms**, so min-max afterwards fixes the range but not the skew — almost everything lands near zero. Additive percentile ranks with explicit weights would behave much better. That's what the dashboard does now, so we can compare.
> 2. **`max(residual, 1.0)` is what makes the residual dominate.** Non-underperformers multiply by 1, underperformers by up to 75,000, while `off_grid_likelihood` only spans 0.01–4.9. Net effect: the residual rank-correlates 0.90 with the final score and every ESG term sits below 0.13. We're ranking an ESG project almost entirely on one telecoms variable.
> 3. **`off_grid_likelihood` is unbounded** — a fully dark tile gets `1/0.1 × 0.2 = 2.0` from the radiance term alone, hence the max of 4.94. Worth bounding if we're calling it a likelihood.
>
> Also: `indicative_abatement_tco2e_yr` is a flat 22.23 for every row, which makes `people_connected_per_tonne_co2` exactly population ÷ 22.23. I've probability-weighted it by off-grid likelihood in the dashboard so carbon actually varies between sites — happy for that to move upstream if you'd rather own it.
>
> One for the whole team: `logistics_difficulty` is a divisor in your score, so remote sites rank *lower*. I had it raising priority, on the logic that diesel delivery is what costs money. Both are defensible and they partly cancel — but we should agree which way it goes before someone asks.

## Message to send Member 1

> Two things on the extraction, both small:
>
> 1. **Can the ETL keep tiles below the activity threshold?** Everything in our matrices has `tests >= 15` and `devices >= 5`, so Dhanya's three-tier masking never sees a thin or no-data row — all 2,815 come back as "Sufficient Evidence". That means our Sabah/Sarawak blind-spot finding, which is probably the strongest governance point we have, can't be shown on the map. We need the thin rows present *and labelled*, not filtered out.
> 2. **Can we commit the three `.parquet` matrices to the repo?** The README has them gitignored for size, but they're only 5.2 MB total. Streamlit Community Cloud builds straight from GitHub, so without them the deployed dashboard crashes on startup — it can't reach Google Drive. The big files (`cell_towers.csv.gz`, the rasters) should absolutely stay out.
