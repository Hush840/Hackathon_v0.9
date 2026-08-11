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
