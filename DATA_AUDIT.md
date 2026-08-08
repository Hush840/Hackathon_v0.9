# Data audit — `jendela_phase2_esg_matrix_*.parquet`

Run against Member 1 and Member 2's delivered files, 8 Aug 2026.
Malaysia: 2,815 rows · Indonesia: 3,482 · Singapore: 145.

Six issues. Four are fixed in the dashboard's correction layer; two need a re-export.

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

### 5. Only one confidence tier is present — the governance story is unshowable

Every row reads `Sufficient Evidence - Ranked Screening Approved`. `inference_status` and `field_survey_triggered` are likewise single-valued. Minimum observed `tests` = 15, minimum `devices` = 5, so the evidence filter was applied **before** export and Tier 2 / Tier 3 rows were dropped.

This matters more than anything else on the list. The handoff note presents the three-tier masking and the "Sabah & Sarawak blind spots" as a headline governance finding — but those rows are not in the file, so the dashboard cannot render them. Right now the map silently shows nothing where the story is strongest, which is the exact failure mode the tiering was designed to prevent.

**Ask:** re-export without the tests/devices filter, keeping the tier label as a column.

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

## Message to send Member 2

> Great work getting this through — the spatial blocking and the caveats list are exactly right, and the three-country output is a gift for the scalability slide.
>
> I hit four things while wiring the dashboard, and there are two I can't fix downstream.
>
> **Can't fix in the app:**
>
> 1. **All 2,815 rows have the same `confidence_tier`.** Min tests = 15, min devices = 5, so the evidence filter ran before export and Tier 2/Tier 3 rows aren't in the file. That means the Sabah/Sarawak masking — our strongest governance point — can't be displayed. Could you re-export unfiltered with the tier label kept as a column?
> 2. **Signed residual, please.** `underperformance_residual` is floored at 1.0 for 53% of rows, so we've lost the direction. Raw `observed − predicted` would let us actually show underperformance.
>
> **Already handled in the dashboard, flagging so the numbers match your notebook:**
>
> 3. `priority_score` comes through at 189 → 1.17e10 rather than 0–100, and rank-correlates 0.90 with the residual alone — the ESG terms are barely moving it. I rebuilt it from percentile ranks with visible weights.
> 4. `indicative_abatement_tco2e_yr` is constant at 22.23 for every row, which makes `people_connected_per_tonne_co2` equal to population ÷ 22.23. I've probability-weighted abatement by off-grid likelihood so carbon actually varies. Happy to move that upstream if you'd rather own it.
>
> One thing worth a team decision: with population weighted in the score, our top 10 sites are all Klang Valley and the top 100 has zero rural tiles. Setting population weight to zero gives 43 rural / 36 peri-urban / 21 urban and doubles East Malaysia's share. I've defaulted the dashboard to that and left the weights as live sliders so we can show the sensitivity on stage.
