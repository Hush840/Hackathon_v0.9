# JENDELA Phase 2 — ESG triage dashboard

Pre-feasibility screening of candidate off-grid mobile sites for solar-hybrid conversion.
AGAIF 2026 · theme: Environmental, Social & Governance.

> HOMER Pro designs the microgrid for one site, bottom-up. This is a top-down national
> scanner. Our output is the shortlist worth paying an engineer to model properly.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Opens on http://localhost:8501. No API keys, no Earth Engine auth, no network calls —
the app reads only the pre-computed parquet files in `data/`.

## Deploy

1. Push this folder to a public GitHub repo
2. share.streamlit.io → New app → point at `app.py`
3. Deploy

Streamlit Community Cloud caps at roughly 1 GB RAM. The app stays well inside that
because all sampling happens upstream — **never read a raster at runtime.**

## Layout

```
app.py                  dashboard (the only thing that runs)
requirements.txt
data/
  jendela_phase2_esg_matrix_malaysia.parquet     2,815 tiles
  jendela_phase2_esg_matrix_indonesia.parquet    3,482 tiles
  jendela_phase2_esg_matrix_singapore.parquet      145 tiles
  Asean.geojson
SCHEMA.md               target handoff contract
DATA_AUDIT.md           what actually arrived, and the corrections applied
make_sample_data.py     legacy dev fixture, no longer used
```

## Tabs

- **Priority map** — weighted ranking, live weight sliders, KPI row, site inspector showing why each site ranks where it does
- **Shortlist** — sortable table, CSV download for the engineering handoff, abatement and population breakdowns, weight-stability metric
- **Model** — out-of-block vs in-sample R², measured-against-predicted scatter, shortfall map, fairness table by settlement type
- **Evidence coverage** — the blind-spot map: national outline with every assessable tile, so gaps read as gaps
- **Data integrity** — corrections applied to the pipeline output, and the limits that remain
- **Ethics** — seven-dimension responsible AI self-audit, traffic-light scored
- **Method** — permitted and prohibited claims, provenance of every constant

## Know your numbers

Out-of-block R² differs by country: **Malaysia 0.604, Indonesia 0.448**. The handoff
note's "0.447" is the Indonesia figure. Don't quote the wrong one on stage.

## The correction layer

The dashboard does not present the upstream score unmodified. Four corrections are applied
and all are disclosed in the Data integrity tab. See `DATA_AUDIT.md` for the full findings.

Weights default to off-grid 0.50 / solar 0.30 / logistics 0.20 / population 0.00.
**Population defaults to zero deliberately** — weighting it pulls dense cities to the top,
which is the opposite of an off-grid diesel problem. Moving that slider live during the
pitch is the sensitivity analysis.

## Demo script (45 seconds)

1. Land on Malaysia, rural + peri-urban, top 50 — point at the East Malaysia share
2. Drag population weight to 0.5 — watch the shortlist jump to 83% urban. "This is why it's zero."
3. Click a site → the factor table shows why it ranks
4. **Evidence coverage** tab → "the gaps inside the outline are places we cannot assess, and they are exactly the places most likely to be off-grid"
5. Switch country to Indonesia → "same pipeline, nothing changed but the file"

If you have spare seconds, **Data integrity** — "we audit our own inputs" — is the
strongest closing line available.

## Data version

The dashboard reads the 8 August export. A second export (10 August) restored the missing
confidence tiers but collapsed the model — out-of-block R² fell from 0.590 to −8.73 on the
identical Malaysian rows, because thin-evidence tiles were included in training. Tested and
rejected; see `DATA_AUDIT_ROUND2.md` and the Data integrity tab. `check_new_data.py` re-runs
the comparison against anything dropped into `data/NEW/`.

Column names are unchanged between exports, so swapping is a file copy once the training
filter is fixed.

## Known limits

Every row is a **candidate requiring operator confirmation**. Off-grid status is inferred
from night-lights and road/power proximity, not utility records. Rows are Ookla zoom-16
tiles, not tower sites. No observation means no measurement, never no coverage.
