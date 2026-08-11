# Slide review — "Powering the Last Mile"

Reviewed against the actual pipeline (`main.py`, `models/model_pipeline.py`) and the
shipped parquet files. 34 edits applied in `Powering the Last Mile - REVIEWED.pptx`.

The deck looks good. The problem is that several claims describe a version of the
project that doesn't exist — mostly things that were planned, then changed. A judge
who opens the dashboard will see the difference.

---

## The three that would have hurt us on stage

**1. SHAP.** Slides 8 and 9 promised "SHAP-based feature contribution charts." There is
no SHAP anywhere in the codebase. The dashboard shows a factor-contribution table
(percentile × weight × contribution), which is arguably *more* transparent, but it isn't
SHAP. Judges at a GeoAI event know what SHAP is and one of them will ask to see it.
→ Rewritten to describe what the dashboard actually does.

**2. The sensitivity weights were invented.** Slide 8 showed Environmental 60% / Social
25% / Governance 15%. The dashboard's sliders are Off-grid likelihood 45%, Solar
viability 25%, Ease of access 20%, Service shortfall 10%, Population 0%. Nothing in the
code produces 60/25/15. If we put that slide up and then drag the real sliders, the
mismatch is visible in the same breath.
→ Replaced with the real defaults.

**3. The carbon number was wrong on three slides, and inconsistent between them.**

| Slide | Said | Should be |
|---|---|---|
| 4 | "saving up to 24.0 tCO2e/yr" | 22.2 |
| 6 | "60–70%", "24.0 tCO2e/yr" | 65%, 22.2 |
| 7 | "35t", "approximately 35 tonnes avoided" | 22t |
| 7 | "$21,000 OPEX per site" | US$17,000 (slide 3 already says 17k) |

The arithmetic is 13,000 L × 2.63 kg CO₂/L = **34.2 t emitted**, × 65% =
**22.2 t avoided**. Slide 7 was quoting the gross emissions figure as if it were the
saving — that's the kind of error a judge catches in ten seconds, and it costs more
credibility than the number is worth. The pipeline hardcodes 0.65, so 22.2 is the only
defensible figure.

The $21k vs $17k contradiction sits two slides apart in the same deck.

---

## Other corrections applied

- **Slide 4, tech stack** — said "XGBoost, QGIS engine." We use scikit-learn's
  `GradientBoostingRegressor`; QGIS isn't in the pipeline at all. Replaced with Earth
  Engine / GeoPandas / scikit-learn / Streamlit + pydeck.
- **Slide 6, model features** — said the GBDT uses "terrain ruggedness, radiance, and
  rainfall." The actual feature list in `main.py` is population, elevation, slope,
  distance to power, distance to road, antenna count. Radiance and rainfall are sampled
  but are *not* model inputs — they feed the off-grid likelihood index instead.
- **Slide 7, scoring formula** — said the score "multiplies" its factors. It did, and
  that was the bug: multiplying unbounded terms let one factor swamp the rest. It's now
  additive over percentile ranks. The deck was describing the version we fixed.
- **Slide 5** — same fix to the one-line description.
- **Slide 2 and 4** — dropped "satellite" / "satellite backhaul." We don't model it.
  Don't promise a capability that isn't in the output.
- **Slide 8, confidence masking** — the deck describes three tiers. The shipped data
  contains exactly one ("Sufficient Evidence", all 2,815 Malaysian rows). The thin-
  evidence and no-data rows are filtered out upstream in the ETL before the mask ever
  runs, so the three-tier system is real in code but invisible in the output. Reworded
  to say so honestly rather than claim a live capability.
- **Slide 1** — `[Member 1] [Member 2] [Member 3]` placeholders filled. **Check the
  spelling of everyone's name before submitting** — I used the names as they appear in
  our chat, not official spellings.
- **Slide 3** — "Company Name" / "Date" template text was never replaced.
- **Slide 9** — kicker said "WONG YAN WEN ESG DEPLOYMENT." A person's name where the
  team name belongs. Changed to the team name.
- **Slide 9** — "Future ASEAN Regional Scaling" described as a roadmap item. It's done.
  Eight countries are live in the dashboard right now. That's a strength being filed
  under future work.
- **Slide 6** — added the actual R² (Malaysia 0.59 out-of-block vs 0.76 in-sample). The
  slide had a box headed "True R² Metric" with no number in it.

---

## Two slides added

The deck had ten slides of method and zero showing a result. That's the most likely
place to lose points on Prototype Demo. Both new slides are built from the real Malaysia
parquet using the dashboard's own scoring, so the numbers on them will match what a
judge sees on screen.

**New slide 9 — "From 2,815 candidate tiles to 50 site surveys."** The priority map
with the shortlist ringed, four KPIs (2,815 assessed / 50 shortlisted / 832 tCO₂e
avoided per year / 14% in East Malaysia), and the HOMER Pro positioning line along the
bottom: *"HOMER Pro designs the microgrid for one site. Nobody triages a whole country."*
That answers the "why isn't this just HOMER Pro?" question on a slide instead of under
pressure in Q&A.

**New slide 10 — "The gaps are the finding."** The evidence-coverage map, where every
hole inside the national outline is somewhere we cannot assess, plus the three points
that make it a finding rather than an apology: 12% of our evidence is in East Malaysia,
no data never means no coverage, and we publish the blind spots rather than hide them.

Both maps are also saved as `fig_priority.png` and `fig_coverage.png` — use them as
demo fallback if the live dashboard fails on stage.

Deck is now 12 slides. For a 5-minute slot including Q&A that's roughly 17 seconds each,
so plan to skip past slides 4 and 5 quickly — they cover the same canvas twice.

---

## Small things also fixed

- Slide 11 timeline: Phase 3 was dated Aug 7 but that work ran through Aug 10.
- "40 seconds to train on a standard CPU" appeared twice on slide 11. The second copy
  (in the Governance panel) now says what governance actually means here — confidence
  flags, survey triggers, human sign-off.

## Still worth checking

- Slide 12 references look sound, but the Ookla citation says "Q1 2019 – Q1 2026" —
  confirm which quarter we actually pulled.
- Malaysia R² is 0.59 in the current extract, 0.604 in the older one. Quote **0.59**.
  Indonesia is 0.44 — don't mix them up.
- Slides 4 and 5 both present the solution canvas. Consider cutting one.
