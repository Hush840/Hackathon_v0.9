# Live demo — finals, 3 minutes

**Rebuilt 19 Sep against the final backend export.** Every number below was re-derived
from the live app, not carried over. The old figures (14,071 tiles, 951 tCO₂e, the
ease-of-access slider beat) are dead — the scoring is now four backend pillars and the
weights are no longer yours to drag.

Five moves. The centre of it is stronger than what you had in August.

---

## Before you start

- Malaysia loaded, **Overview** tab, Policy scope **Rural Last-Mile**, Geography
  **Malaysia — national**, strategy **Balanced — pipeline default**, shortlist 20
- Second browser tab open on the same URL
- Map PNGs open and minimised as fallback
- Browser at 80% zoom so the map and the KPI row fit without scrolling
- **Do not click Brunei.** 32 tiles, all thin evidence, and the app correctly dead-ends
  with "no evidence-qualified candidates". Honest, but not a thing to show live.

---

## Move 1 · Orient — 25 seconds

**[Overview tab, Malaysia, Rural Last-Mile, national]**

> Every dot is an Ookla analysis tile matched to a candidate site — about six hundred
> metres across, not a confirmed tower. Malaysia has fifty-one thousand of them.
>
> Only two thousand five hundred and eighty cleared the evidence bar for ranking. The
> rest are either too thinly measured to trust, or already performing above baseline and
> excluded. Green is higher priority, ringed is the shortlist.

*Pause. Two seconds.*

---

## Move 2 · The finding — 55 seconds

This is the heart of it. Slower than feels natural.

**[Stay on Overview. Point at the map — the shortlist rings are all peninsular.]**

> Now — JENDELA Phase 2 prioritises Sabah and Sarawak. Look where our shortlist actually
> is. **Zero of the top twenty are in East Malaysia.**
>
> And that's not the ranking's fault. It's an evidence problem. **Ninety-three percent of
> East Malaysian tiles are masked for thin evidence**, against seventy-one percent in the
> peninsula. East Malaysia is only four point eight percent of everything we're allowed
> to rank.
>
> Ookla is crowdsourced. The least-connected places generate the fewest speed tests. So
> the region that needs this most is the region we can see least.

**[Geography → East Malaysia (Sabah + Sarawak). Let it redraw. Say nothing.]**

> So we rank *within* the region instead of against it.

**[Point at the abatement KPI.]**

> Twenty sites in Sabah and Sarawak — and here's the part we didn't expect. Three hundred
> and seventy-four tonnes of CO₂ a year, against three hundred and eight for the national
> list. **Scoping to East Malaysia avoids twenty-one percent more carbon.**
>
> Because East Malaysian rural sites have a much higher inferred off-grid likelihood —
> 0.73 against 0.44. The national ranking wasn't just missing the policy region. It was
> leaving abatement on the table.

---

## Move 3 · No black box — 35 seconds

**[Rural prioritisation tab. Click into the candidate inspector.]**

> Every candidate explains itself. Four pillars — inferred diesel dependence, solar
> suitability, community impact, implementation feasibility — each scored out of a
> hundred, each with the evidence behind it.
>
> And the ranking you see is the backend's own priority score. The dashboard doesn't
> recompute it. If the pillar columns are missing, this app refuses to start rather than
> quietly inventing a ranking.

**[Point at the imputation flags / "Candidate only" notice.]**

> Where a distance was imputed, it says so. Every row is a field-survey trigger, not a
> verdict on a tower.

---

## Move 4 · Where the model is allowed to speak — 35 seconds

**[Model & evidence tab]**

> Spatial cross-validation R-squared is 0.63 for Malaysia, against 0.71 in-sample. We
> report the lower one.
>
> But look at the per-stratum table. Within rural, within peri-urban, within urban, the
> model explains almost nothing — it's separating the three groups, not the sites inside
> them. So we don't let it drive the ranking. The ML residual is one bounded input inside
> the community pillar, and nothing more.
>
> And it has a circuit breaker. For Laos, Myanmar and Singapore the spatial validation
> failed, so the model is switched off entirely for those countries and the deterministic
> ESG evidence carries the score. That's automatic, not a judgement call we made
> afterwards.

*This is the single most credible thing in the demo. Do not rush it.*

---

## Move 5 · It scales — 15 seconds

**[Country dropdown → Indonesia, or Thailand]**

> Same code, different file. Ten ASEAN countries, one pipeline, no country-specific logic.

**[Stop. Hands off.]**

---

## If you have spare time

**Methodology tab**, the DBSCAN sensitivity table:

> And the 50-metre clustering radius isn't borrowed from anywhere. We tested 25 to 500
> metres — beyond 50, DBSCAN chaining merges forty-three thousand towers into one cluster.
> It's an empirically chosen parameter and we show the test.

---

## If you're running short

Cut Move 5, then Move 3. **Never cut Move 2 or Move 4.**

---

## The numbers, for reference

| | |
|---|---|
| Malaysia tiles | 51,926 |
| Approved for ranking | 2,580 |
| Excluded — performing above baseline | 10,394 |
| Masked — thin evidence | 38,952 |
| Thin-evidence rate, East vs Peninsular | **92.8% vs 70.9%** |
| East share of approved pool | 4.8% |
| Rural national top 20 | 0% East · 308 tCO₂e |
| Rural East-only top 20 | 100% East · **374 tCO₂e (+21%)** |
| Mean off-grid likelihood, rural | East 0.73 · Peninsular 0.44 |
| Spatial-CV R², Malaysia | 0.630 out-of-block · 0.713 in-sample |
| Model bypassed for | Laos, Myanmar, Singapore, Brunei |

Scenario overlap with the pipeline default, rural national top 20: **Carbon-first 80%,
Community-first 75%.** Useful if a judge asks how sensitive the ranking is.

---

## Things that will lose you marks

- Saying "towers." They're analysis tiles matched to candidate-site proxies
- Saying "no coverage" for masked areas. Say "insufficient measurement"
- Quoting the August figures — 14,071 tiles and 951 tCO₂e no longer exist
- Claiming the model is good. It's 0.63 pooled and near zero within stratum, and saying
  so is what makes the rest believable
- Clicking Brunei
- Filling time by opening tabs you don't explain

---

## Rehearsal

Full run with a stopwatch, twice today and twice tomorrow. The two beats to make
automatic are the Geography switch in Move 2 — drag, silence, let the number land — and
the per-stratum honesty in Move 4.

---

## UPDATE — 20 Sep · what changed in the dashboard

Three things now do work the script used to do with words.

**The evidence layer is on the landing map.** Grey = masked for thin evidence, pale olive =
above baseline and excluded, green = eligible to rank, rings = shortlist. Borneo now reads
as visibly grey the moment the page loads. Open on Overview and let it sit for two seconds
before speaking — the map makes your argument before you do.

**The KPIs show deltas.** Change scope and the abatement figure carries a green +66 (+21%).
Point at the delta, not at the number. The judge watches the consequence happen rather than
being asked to remember 308.

**There is a field brief.** In the candidate inspector, "Download field brief" produces a
one-page printable document for the survey engineer — pillar scores, site context,
provenance warnings, and a blank survey record with sign-off lines. Open one on stage. It
is the difference between showing a ranking and showing a deliverable.

**Region labels** are on the map now, so judges who don't know Malaysian geography can
follow the Sabah and Sarawak argument.
