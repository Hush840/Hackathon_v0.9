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
MATRIX_GLOB = "jendela_phase2_esg_matrix_*.parquet"

# Filename stem -> the Country value used in Asean.geojson
GEOJSON_NAME = {
    "malaysia": "Malaysia", "indonesia": "Indonesia", "singapore": "Singapore",
    "thailand": "Thailand", "vietnam": "Vietnam", "viet_nam": "Vietnam",
    "myanmar": "Myanmar", "philippines": "Philippines", "cambodia": "Cambodia",
    "laos": "Laos DR", "lao_pdr": "Laos DR", "brunei": "Brunei Darussalam",
    "brunei_darussalam": "Brunei Darussalam",
}


DIESEL_KG_CO2_PER_L = 2.63
BASELINE_LITRES = 13_000.0
SOLAR_HYBRID_REDUCTION = 0.65
ABATEMENT_FULL_TCO2E = BASELINE_LITRES * SOLAR_HYBRID_REDUCTION * DIESEL_KG_CO2_PER_L / 1000

MAP_HEIGHT = 560
BASEMAP = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"

st.set_page_config(page_title="JENDELA Phase 2 — ESG triage", layout="wide")


# ─────────────────────────────────────────────  data

@st.cache_data(show_spinner=False)
def matrix_paths() -> dict:
    """Find every country matrix under data/, including subfolders.

    If the same country appears more than once, the most recently modified file
    wins — so dropping a fresh export into a subfolder supersedes an older copy
    without anyone having to delete anything.
    """
    best: dict[str, Path] = {}
    for p in DATA_DIR.rglob(MATRIX_GLOB):
        key = p.stem.replace("jendela_phase2_esg_matrix_", "").lower()
        if key not in best or p.stat().st_mtime > best[key].stat().st_mtime:
            best[key] = p
    return best


@st.cache_data(show_spinner=False)
def available_countries() -> dict:
    """Label -> key. Adding a country is a file drop, nothing else."""
    return {k.replace("_", " ").title(): k for k in sorted(matrix_paths())}


@st.cache_data(show_spinner=False)
def load(country_key: str) -> pd.DataFrame:
    df = pd.read_parquet(matrix_paths()[country_key])
    return df.drop(columns=[c for c in ("geometry", ".geo", "__index_level_0__") if c in df],
                   errors="ignore")


@st.cache_data(show_spinner=False)
def boundary(country_key: str):
    path = DATA_DIR / "Asean.geojson"
    if not path.exists():
        return None
    want = GEOJSON_NAME.get(country_key)
    if want is None:
        return None
    gj = json.loads(path.read_text())
    feats = [f for f in gj["features"] if f["properties"].get("Country") == want]
    return {"type": "FeatureCollection", "features": feats} if feats else None


def view_for(df: pd.DataFrame) -> dict:
    """Fit the camera to the data rather than hardcoding per country."""
    lon_span = max(float(df.longitude.max() - df.longitude.min()), 0.05)
    lat_span = max(float(df.latitude.max() - df.latitude.min()), 0.05)
    zoom = np.log2(360.0 / max(lon_span, lat_span)) + 0.8
    return dict(lat=float(df.latitude.mean()), lon=float(df.longitude.mean()),
                zoom=float(np.clip(zoom, 2.5, 11.0)))


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

    d["region"] = np.where(d["longitude"] > 109, "East", "West")  # meaningful for Malaysia
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


def legend_html(label: str = "priority", rings: bool = True) -> str:
    stops = [ramp([x])[0] for x in (0.0, 0.25, 0.5, 0.75, 1.0)]
    swatches = "".join(
        f'<span style="display:inline-block;width:30px;height:11px;'
        f'background:rgb({c[0]},{c[1]},{c[2]})"></span>' for c in stops
    )
    ring = (
        '<div style="display:flex;align-items:center;gap:7px">'
        '<svg width="16" height="16"><circle cx="8" cy="8" r="6" fill="none" '
        'stroke="currentColor" stroke-width="1.8" opacity="0.85"/></svg>'
        "<span>shortlisted</span></div>"
    ) if rings else ""
    return f"""
<div style="display:flex;flex-wrap:wrap;gap:22px;align-items:center;
            padding:8px 0 2px 0;font-size:13px">
  <div style="display:flex;align-items:center;gap:7px">
    <span style="opacity:.7">low</span>{swatches}<span style="opacity:.7">high</span>
    <span style="opacity:.7">{label}</span>
  </div>
  {ring}
  <div style="opacity:.7">1 dot = one ~610 m tile · gaps = no measurement</div>
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
COUNTRIES = available_countries()
if not COUNTRIES:
    st.error(f"No matrices found in {DATA_DIR}. Expected files named {MATRIX_GLOB}.")
    st.stop()
_default = list(COUNTRIES).index("Malaysia") if "Malaysia" in COUNTRIES else 0
country_label = st.sidebar.selectbox("Country", list(COUNTRIES), index=_default)
country = COUNTRIES[country_label]

raw = load(country)
data = correct(raw)

if country in ("singapore", "brunei", "brunei_darussalam"):
    st.sidebar.warning(
        "Negative control, not a target. Singapore is ~100% electrified yet the "
        "off-grid proxy still fires — it needs recalibration for dense urban areas."
    )
else:
    st.sidebar.caption("Same pipeline, different file. Nothing else changes.")

st.sidebar.subheader("Priority weights")
st.sidebar.caption("Live — this is the sensitivity analysis.")
w = dict(
    offgrid=st.sidebar.slider("Off-grid likelihood", 0.0, 1.0, 0.45, 0.05),
    solar=st.sidebar.slider("Solar viability", 0.0, 1.0, 0.25, 0.05),
    logistics=st.sidebar.slider("Ease of access", 0.0, 1.0, 0.20, 0.05),
    residual=st.sidebar.slider("Service shortfall", 0.0, 1.0, 0.10, 0.05),
    population=st.sidebar.slider("Population served", 0.0, 1.0, 0.00, 0.05),
)
st.sidebar.caption("Population is 0 on purpose — weighting it pulls dense cities to the top.")

st.sidebar.subheader("Filters")
strata = st.sidebar.multiselect(
    "Settlement type", sorted(data["demographic_stratum"].unique()),
    default=[s for s in ("rural", "peri-urban") if s in set(data["demographic_stratum"])],
)
top_n = st.sidebar.slider("Shortlist size", 10, 300, 50, 10)
amenity_km_max = st.sidebar.slider(
    "Max distance to school or clinic (km)", 0.1, 5.0, 5.0, 0.1,
    help="5.0 keeps everything. The pipeline's own threshold is 2.5 km, but that "
         "retains 96% of tiles — tighten below ~1 km to make it discriminate.",
)

st.sidebar.subheader("Map layers")
COLOUR_BY = {
    "Priority": ("priority_v2", "priority"),
    "Off-grid likelihood": ("off_grid_likelihood", "off-grid likelihood"),
    "Solar viability": ("solar_viability", "solar"),
    "Distance to power": ("distance_to_power_m", "distance to power"),
    "Distance to road": ("distance_to_road_m", "distance to road"),
    "Population": ("population_total", "population"),
}
colour_choice = st.sidebar.selectbox("Colour sites by", list(COLOUR_BY), index=0)
show_rings = st.sidebar.checkbox("Shortlist rings", value=True)
show_border = st.sidebar.checkbox("National boundary", value=True)

data["priority_v2"] = score(data, w)
view = (data[data["demographic_stratum"].isin(strata)] if strata else data).copy()
if amenity_km_max < 5.0:
    view = view[view["amenity_km"] <= amenity_km_max]
shortlist = view.nlargest(top_n, "priority_v2")

# ─────────────────────────────────────────────  header

st.title("JENDELA Phase 2 — solar conversion triage")
st.caption(
    f"{country_label} · {len(data):,} candidate tiles · screening only — every site "
    "requires operator confirmation and a field survey"
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

    col, col_label = COLOUR_BY[colour_choice]
    plot = view.copy()
    plot["shade"] = pct_rank(plot[col])
    plot["color"] = ramp(plot["shade"])
    plot["radius"] = 1200 + 5200 * (plot["priority_v2"] / 100) ** 2

    v = view_for(view if len(view) else data)
    layers = (outline_layer(country) if show_border else []) + [
        pdk.Layer("ScatterplotLayer",
                  data=plot[["longitude", "latitude", "color", "radius", "priority_v2"]],
                  get_position=["longitude", "latitude"], get_fill_color="color",
                  get_radius="radius", radius_min_pixels=3.5, radius_max_pixels=26,
                  pickable=True, opacity=0.75),
    ]
    if show_rings:
        layers.append(
            pdk.Layer("ScatterplotLayer", data=shortlist[["longitude", "latitude"]],
                      get_position=["longitude", "latitude"], get_fill_color=[0, 0, 0, 0],
                      get_line_color=[20, 20, 20, 220], stroked=True, filled=False,
                      line_width_min_pixels=1.6, get_radius=3200, radius_max_pixels=26)
        )
    st.pydeck_chart(
        pdk.Deck(layers=layers,
                 initial_view_state=pdk.ViewState(latitude=v["lat"], longitude=v["lon"], zoom=v["zoom"]),
                 map_style=BASEMAP, tooltip={"text": "priority {priority_v2}"},
                 height=MAP_HEIGHT),
        use_container_width=True,
    )
    st.markdown(legend_html(col_label, rings=show_rings), unsafe_allow_html=True)

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
    st.caption("A survey-ordering list, not an investment decision.")

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
              help="High overlap means the ranking is not an artefact of one weighting.")

# ─────────────────────────────────────────────  model

with tab_model:
    st.subheader("The model behind the shortfall signal")
    st.caption(
        "Speed predicted from terrain and population only. Tiles far below prediction "
        "are underperforming for reasons geography does not explain — tractable targets."
    )

    r2_block = r_squared(data.download_kbps, data.cv_predicted_speed)
    r2_in = r_squared(data.download_kbps, data.predicted_download_kbps)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Out-of-block R²", f"{r2_block:.3f}", help="Spatially blocked cross-validation")
    m2.metric("In-sample R²", f"{r2_in:.3f}")
    m3.metric("Spatial blocks", f"{data.spatial_block.nunique()}", help="0.5° blocks")
    m4.metric("Tiles underperforming", f"{data.underperforming.mean() * 100:.0f}%")

    st.caption("The gap is the cost of honest spatial validation. Random splits flatter.")

    sc = data[["cv_predicted_speed", "download_kbps", "demographic_stratum"]].copy()
    sc.columns = ["predicted kbps", "measured kbps", "settlement"]
    st.scatter_chart(sc.sample(min(1500, len(sc)), random_state=0),
                     x="predicted kbps", y="measured kbps", color="settlement", height=380)
    st.caption("Below the diagonal = underperforming.")

    st.subheader("Where the shortfall is")
    under = data[data.underperforming].copy()
    under["color"] = ramp(pct_rank(under["shortfall"]))
    v = view_for(data)
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
    st.caption(f"Only the {data.underperforming.sum():,} underperforming tiles are drawn.")

    st.subheader("Fairness — does the model work equally well everywhere?")
    fair = data.assign(abs_err=data.residual_signed.abs()).groupby("demographic_stratum").agg(
        tiles=("site_id", "size"),
        median_abs_error_kbps=("abs_err", "median"),
        underperforming_pct=("underperforming", lambda s: round(s.mean() * 100, 1)),
    ).reset_index()
    st.dataframe(fair.round(1), hide_index=True, use_container_width=True)
    st.caption("A model accurate on average can still be unusable rurally.")

# ─────────────────────────────────────────────  evidence coverage

with tab_cov:
    st.subheader("Where we have no evidence at all")
    st.caption(
        "Every tile cleared a minimum-activity filter. Remote areas generate few speed "
        "tests, so the places most likely to be off-grid are the ones we know least "
        "about. Blank space is **absence of measurement, never absence of coverage.**"
    )

    e1, e2, e3 = st.columns(3)
    e1.metric("Tiles with evidence", f"{len(data):,}")
    e2.metric("East Malaysia share", f"{(data.region == 'East').mean() * 100:.0f}%",
              help="The JENDELA Phase 2 priority region")
    e3.metric("Median tests per tile", f"{data.tests.median():.0f}")

    v = view_for(data)
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
    st.caption("Rural tiles carry the least evidence and the most inferential weight.")

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

    st.info("A screening tool that cannot audit its own inputs should not allocate public money.")

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
    st.caption("Three amber. Claiming all green would be the tell we had not run the audit.")

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
