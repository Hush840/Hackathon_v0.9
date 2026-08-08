"""JENDELA Phase 2 — ESG triage dashboard.

Pre-feasibility screening of candidate off-grid mobile sites for solar-hybrid
conversion. Reads the scored matrix produced by models/model_pipeline.py.

Run:  streamlit run app.py
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

DATA_DIR = Path(__file__).parent / "data"
COUNTRIES = {"Malaysia": "malaysia", "Indonesia": "indonesia", "Singapore": "singapore"}
GEOJSON_NAME = {"malaysia": "Malaysia", "indonesia": "Indonesia", "singapore": "Singapore"}

DIESEL_KG_CO2_PER_L = 2.63
BASELINE_LITRES = 13_000.0
SOLAR_HYBRID_REDUCTION = 0.65
ABATEMENT_FULL_TCO2E = BASELINE_LITRES * SOLAR_HYBRID_REDUCTION * DIESEL_KG_CO2_PER_L / 1000

VIEWS = {
    "malaysia": dict(lat=4.0, lon=109.5, zoom=5.2),
    "indonesia": dict(lat=-2.0, lon=118.0, zoom=4.2),
    "singapore": dict(lat=1.35, lon=103.82, zoom=10.5),
}
MAP_HEIGHT = 560
BASEMAP = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"

st.set_page_config(page_title="JENDELA Phase 2 — ESG triage", layout="wide")


# ─────────────────────────────────────────────  data

@st.cache_data(show_spinner=False)
def load(country_key: str) -> pd.DataFrame:
    df = pd.read_parquet(DATA_DIR / f"jendela_phase2_esg_matrix_{country_key}.parquet")
    return df.drop(columns=[c for c in ("geometry", ".geo", "__index_level_0__") if c in df],
                   errors="ignore")


@st.cache_data(show_spinner=False)
def boundary(country_key: str):
    path = DATA_DIR / "Asean.geojson"
    if not path.exists():
        return None
    gj = json.loads(path.read_text())
    want = GEOJSON_NAME[country_key]
    feats = [f for f in gj["features"] if f["properties"].get("Country") == want]
    return {"type": "FeatureCollection", "features": feats} if feats else None


def pct_rank(s: pd.Series) -> pd.Series:
    return s.rank(pct=True)


def r_squared(y, p) -> float:
    y, p = np.asarray(y, float), np.asarray(p, float)
    return float(1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum())


@st.cache_data(show_spinner=False)
def correct(df: pd.DataFrame) -> pd.DataFrame:
    """Corrections applied on top of the pipeline output. All disclosed in the
    Data integrity tab — nothing is silently changed."""
    d = df.copy()

    for col in ("off_grid_likelihood", "solar_viability", "logistics_difficulty"):
        d[f"{col}_n"] = pct_rank(d[col])
    d["population_n"] = pct_rank(d["population_total"])

    # Team decision: follow model_pipeline.py, where logistics_difficulty is a
    # divisor — harder to reach means lower priority, because installation and
    # mobilisation cost more. Inverted here so the additive score keeps that
    # direction.
    d["access_ease_n"] = 1.0 - d["logistics_difficulty_n"]

    # Signed residual recovered from the shipped columns. The supplied
    # underperformance_residual is floored at 1.0 for ~53% of rows.
    d["residual_signed"] = d["download_kbps"] - d["cv_predicted_speed"]
    d["underperforming"] = d["residual_signed"] < 0
    # Only shortfall counts as priority signal; overperformance is not a problem.
    d["shortfall"] = (-d["residual_signed"]).clip(lower=0)
    d["residual_n"] = pct_rank(d["shortfall"])

    # Abatement probability-weighted. Likelihood is capped at 1.0 rather than
    # divided by the country maximum, so values stay comparable across files.
    d["expected_abatement_tco2e"] = ABATEMENT_FULL_TCO2E * d["off_grid_likelihood"].clip(0, 1)
    d["people_per_tonne_v2"] = d["population_total"] / d["expected_abatement_tco2e"].replace(0, np.nan)

    d["region"] = np.where(d["longitude"] > 109, "East", "West")
    d["amenity_km"] = d["distance_to_amenity_m"] / 1000
    return d


def score(d: pd.DataFrame, w: dict) -> pd.Series:
    total = sum(w.values()) or 1.0
    raw = (
        w["offgrid"] * d["off_grid_likelihood_n"]
        + w["solar"] * d["solar_viability_n"]
        + w["logistics"] * d["access_ease_n"]
        + w["population"] * d["population_n"]
        + w["residual"] * d["residual_n"]
    ) / total
    return (100 * raw).round(1)


def ramp(v) -> list:
    v = np.clip(np.nan_to_num(np.asarray(v, float)), 0, 1)
    return [[int(245 - 215 * x), int(160 + 30 * x), int(40 + 90 * x), 200] for x in v]


def legend_html() -> str:
    stops = [ramp([x])[0] for x in (0.0, 0.25, 0.5, 0.75, 1.0)]
    swatches = "".join(
        f'<span style="display:inline-block;width:34px;height:12px;'
        f'background:rgb({c[0]},{c[1]},{c[2]})"></span>' for c in stops
    )
    return f"""
<div style="display:flex;flex-wrap:wrap;gap:26px;align-items:center;
            padding:10px 0 2px 0;font-size:13px;line-height:1.4">
  <div>
    <div style="display:flex;align-items:center;gap:8px">
      <span style="opacity:.7">lower</span>{swatches}<span style="opacity:.7">higher</span>
    </div>
    <div style="opacity:.7;margin-top:3px">priority — colour and size both encode it</div>
  </div>
  <div style="display:flex;align-items:center;gap:8px">
    <svg width="18" height="18"><circle cx="9" cy="9" r="7" fill="none"
      stroke="currentColor" stroke-width="1.8" opacity="0.85"/></svg>
    <span>ringed = on the shortlist</span>
  </div>
  <div style="display:flex;align-items:center;gap:8px">
    <svg width="18" height="18"><circle cx="9" cy="9" r="3.2" fill="currentColor"
      opacity="0.5"/></svg>
    <span>one dot = one ~610 m tile, not one tower</span>
  </div>
  <div style="opacity:.75">gaps inside the border = no measurement, not no coverage</div>
</div>
"""


def outline_layer(country_key):
    gj = boundary(country_key)
    if gj is None:
        return []
    return [pdk.Layer("GeoJsonLayer", data=gj, stroked=True, filled=False,
                      get_line_color=[90, 90, 90, 160], line_width_min_pixels=1)]


# ─────────────────────────────────────────────  sidebar

st.sidebar.title("Controls")
country_label = st.sidebar.selectbox("Country", list(COUNTRIES), index=0)
country = COUNTRIES[country_label]

raw = load(country)
data = correct(raw)

if country == "singapore":
    st.sidebar.warning(
        "Singapore is a negative control, not a deployment target. It is ~100% "
        "electrified, yet the off-grid proxy still fires — evidence the proxy needs "
        "recalibration for dense urban areas. Use Indonesia for the scalability story."
    )
else:
    st.sidebar.caption("Same pipeline, different file. Nothing else changes.")

st.sidebar.subheader("Priority weights")
st.sidebar.caption("Move these live during the pitch. This is the sensitivity analysis.")
w = dict(
    offgrid=st.sidebar.slider("Off-grid likelihood", 0.0, 1.0, 0.45, 0.05),
    solar=st.sidebar.slider("Solar viability", 0.0, 1.0, 0.25, 0.05),
    logistics=st.sidebar.slider("Ease of access", 0.0, 1.0, 0.20, 0.05),
    residual=st.sidebar.slider("Service shortfall", 0.0, 1.0, 0.10, 0.05),
    population=st.sidebar.slider("Population served", 0.0, 1.0, 0.00, 0.05),
)
st.sidebar.caption(
    "Ease of access raises priority — installation and mobilisation cost dominate at "
    "screening stage. Population defaults to 0: weighting it pulls dense cities to the "
    "top, which is the opposite of an off-grid diesel problem."
)

st.sidebar.subheader("Filters")
strata = st.sidebar.multiselect(
    "Settlement type", sorted(data["demographic_stratum"].unique()),
    default=[s for s in ("rural", "peri-urban") if s in set(data["demographic_stratum"])],
)
top_n = st.sidebar.slider("Shortlist size", 10, 300, 50, 10)

data["priority_v2"] = score(data, w)
view = (data[data["demographic_stratum"].isin(strata)] if strata else data).copy()
shortlist = view.nlargest(top_n, "priority_v2")

# ─────────────────────────────────────────────  header

st.title("JENDELA Phase 2 — solar conversion triage")
st.caption(
    f"{country_label} · {len(data):,} candidate tiles · pre-feasibility screening only · "
    "every site listed requires operator confirmation and a field survey"
)

tabs = st.tabs(["Priority map", "Shortlist", "Model", "Evidence coverage",
                "Data integrity", "Ethics", "Method"])
tab_map, tab_list, tab_model, tab_cov, tab_audit, tab_ethics, tab_method = tabs

# ─────────────────────────────────────────────  priority map

with tab_map:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Shortlisted tiles", f"{len(shortlist):,}")
    c2.metric("Expected abatement", f"{shortlist['expected_abatement_tco2e'].sum():,.0f} tCO₂e/yr")
    c3.metric("Population in range", f"{shortlist['population_total'].sum():,.0f}")
    east = (shortlist["region"] == "East").mean() * 100 if len(shortlist) else 0
    c4.metric("East Malaysia share", f"{east:.0f}%",
              help="JENDELA Phase 2 prioritises Sabah and Sarawak")

    plot = view.copy()
    plot["color"] = ramp(plot["priority_v2"] / 100)
    plot["radius"] = 1200 + 5200 * (plot["priority_v2"] / 100) ** 2

    v = VIEWS[country]
    layers = outline_layer(country) + [
        pdk.Layer("ScatterplotLayer",
                  data=plot[["longitude", "latitude", "color", "radius", "priority_v2"]],
                  get_position=["longitude", "latitude"], get_fill_color="color",
                  get_radius="radius", radius_min_pixels=3.5, radius_max_pixels=26,
                  pickable=True, opacity=0.75),
        pdk.Layer("ScatterplotLayer", data=shortlist[["longitude", "latitude"]],
                  get_position=["longitude", "latitude"], get_fill_color=[0, 0, 0, 0],
                  get_line_color=[20, 20, 20, 220], stroked=True, filled=False,
                  line_width_min_pixels=1.6, get_radius=3200, radius_max_pixels=26),
    ]
    st.pydeck_chart(
        pdk.Deck(layers=layers,
                 initial_view_state=pdk.ViewState(latitude=v["lat"], longitude=v["lon"], zoom=v["zoom"]),
                 map_style=BASEMAP, tooltip={"text": "priority {priority_v2}"},
                 height=MAP_HEIGHT),
        use_container_width=True,
    )
    st.markdown(legend_html(), unsafe_allow_html=True)

    st.subheader("Inspect a site")
    if len(shortlist):
        labels = {str(r.site_id): f"{r.site_id} · priority {r.priority_v2:.0f} · {r.demographic_stratum}"
                  for r in shortlist.itertuples()}
        pick = st.selectbox("Site", list(labels), format_func=labels.get)
        row = shortlist[shortlist["site_id"].astype(str) == pick].iloc[0]

        a, b = st.columns(2)
        with a:
            st.markdown("**Why it ranks here**")
            contrib = pd.DataFrame({
                "factor": ["Off-grid likelihood", "Solar viability", "Ease of access",
                           "Service shortfall", "Population"],
                "percentile": [row.off_grid_likelihood_n, row.solar_viability_n,
                               row.access_ease_n, row.residual_n, row.population_n],
                "weight": [w["offgrid"], w["solar"], w["logistics"], w["residual"], w["population"]],
            })
            contrib["contribution"] = (contrib.percentile * contrib.weight).round(3)
            st.dataframe(contrib.round(3), hide_index=True, use_container_width=True)
        with b:
            st.markdown("**Site detail**")
            st.write({
                "settlement": row.demographic_stratum,
                "region": row.region,
                "expected abatement tCO₂e/yr": round(row.expected_abatement_tco2e, 2),
                "population in range": round(row.population_total),
                "nearest school/clinic (km)": round(row.amenity_km, 2),
                "solar radiation MJ": round(row.solar_radiation_mj, 1),
                "slope °": round(row.slope_degrees, 1),
                "distance to road (m)": round(row.distance_to_road_m),
                "distance to power (m)": round(row.distance_to_power_m),
                "measured vs predicted (kbps)": f"{row.download_kbps:,.0f} vs {row.cv_predicted_speed:,.0f}",
                "Ookla tests / devices": f"{int(row.tests)} / {int(row.devices)}",
                "status": row.inference_status,
            })

# ─────────────────────────────────────────────  shortlist

with tab_list:
    cols = [c for c in ["site_id", "latitude", "longitude", "demographic_stratum", "region",
                        "priority_v2", "off_grid_likelihood", "solar_viability",
                        "logistics_difficulty", "expected_abatement_tco2e", "population_total",
                        "amenity_km", "residual_signed", "tests", "devices"]
            if c in shortlist.columns]
    st.dataframe(shortlist[cols].round(3), hide_index=True, use_container_width=True, height=460)
    st.download_button("Download shortlist (CSV)",
                       shortlist[cols].to_csv(index=False).encode(),
                       file_name=f"jendela_shortlist_{country}.csv", mime="text/csv")
    st.caption("Hand this to an engineer to model properly in HOMER Pro. "
               "It is a survey-ordering list, not an investment decision.")

    st.subheader("Where the shortlist sits")
    g1, g2 = st.columns(2)
    with g1:
        st.bar_chart(shortlist.groupby("demographic_stratum")["expected_abatement_tco2e"].sum(),
                     y_label="tCO₂e/yr", x_label="settlement type")
    with g2:
        st.bar_chart(shortlist.groupby("region")["population_total"].sum(),
                     y_label="population", x_label="region")

    st.subheader("Stability")
    ref = score(data, dict(offgrid=.45, solar=.25, logistics=.20, residual=.10, population=0.0))
    ref_top = set(data.assign(s=ref).nlargest(top_n, "s").site_id)
    overlap = len(ref_top & set(shortlist.site_id)) / max(len(ref_top), 1) * 100
    st.metric(f"Overlap with default weights (top {top_n})", f"{overlap:.0f}%",
              help="How much the shortlist changes as you move the weight sliders. "
                   "High overlap means the ranking is not an artefact of one weighting.")

# ─────────────────────────────────────────────  model

with tab_model:
    st.subheader("The model behind the shortfall signal")
    st.markdown(
        "Gradient boosting predicts Ookla download speed from terrain and population "
        "features only — no network-internal variables. Where a tile performs far below "
        "what its geography predicts, the shortfall is not explained by terrain, so it "
        "is a tractable target rather than an inevitability."
    )

    r2_block = r_squared(data.download_kbps, data.cv_predicted_speed)
    r2_in = r_squared(data.download_kbps, data.predicted_download_kbps)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Out-of-block R²", f"{r2_block:.3f}", help="Spatially blocked cross-validation")
    m2.metric("In-sample R²", f"{r2_in:.3f}")
    m3.metric("Spatial blocks", f"{data.spatial_block.nunique()}", help="0.5° blocks")
    m4.metric("Tiles underperforming", f"{data.underperforming.mean() * 100:.0f}%")

    st.caption(
        "The gap between in-sample and out-of-block R² is the honest cost of spatial "
        "autocorrelation. Random splits would report the higher number and mean less."
    )

    sc = data[["cv_predicted_speed", "download_kbps", "demographic_stratum"]].copy()
    sc.columns = ["predicted kbps", "measured kbps", "settlement"]
    st.scatter_chart(sc.sample(min(1500, len(sc)), random_state=0),
                     x="predicted kbps", y="measured kbps", color="settlement", height=380)
    st.caption("Points below the diagonal are underperforming relative to prediction.")

    st.subheader("Where the shortfall is")
    under = data[data.underperforming].copy()
    under["color"] = ramp(pct_rank(under["shortfall"]))
    v = VIEWS[country]
    st.pydeck_chart(
        pdk.Deck(layers=outline_layer(country) + [
            pdk.Layer("ScatterplotLayer", data=under[["longitude", "latitude", "color"]],
                      get_position=["longitude", "latitude"], get_fill_color="color",
                      get_radius=3000, radius_min_pixels=3, radius_max_pixels=16, opacity=0.75)],
            initial_view_state=pdk.ViewState(latitude=v["lat"], longitude=v["lon"], zoom=v["zoom"]),
            map_style=BASEMAP, height=MAP_HEIGHT),
        use_container_width=True,
    )
    st.markdown(
        legend_html().replace(
            "priority — colour and size both encode it",
            "size of shortfall — how far below prediction the tile performs",
        ).replace(
            '<div style="display:flex;align-items:center;gap:8px">\n    <svg width="18" height="18"><circle cx="9" cy="9" r="7" fill="none"\n      stroke="currentColor" stroke-width="1.8" opacity="0.85"/></svg>\n    <span>ringed = on the shortlist</span>\n  </div>', ""
        ),
        unsafe_allow_html=True,
    )
    st.caption(f"Only the {data.underperforming.sum():,} underperforming tiles are drawn. "
               "Tiles at or above prediction are omitted — they are not a problem to solve.")

    st.subheader("Fairness — does the model work equally well everywhere?")
    fair = data.assign(abs_err=data.residual_signed.abs()).groupby("demographic_stratum").agg(
        tiles=("site_id", "size"),
        median_abs_error_kbps=("abs_err", "median"),
        underperforming_pct=("underperforming", lambda s: round(s.mean() * 100, 1)),
    ).reset_index()
    st.dataframe(fair.round(1), hide_index=True, use_container_width=True)
    st.caption("Reported by settlement type rather than as a single global score. "
               "A model that is accurate on average can still be unusable rurally.")

# ─────────────────────────────────────────────  evidence coverage

with tab_cov:
    st.subheader("Where we have no evidence at all")
    st.markdown(
        "Every tile in this dataset cleared a minimum-activity filter. Remote areas "
        "generate few speed tests, so the places most likely to be off-grid are the "
        "places we know least about. Blank space below is **absence of measurement, "
        "never absence of coverage.**"
    )

    e1, e2, e3 = st.columns(3)
    e1.metric("Tiles with evidence", f"{len(data):,}")
    e2.metric("East Malaysia share", f"{(data.region == 'East').mean() * 100:.0f}%",
              help="The JENDELA Phase 2 priority region")
    e3.metric("Median tests per tile", f"{data.tests.median():.0f}")

    v = VIEWS[country]
    st.pydeck_chart(
        pdk.Deck(layers=outline_layer(country) + [
            pdk.Layer("ScatterplotLayer", data=data[["longitude", "latitude"]],
                      get_position=["longitude", "latitude"], get_fill_color=[30, 130, 120, 120],
                      get_radius=3000, radius_min_pixels=2.5, radius_max_pixels=10)],
            initial_view_state=pdk.ViewState(latitude=v["lat"], longitude=v["lon"], zoom=v["zoom"]),
            map_style=BASEMAP, height=MAP_HEIGHT),
        use_container_width=True,
    )
    st.markdown(
        """
<div style="display:flex;flex-wrap:wrap;gap:26px;align-items:center;
            padding:10px 0 2px 0;font-size:13px">
  <div style="display:flex;align-items:center;gap:8px">
    <svg width="18" height="18"><circle cx="9" cy="9" r="4" fill="rgb(30,130,120)"
      opacity="0.75"/></svg>
    <span>a tile with enough evidence to assess</span>
  </div>
  <div style="display:flex;align-items:center;gap:8px">
    <svg width="26" height="18"><rect x="1" y="4" width="24" height="11" fill="none"
      stroke="currentColor" stroke-width="1.2" opacity="0.55"/></svg>
    <span>national boundary</span>
  </div>
  <div style="opacity:.75">every gap inside the boundary is a place we cannot assess</div>
</div>
""",
        unsafe_allow_html=True,
    )

    st.bar_chart(data.groupby("demographic_stratum")["tests"].median(),
                 y_label="median Ookla tests", x_label="settlement type")
    st.caption(
        "Rural tiles carry the least evidence and the most inferential weight. That "
        "asymmetry is the governance finding, and it belongs in the open."
    )

# ─────────────────────────────────────────────  data integrity

with tab_audit:
    st.subheader("What we changed in the pipeline output, and why")
    st.markdown(
        """
| # | Issue in the scored matrix | Correction |
|---|---|---|
| 1 | `priority_score` spans 189 → 1.17 × 10¹⁰, not 0–100, and rank-correlates 0.90 with the residual alone — the ESG terms barely move it | Rebuilt from percentile ranks with visible, adjustable weights, bounded 0–100 |
| 2 | `indicative_abatement_tco2e_yr` is the **same constant (22.23) for every tile**, so `people_connected_per_tonne_co2` is just population ÷ 22.23 | Abatement probability-weighted by off-grid likelihood, capped at 1.0 so values stay comparable between countries |
| 3 | `underperformance_residual` is floored at 1.0 for 53% of rows, losing direction | Signed residual recovered as `download_kbps − cv_predicted_speed` |
| 4 | `off_grid_likelihood` reaches 4.94 and `logistics_difficulty` 3.23 despite nominal 0–1 ranges | Converted to percentile ranks |
        """
    )

    st.subheader("Limits we cannot fix downstream")
    st.markdown(
        f"""
- **Only one confidence tier is present.** All {len(data):,} rows read
  *"Sufficient Evidence – Ranked Screening Approved"*. Minimum observed:
  {int(data.tests.min())} tests, {int(data.devices.min())} devices — the evidence
  filter ran before export, so Tier 2 and Tier 3 rows are absent. The three-tier
  masking cannot be displayed until the matrix is re-exported unfiltered.
- **The evidence filter biases against the target population** — see Evidence coverage.
- **Rows are Ookla zoom-16 tiles, not tower sites.** `site_id` is a 16-character quadkey.
- **Off-grid status is inferred** from night-lights and road/power proximity, not utility
  records. Every row is a candidate requiring operator confirmation.
- **Ease of access biases the shortlist away from the hardest terrain.** Following the
  pipeline's convention, remote sites rank lower because installation costs more. That
  drops East Malaysia's share of the top 50 from 26% to 10% — so this is a first-wave
  list, not a complete one. The hardest Sabah and Sarawak sites need a different
  instrument, and that is in the roadmap.
- `logistics_difficulty` is clipped at 0.1 and **50.9% of tiles sit on that floor**, so
  ease of access cannot separate half the dataset.
- `essential_service_weight` is 50.0 for over 75% of rows and `antenna_count` reaches
  43,394 on a single tile — both look like join artefacts and are excluded from scoring.
        """
    )

    k1, k2, k3 = st.columns(3)
    k1.metric("Distinct confidence tiers", data["confidence_tier"].nunique())
    k2.metric("Distinct abatement values (as shipped)", raw["indicative_abatement_tco2e_yr"].nunique())
    k3.metric("Supplied residual at floor", f"{(raw['underperformance_residual'] <= 1).mean() * 100:.0f}%")

    st.info(
        "Showing this tab is deliberate. A screening tool that cannot audit its own "
        "inputs should not be trusted to allocate public money."
    )

# ─────────────────────────────────────────────  ethics

with tab_ethics:
    st.subheader("Responsible AI self-audit")
    st.caption("Seven dimensions, traffic-light scored against our own system.")
    ethics = pd.DataFrame([
        ("Fairness", "🟡 Partial",
         "Error reported by settlement type, not just globally. Rural tiles carry more "
         "inference and thinner evidence — disclosed, not corrected."),
        ("Privacy", "🟢 Met",
         "Aggregated tiles and modelled surfaces only. No individual speed tests, no "
         "subscriber data, coarsest resolution the decision needs."),
        ("Transparency", "🟢 Met",
         "Every ranking exposes its factor contributions. Weights are user-visible and "
         "adjustable. Corrections to upstream data are published, not silent."),
        ("Accountability", "🟡 Partial",
         "Output framed as a survey trigger, not an allocation. A named team owner is "
         "required before any operational use."),
        ("Safety", "🟡 Partial",
         "The tool declines to rank where evidence is thin. It cannot yet render the "
         "no-data tier because those rows are filtered upstream."),
        ("Sustainability", "🟢 Met",
         "Small CPU-trainable model, open datasets, no live raster compute. The purpose "
         "of the system is emissions reduction."),
        ("Human oversight", "🟢 Met",
         "No automated allocation. A planner reviews and can override; affected "
         "communities can contest a ranking through the survey process."),
    ], columns=["Dimension", "Status", "Evidence"])
    st.dataframe(ethics, hide_index=True, use_container_width=True)
    st.caption("Three amber, four green. Claiming all green would be the tell that we had "
               "not actually run the audit.")

# ─────────────────────────────────────────────  method

with tab_method:
    st.subheader("Problem–decision contract")
    a, b = st.columns(2)
    a.markdown(
        """
**This tool may be used to**

- Screen and prioritise sites *for further assessment and field survey*
- Identify where solar resource is strong relative to inferred energy burden
- Produce indicative emissions and savings estimates from published averages
- Order the queue for detailed microgrid design
        """
    )
    b.markdown(
        """
**This tool may not be used to**

- Assert that a specific site is off-grid — status is inferred, not observed
- Claim an area has no coverage — no observation means no measurement
- Present site-specific costed business cases
- Make any claim about a named operator's emissions
        """
    )

    st.subheader("Where the numbers come from")
    st.markdown(
        f"""
- Full-conversion abatement: {BASELINE_LITRES:,.0f} L/yr × {SOLAR_HYBRID_REDUCTION:.0%}
  × {DIESEL_KG_CO2_PER_L} kg CO₂/L = **{ABATEMENT_FULL_TCO2E:.2f} tCO₂e/yr**, applied
  probability-weighted by off-grid likelihood (GSMA published averages)
- Off-grid inference: VIIRS night radiance, distance to power infrastructure and roads
- Solar: Earth Engine surface solar radiation · Terrain: NASADEM slope and elevation
- Population: WorldPop 2020 · Performance: Ookla Open Data zoom-16 tiles
- Model: gradient boosting, 0.5° spatially blocked cross-validation
        """
    )

    st.subheader("Positioning")
    st.info(
        "HOMER Pro designs the microgrid for one site, bottom-up. This is a top-down "
        "national scanner. Our output is the shortlist worth paying an engineer to "
        "model properly."
    )
