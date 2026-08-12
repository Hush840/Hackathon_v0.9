# Export audit — rounds 2 and 3

> **Resolution (12 Aug).** Round 2 was rejected. A corrected export arrived the same day
> and is now live — see the final section. Everything below is kept as the record of what
> was found and why it mattered.

---

# Second export — audit findings

Checked `PARQUET FOLDER NEW` against the export currently in `data/`.

**Recommendation: do not swap before the deadline.** One thing got fixed, one thing broke
badly, and the broken thing is the one we put on a slide.

---

## What got fixed

**Confidence tiers are real now.** Thin-evidence rows survive the ETL instead of being
filtered out upstream. Malaysia ships 51,926 rows: 14,071 Sufficient Evidence, 37,855
Thin Evidence. That's a genuine improvement and it's what we asked for.

Two new columns arrived: `is_underserved_target` and `national_rank`.

---

## What broke

**The model collapsed.** Not a subsetting artifact — the same rows are predicted far
worse than before.

`is_underserved_target == True` selects exactly the old row set. Malaysia: 2,815 rows,
all 2,815 site_ids match, and the measured `download_kbps` values are byte-identical.
Only the predictions changed.

| Country | Old out-of-block R² | New, same rows |
|---|---|---|
| Malaysia | **0.590** | **−8.73** |
| Philippines | **0.545** | **−10.01** |
| Thailand | **0.302** | **−8.43** |

A negative R² means the model is worse than predicting the average. −8.7 means about ten
times worse. In-sample R² fell to −6.97, so it can't even fit its own training data.

**Why.** The model is now trained on the full expanded population, which is 73% thin-
evidence tiles with a median of **3 speed tests each** against 42 for the sufficient-
evidence tiles. Three tests is noise. The model spent its capacity learning noise and is
now badly biased on the tiles we actually rank.

Keeping thin rows in the *output* was right. Keeping them in *training* is what did the
damage. Those are separable.

---

## What did not change

| Issue | Status |
|---|---|
| `indicative_abatement_tco2e_yr` | Still a single constant, 22.235 for every row in every country |
| `off_grid_likelihood` | Still unbounded — max 4.95 (Malaysia), 14.80 (Philippines) |
| Priority score | Still multiplicative. Rescaled 0–100, but among *ranked* Malaysian sites the median is 0.04 and **49% score exactly zero** |
| `underperformance_residual` | 13% still sitting on the 1.0 floor (Malaysia) |

So the dashboard's correction layer stays either way.

**`national_rank` is not usable as shipped.** It ranks all 51,926 rows including thin
evidence, and with 86% of scores at zero the ordering below the top few hundred is
arbitrary tie-breaking.

---

## Also: three countries are missing

The new folder has cambodia, malaysia, philippines, singapore, thailand. The current
export has those plus **indonesia, myanmar, vietnam**. Either they weren't regenerated or
they weren't uploaded.

---

## The decision

**Ship on the current export.** R² 0.590 for Malaysia is defensible and it's already on
slide 6 and in the demo script. Shipping a model with R² −8.7 and hoping nobody opens the
Model tab is not a plan.

The cost is that slide 8's confidence-masking claim stays worded as "excluded upstream in
the current extract" rather than being demonstrated live. That's already how it reads.

**If Dhanya can turn the fix around in time**, the new export becomes strictly better than
the old one and we swap. The fix is one filter — train on sufficient-evidence rows only,
then predict across everything:

```python
train = df[df.confidence_tier.str.startswith("Sufficient")]
model.fit(train[features], train["download_kbps"])
df["predicted_download_kbps"] = model.predict(df[features])
```

Re-run `check_new_data.py` on whatever comes back. The bar is Malaysia out-of-block R²
back above roughly 0.5 on the `is_underserved_target == True` subset. If it clears that,
swapping is a ten-minute job — the column names are unchanged, so the dashboard reads the
new files without modification.

---

# Third export — accepted (12 Aug, Malaysia)

Cleared the bar. Out-of-block R² **0.598** against 0.590 in the original, on the same
2,815 cross-validated rows. Adopted for Malaysia; the other seven countries stay on the
8 August files, and the dashboard handles both formats without branching.

| | 8 Aug (was live) | Round 2 (rejected) | Round 3 (live now) |
|---|---|---|---|
| Malaysia R² | 0.590 | −8.73 | **0.598** |
| Abatement | one constant | one constant | **13,577 distinct values** |
| Confidence tiers | 1 | 2 | **2 — 14,071 ranked, 37,855 masked** |
| Residual on floor | 13.3% | 13.3% | **2.9%** |
| SHAP | none | none | **`top_shap_driver` + `top_shap_value`** |

Two corrections retired: abatement is now per-site upstream, and thin-evidence masking
is real rather than described. Two remain — the multiplicative priority score and the
unbounded `off_grid_likelihood` — both still handled by percentile ranking.

## What the new format required

- **`spatial_block`, `lat_block`, `lon_block` were dropped**, then restored in the
  evening file. The Model tab falls back to a cross-validated tile count when absent.
- **Thin-evidence rows carry null index columns.** `load()` derives a `rankable` flag;
  ranking uses rankable rows only, and percentiles are computed among them so masked
  tiles never shift another tile's position. Coverage maps draw both.
- **Singapore was reverted.** Its round-3 file scores R² −1.49 across the wider
  sufficient-evidence set against 0.990 on the 8 August file. It's a negative control,
  so there was nothing to gain and an ugly number to lose.

## The finding this surfaced

With 14,071 ranked tiles instead of 2,815, East Malaysia takes **0% of the top 50** at
default weights, despite holding 12.3% of ranked tiles and being JENDELA Phase 2's
priority region.

Setting the ease-of-access weight to zero moves that to **32%**, and total expected
abatement goes from 951 to 947 tCO₂e — a 0.4% change. The access term was buying
convenience, not carbon, at the direct cost of the target region.

Left at the pipeline's default and surfaced in the Data integrity tab rather than tuned
away. It's now the strongest beat in the live demo.

---

# Fourth export — accepted with a caveat (12 Aug evening, Malaysia)

Restored `spatial_block` / `lat_block` / `lon_block` (152 blocks) and extended
`cv_predicted_speed` from 2,815 tiles to all 14,071 ranked ones. Adopted.

On the validated population the model is unchanged — **R² 0.601** against 0.598, same
2,815 rows, identical measured speeds.

**But across all 14,071 ranked tiles, out-of-block R² is −1.17.** That is not a broken
model; it is the same model measured outside its design population. The wider
sufficient-evidence set includes urban tiles an order of magnitude faster than anything
in training, and the model does not generalise to them.

## How the dashboard handles it

Both numbers are on screen. The headline metric is 0.601 on the validated population;
a warning box directly beneath states the −1.17 and explains why.

The shortfall term is applied only where the model is validated (`cv_trusted` =
`has_cv & is_underserved_target`). The remaining tiles score zero on it rather than being
ranked on an extrapolation.

Checked before choosing: **both approaches produce an identical top 50** (50/50 overlap,
same 951 tCO₂e, same 44 rural / 6 peri-urban split). The choice is free, so we took the
one we can defend.

## Not adopted

Singapore stays on the 8 August file. Its evening export scores R² −1.49 across the
wider sufficient-evidence set against 0.990 on the current file. It is a negative
control, so there was nothing to gain and an ugly number to lose.

## Residual floor regressed

24.6%, up from 2.9% in the morning file — more rows now carry a residual, and more of
them clamp. Immaterial here because we recover the signed residual ourselves from
`download_kbps − cv_predicted_speed`, but worth flagging upstream.
