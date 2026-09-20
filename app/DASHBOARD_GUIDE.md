# The dashboard, element by element

Every control, every number, where it comes from, and what to say if asked. Read this
once properly — in a fifteen-minute Showdown with judges' Q&A, "I'd have to check" about
your own screen is expensive.

Live: https://hackathonmcmc.streamlit.app/

---

# Sidebar — "Decision controls"

The sidebar is the argument. Everything in it exists because a judgement had to be made
and we chose to expose it rather than bury it.

### Country

Ten ASEAN countries. The list isn't hardcoded — it's built by scanning `data/` for files
matching `jendela_phase2_esg_matrix_*.parquet`. Adding a country is a file drop.

> **Brunei has 32 tiles, all thin evidence.** Selecting it correctly stops with "no
> evidence-qualified candidates remain." That's the governance layer working, but don't
> demo it.

### Policy scope — Rural Last-Mile / All evidence-qualified

Filters to `demographic_stratum == "rural"` or leaves everything approved.

**Why it exists:** the model is national, but the *decision* is rural last-mile. This
separates the two so you can narrow the policy question without retraining anything.

Rural Last-Mile is the default because urban tiles are almost certainly grid-connected —
no diesel to displace.

### Geography — Malaysia only

National / East Malaysia (Sabah + Sarawak) / Peninsular. A longitude split at 109°E.

> Be precise if asked: this is a **UI grouping for the current dataset**, not a
> state-level administrative boundary. It's labelled that way in the code.

This control produces your headline finding. See "The finding" below.

### Ranking strategy

Four options:

| Option | What it does |
|---|---|
| **Balanced — pipeline default** | Uses `priority_score` straight from the backend. No UI recomputation. |
| Carbon-first | Re-weights the four pillars 0.55 / 0.30 / 0.10 / 0.05 |
| Community-first | 0.25 / 0.20 / 0.50 / 0.05 |
| Custom sensitivity | Four sliders you set yourself |

**The critical point, and it's a design decision worth defending:** the dashboard does
*not* recompute the production ranking. Under the default it displays the backend's own
`priority_score`. The scenarios are explicitly labelled sensitivity tests, and whenever
you're not on the default, a banner appears showing the overlap with the default list.

If the pillar columns or `priority_score` are missing from a file, **the app refuses to
start** rather than quietly inventing a ranking. That's a deliberate `raise ValueError`.

### Shortlist size

5 to 100, default 20. Just the cut-off for how many candidates make the list.

---

# The four pillars

Everything ranks on these. Weights are the backend's, not yours.

| Pillar | Weight | Column | What it measures |
|---|---|---|---|
| **Diesel / off-grid dependence** | 40% | `off_grid_score_n` | 50/50 mapped power distance + VIIRS night-light darkness. Falls back to VIIRS alone where power mapping is missing. |
| **Solar suitability** | 25% | `solar_score_n` | Solar resource + tree canopy + slope + rainfall |
| **Community impact** | 30% | `community_impact_n` | Population + essential services + a bounded connectivity shortfall, diesel-gated |
| **Implementation feasibility** | 5% | `access_ease_n` | Road access + terrain, slope, elevation |

All four are normalised 0–1 and verified bounded by `check_new_data.py`.

**Why diesel is heaviest:** it's the precondition. A grid-connected site has no diesel to
displace, so nothing else matters. **Why feasibility is only 5%:** it's about cost, not
viability — it should nudge the order, not decide it.

---

# Tab 1 · Overview

### The four metrics

| Metric | Meaning |
|---|---|
| **Candidates in scope** | Approved tiles surviving your policy and geography filters |
| **Shortlisted** | Your shortlist size, or fewer if the pool is smaller |
| **Indicative abatement** | Sum of `indicative_abatement_tco2e_yr` across the shortlist |
| **Population associated** | Sum of WorldPop population in those tiles |

Both impact figures carry tooltips saying what they are not: a published-average
screening estimate rather than engineering design, and tile population rather than
deduplicated subscribers. **Say those caveats out loud; don't rely on the tooltip.**

Abatement per site scales continuously with inferred off-grid likelihood —
`34.2 × 0.65 × off_grid_likelihood`. A site we're 70% confident about contributes 70% of
the carbon. `check_new_data.py` verifies that formula matches to nine decimal places.

### The map

- Every dot is one **Ookla analysis tile** — roughly 600 m across — matched to its nearest
  OpenCellID-derived candidate-site proxy. **Not a confirmed tower.** Someone will test
  you on this.
- Colour runs amber → green by percentile of the displayed score, *within the current
  scope*. Re-scoping recolours the map; the legend says so.
- Dot size scales with score squared, so high priority reads as bigger and greener.
- Black rings mark the shortlist.
- Grey outline is the national boundary from `Asean.geojson`.
- Hover gives rank, score, settlement type and tile ID.

The camera isn't hardcoded — it fits itself to the bounding box of whatever is on screen.

### Top candidates table

The shortlist in brief: rank, tile, score, settlement, region, abatement, population.

---

# Tab 2 · Rural prioritisation

### Decision shortlist

The full table with all four pillar scores plus `priority_score` alongside the displayed
score, so a judge can see they're identical under the default.

**Ranks are re-numbered within the selected scope.** The first rural East Malaysian result
is "#1" in that scope, not its national rank. That's intentional — a decision-maker
working a rural programme wants a rural list, not a filtered national one.

CSV download is the actual handoff artefact: the file an engineer opens on Monday.

### Inspect a candidate

**Left — "Why it ranks here."** Four progress bars, one per pillar, each scored /100.
This is the no-black-box panel. Below it, the two strongest pillar signals in words.

**Speed-model explanation.** The strongest SHAP driver of the Random Forest speed
prediction, in kbps. Note the disclaimer in the app: *SHAP explains the speed model, not
the four-pillar priority score.* Those are different things and conflating them is the
easiest mistake to make on stage.

Where the model was bypassed, this panel says so instead.

**Right — the numbers.**

- **Displayed score** vs **Pipeline score** — identical unless you're running a scenario
- **Model disagreement** — standard deviation across Random Forest trees. A stability
  signal, explicitly *not* a calibrated confidence interval
- **Evidence** — "Sufficient", since only approved tiles are rankable
- **Indicative impact** — abatement, OPEX saving, population, people per tonne
- **Site context** — distance to power, road and amenity; measured vs expected speed;
  Ookla tests and devices

**The imputation flags.** If a distance was imputed rather than measured, an amber warning
appears naming which one. If none were, you get a green "no infrastructure-missing flags."
This is small and it is the kind of thing that wins a governance criterion — the tool
tells you which of its own inputs it wasn't sure about.

---

# Tab 3 · Model & evidence

The most defensible tab you have. Spend time here.

### The four metrics

- **Spatial-CV R²** — 0.630 for Malaysia. Read from the backend's stored `spatial_cv_r2`,
  and `check_new_data.py` verifies the stored value matches a recomputation exactly.
- **Validated tiles** — 2,815 for Malaysia: the underserved-target population the model
  was trained and validated on
- **Spatial blocks** — number of 0.5° blocks used for held-out validation
- **Training scope** — "Underserved"

Out-of-block 0.630 against in-sample 0.713. **Always quote the lower one.** Random splits
would have flattered the number; blocked validation is the honest version.

### The per-stratum table — your credibility moment

R² and median absolute error for rural, peri-urban and urban separately. The numbers are
near zero — around 0.002 to 0.003 for Malaysia.

**Say this plainly:** the pooled model separates the three settlement strata well but
explains very little *within* any one of them. Which is exactly why the ML residual is a
bounded input inside the community pillar and is not allowed to drive the ranking.

The app prints that warning itself. Reading it aloud is stronger than being caught by it.

### The scatter

Predicted vs measured speed, coloured by settlement. You'll see three distinct clouds —
that's the stratum separation described above, visible.

### The circuit breaker

`model_validation_status` comes from the backend. Where spatial validation failed, the ML
residual is switched off entirely and the deterministic ESG pillars carry the whole score.
The app shows the diagnostic R² it saw before bypassing.

Currently bypassed for **Laos (−0.008), Myanmar (−2.007), Singapore (insufficient spatial
blocks) and Brunei (insufficient data).** Validated for Malaysia, Indonesia, Thailand,
Philippines, Vietnam, Cambodia.

This is automatic, not a judgement made afterwards, and it's probably the single most
impressive thing in the build.

### Evidence coverage & governance

Three confidence tiers, and the counts for each:

| Tier | Malaysia | Meaning |
|---|---|---|
| Sufficient Evidence — Ranked Screening Approved | 2,580 | Eligible for ranking |
| Sufficient Evidence — Performing Above Baseline (Excluded) | 10,394 | Measured fine, so not a problem to solve |
| Thin Evidence — Masked from Prioritisation | 38,952 | Too few speed tests to trust |

Plus median Ookla tests per tile, and a bar chart of median tests by settlement type —
rural tiles carry the least evidence and the most inferential weight.

> **Blank or masked means insufficient measurement, never absence of coverage.** Say
> "no measurement", never "no coverage."

### Ranking sensitivity

Overlap between your current shortlist and the pipeline default, same scope. 100% on the
default. Carbon-first gives 80%, Community-first 75% — so the ranking is responsive to
weighting but not hostage to it.

---

# Tab 4 · Methodology

### Problem–decision contract

Two columns: what the tool may be used for, and what it may not. The second column is the
one that matters — it explicitly forbids asserting a specific tower is off-grid, claiming
no coverage from no measurement, treating a tile as a verified installation, or presenting
screening figures as a business case.

### How the ranking is built

The four pillars, their weights, and the evidence behind each.

### Geospatial engineering

- OpenCellID records clustered into candidate site proxies via **Haversine DBSCAN**
- **50 m epsilon**, chosen empirically — the sensitivity table shows 25 m to 500 m, and
  beyond 50 m chaining merges 43,393 records into a single cluster
- Ookla tile → nearest candidate site via **Haversine BallTree**
- Distances to road, power and amenity via zone- and hemisphere-aware projected joins

That DBSCAN table is a strong slide-free answer to "how rigorous are you?" — you tested
the parameter and you show the test.

### Known limitations

Six of them, including that the pooled R² is materially stronger than within-stratum.
Volunteering this is the point.

---

# The finding — the thing to lead with

At Rural Last-Mile, Malaysia national, default weights:

**Zero of the top 20 are in East Malaysia.**

Not a ranking failure — an evidence failure:

| | East Malaysia | Peninsular |
|---|---|---|
| Tiles | 9,756 | 42,170 |
| Thin evidence (masked) | **92.8%** | 70.9% |
| Approved for ranking | 125 | 2,455 |

East Malaysia is **4.8%** of everything we're allowed to rank, in the region JENDELA
Phase 2 explicitly prioritises. Ookla is crowdsourced, so the least-connected places
generate the fewest tests.

**Switch Geography to East Malaysia (Sabah + Sarawak):**

| | Abatement | Population |
|---|---|---|
| Rural national, top 20 | 308 tCO₂e/yr | 10,339 |
| Rural East-only, top 20 | **374 tCO₂e/yr** | 6,286 |

**Scoping to the policy region avoids 21% more carbon.** Because East Malaysian rural
sites carry far higher inferred off-grid likelihood — **0.73 against 0.44**.

So the national ranking wasn't only missing the priority region. It was leaving abatement
on the table. One dropdown, four seconds, and it's reproducible live.

---

# Quick answers

**"Is this real-time?"** No. Pre-computed matrices, refreshed when the backend re-runs.
Screening doesn't need real-time.

**"Could MCMC run this?"** Yes. Five Python dependencies, no API keys, no paid services,
39 MB of data, runs on a laptop.

**"What if a country has no Ookla coverage?"** Then it shows as thin evidence and is
masked. We report the gap rather than imputing a score.

**"Why Streamlit?"** The analysis is Python and this puts a live interface on it without a
separate front end. For a screening tool a policy team runs periodically, that's the right
trade.

**"Who maintains it?"** The pipeline is reproducible from open sources. The intended home
is MCMC or a towerco planning team; we'd hand over the repo and the runbook.
