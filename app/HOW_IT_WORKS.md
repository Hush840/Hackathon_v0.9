# How the dashboard works — A to Z

Written so you can answer any question a judge asks about your own tool. Read it once
properly; you'll present far more confidently knowing what every piece does.

`app.py` is 769 lines and does exactly seven things in order. Everything below follows
that order.

---

## The shape of it

```
data/*.parquet   ──►  load()   ──►  correct()  ──►  score()  ──►  filters  ──►  7 tabs
  (Dhanya's            reads         fixes what      applies      settlement    render
   pipeline            the file      is broken       your         type,
   output)             and flags     and derives     sliders      region,
                       rankable      what's missing               shortlist size
                       rows
```

One sentence version: **the dashboard reads a scored file, corrects known faults in it,
re-scores it transparently, and draws the result.**

---

## 1 · Finding the data

```python
DATA_DIR = Path(__file__).parent / "data"
MATRIX_GLOB = "jendela_phase2_esg_matrix_*.parquet"
```

`matrix_paths()` scans `data/` — including subfolders — for anything matching that
filename pattern. It keys them by country name pulled from the filename, and if the same
country appears twice, the **most recently modified file wins**.

That's why adding a country is a file drop and nothing else. It's also why putting an
unverified file under `data/` silently replaces a good one — a real trap we hit twice.

`available_countries()` turns those filenames into the dropdown. Nine files, nine options,
no hardcoded list.

**Why parquet, not CSV.** Parquet is columnar and compressed. Malaysia is 51,926 rows ×
36 columns; as CSV that's slow to read and roughly ten times the size. Parquet also
preserves data types, so numbers come back as numbers.

## 2 · Loading, and the `rankable` flag

```python
df["rankable"] = df[list(SCORE_COLS)].notna().all(axis=1)
```

This one line handles both pipeline versions without branching anywhere else.

In the 12 August export, thin-evidence tiles are shipped with their index columns **null**
— that's the masking working as designed. Older exports filtered those rows out entirely,
so every row had values. The flag asks a simpler question than "which export is this?":
*does this row have the three numbers I need to rank it?*

Downstream, `data` is the rankable rows and `masked` is everything else. Masked tiles are
drawn on the coverage map and never ranked.

The loader also drops `geometry` and `.geo`, which are large and unused, and converts
dictionary-encoded strings back to plain text so `groupby` behaves normally.

## 3 · `correct()` — the honest part

This is the function that matters most, and the one your Data integrity tab documents.
The pipeline output has known faults; rather than hide them or ignore them, the dashboard
fixes them and says so.

**Percentile ranks instead of raw values.**

```python
d[f"{col}_n"] = pct_rank(d[col].where(ok))
```

`off_grid_likelihood` is nominally 0–1 but reaches 4.95. `logistics_difficulty` has its
own scale. You can't add numbers on different scales. Converting each to a percentile
rank — "what fraction of tiles score below this one" — puts everything on 0–1 and makes
the weights mean what they say.

Ranks are computed among **rankable tiles only**, so a masked tile can't shift another
tile's position.

**Ease of access is the inverse of difficulty.**

```python
d["access_ease_n"] = 1.0 - d["logistics_difficulty_n"]
```

The pipeline treats `logistics_difficulty` as a divisor — harder to reach means lower
priority. The dashboard's score is additive, so the direction is flipped once, here, and
everything downstream reads naturally.

**Recovering the real residual.**

```python
d["residual_signed"] = d["download_kbps"] - d["cv_predicted_speed"]
d["shortfall"] = (-d["residual_signed"]).clip(lower=0).fillna(0.0)
```

The supplied `underperformance_residual` is floored at 1.0, which destroys the sign — you
can't tell an underperforming tile from an overperforming one. Both source columns are in
the file, so the signed value is recomputed. Only shortfall counts: performing *better*
than predicted isn't a problem to solve.

Tiles with no cross-validated prediction get zero, not NaN. Absence of an estimate is not
evidence of a shortfall.

**Trusting the model only where it's validated.**

```python
d["cv_trusted"] = d["has_cv"] & d["is_underserved_target"]
```

The model is trained on the underserved-target population. The export also predicts the
wider set, where it scores R² −1.17 — worse than guessing. So the shortfall term is
applied only where the model has been validated. Both choices give an identical top 50;
this one is defensible.

**Abatement.**

```python
if supplied.nunique() > 1:
    d["expected_abatement_tco2e"] = supplied
else:
    d["expected_abatement_tco2e"] = ABATEMENT_FULL_TCO2E * d["off_grid_likelihood"].clip(0, 1)
```

Older exports shipped one constant (22.23) for every tile, which makes the figure
meaningless. The current one varies per site, so it's used as supplied. The fallback
weights the maximum by off-grid likelihood — a site we're half sure about contributes half
its carbon.

The constant comes from GSMA: 13,000 litres of diesel a year × 2.63 kg CO₂ per litre ×
65% abatement = 22.2 tonnes.

## 4 · `score()` — the ranking

```python
raw = (w["offgrid"]    * d["off_grid_likelihood_n"]
     + w["solar"]      * d["solar_viability_n"]
     + w["logistics"]  * d["access_ease_n"]
     + w["population"] * d["population_n"]
     + w["residual"]   * d["residual_n"]) / total
return (100 * raw).round(1)
```

Five percentiles, five weights, add them up, divide by the sum of weights so the result
stays 0–100 whatever the sliders say.

**Additive, not multiplicative** — and that's the single most important design decision in
the file. The pipeline multiplies its factors, which means one unbounded term can swamp
everything else. In the shipped data, 76% of tiles score exactly zero and the top 1% hold
36% of all the score. Adding percentiles can't do that: every factor contributes at most
its own weight.

This function is re-run on every slider move. That's why the map is live — there's no
precomputed ranking anywhere.

## 5 · Filters

Three, applied in order to produce `view`, then the top *N* becomes `shortlist`:

- **Settlement type** — rural and peri-urban by default. Urban tiles are almost certainly
  grid-connected.
- **Region** — Malaysia only. Ranks *within* Sabah and Sarawak instead of against the
  peninsula, which otherwise wins on access.
- **Distance to school or clinic** — 5 km keeps everything; tighten it to make the social
  criterion bite.

## 6 · Drawing the map

pydeck, which is Python's binding to deck.gl — the same WebGL engine Uber uses. It renders
tens of thousands of points in the browser at sixty frames a second, which Streamlit's
built-in charts cannot.

Two layers stack: a `GeoJsonLayer` for the national outline, and a `ScatterplotLayer` for
the tiles. Colour comes from `ramp()`, which interpolates amber → green across the
percentile. Radius scales with priority squared, so high-priority tiles read as larger as
well as greener.

The camera isn't hardcoded. `view_for()` computes latitude, longitude and zoom from the
bounding box of the data, so a new country frames itself correctly.

The basemap is CARTO Positron — deliberately pale, so your data is the only saturated
thing on screen.

## 7 · Caching

```python
@st.cache_data(show_spinner=False)
```

Streamlit re-runs the entire script top to bottom on every interaction. Without caching,
moving a slider would re-read a 51,926-row parquet file and redo every percentile.

`@st.cache_data` memoises by arguments: `load("malaysia")` reads from disk once, then
returns the stored result. `correct()` likewise. Only `score()` and the filters re-run,
which is why sliders feel instant.

It's also the reason a stale cache once showed you 51,926 tiles after the files had
changed — the cache doesn't know the file moved. Clear cache after swapping data.

---

## Questions you might get, and honest answers

**"Why Streamlit rather than a proper web app?"**
> Because the analysis is Python and this puts a live interface on it without a separate
> front end. For a screening tool that a policy team runs occasionally, that's the right
> trade. A production version would separate the API from the interface.

**"Is the scoring done live or precomputed?"**
> Live. Every slider move re-ranks all 14,071 tiles. That's the point — the weights are
> a judgement call, so they're exposed rather than baked in.

**"How does it handle a new country?"**
> Drop the parquet file in `data/`. The dropdown, the camera and the boundary all derive
> themselves. Nine countries, no country-specific code.

**"What happens if the pipeline output changes?"**
> It has, four times. The loader detects what's present rather than assuming a schema,
> and `check_new_data.py` compares any new export against the current one before we adopt
> it. We've rejected one on that basis.

**"How big is it?"**
> 769 lines in one file, five dependencies, 25 MB of data. It runs on a laptop with no
> API keys, no cloud services and no network calls.

---

## What you should be able to say without notes

1. It reads a scored parquet file — it does not run the model.
2. It corrects four known faults in that file, and lists all four on screen.
3. It re-scores additively on percentile ranks, because the original was multiplicative
   and unbounded.
4. Every weight is a slider, so the ranking is auditable rather than asserted.
5. Nothing is precomputed. What you see is computed in the moment you see it.
