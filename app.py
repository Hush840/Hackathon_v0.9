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


SCORE_COLS = ("off_grid_likelihood", "solar_viability", "logistics_difficulty")


@st.cache_data(show_spinner=False)
def load(country_key: str) -> pd.DataFrame:
    df = pd.read_parquet(matrix_paths()[country_key])
    df = df.drop(columns=[c for c in ("geometry", ".geo", "__index_level_0__") if c in df],
                 errors="ignore")
    # The 12 Aug export keeps thin-evidence tiles but leaves their index columns null,
    # which is the masking working as designed. Earlier exports filtered them out
    # upstream, so every row was rankable. Handle both without branching downstream.
    df["rankable"] = df[list(SCORE_COLS)].notna().all(axis=1)
    return df


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
    ok = np.isfinite(y) & np.isfinite(p)
    if ok.sum() < 2:
        return float("nan")
    y, p = y[ok], p[ok]
    return float(1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum())


@st.cache_data(show_spinner=False)
def correct(df: pd.DataFrame) -> pd.DataFrame:
    """Corrections applied on top of the pipeline output. All disclosed in the
    Data integrity tab — nothing is silently changed."""
    d = df.copy()

    # Percentiles are computed among rankable tiles only, so masked thin-evidence
    # rows never shift another tile's position.
    ok = d["rankable"] if "rankable" in d else pd.Series(True, index=d.index)
    for col in SCORE_COLS:
        d[f"{col}_n"] = pct_rank(d[col].where(ok))
    d["population_n"] = pct_rank(d["population_total"].where(ok))

    # Team decision: follow model_pipeline.py, where logistics_difficulty is a
    # divisor — harder to reach means lower priority, because installation and
    # mobilisation cost more. Inverted here so the additive score keeps that
    # direction.
    d["access_ease_n"] = 1.0 - d["logistics_difficulty_n"]

    # Signed residual recovered from the shipped columns. The supplied
    # underperformance_residual is floored at 1.0 for ~53% of rows.
    d["residual_signed"] = d["download_kbps"] - d["cv_predicted_speed"]
    d["has_cv"] = d["residual_signed"].notna()
    d["underperforming"] = d["residual_signed"] < 0

    # The model is trained and validated on the underserved-target population. The
    # 12 Aug export also predicts the wider sufficient-evidence set, where it scores
    # R² −1.17 — outside its design population. We report that, but we do not let it
    # drive the shortfall term. Both choices give an identical top 50; this one is
    # defensible.
    d["cv_trusted"] = d["has_cv"]
    if "is_underserved_target" in d:
        d["cv_trusted"] &= d["is_underserved_target"].fillna(False).astype(bool)

    # Only shortfall counts as priority signal; overperformance is not a problem.
    # Tiles with no trusted prediction score 0 rather than NaN — absence of an
    # estimate is not evidence of a shortfall. Disclosed in Data integrity.
    d["shortfall"] = (-d["residual_signed"].where(d["cv_trusted"])).clip(lower=0).fillna(0.0)
    d["residual_n"] = pct_rank(d["shortfall"].where(ok))

    # Abatement. The 12 Aug export varies it per site, so use it as supplied. Earlier
    # exports shipped one constant for every row, which we replace with a likelihood-
    # weighted estimate capped at 1.0 so countries stay comparable.
    supplied = d.get("indicative_abatement_tco2e_yr")
    if supplied is not None and supplied.nunique(dropna=True) > 1:
        d["expected_abatement_tco2e"] = supplied
        d.attrs["abatement_source"] = "pipeline (per site)"
    else:
        d["expected_abatement_tco2e"] = ABATEMENT_FULL_TCO2E * d["off_grid_likelihood"].clip(0, 1)
        d.attrs["abatement_source"] = "corrected (likelihood-weighted)"
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
full = correct(raw)
data = full[full["rankable"]].copy()      # everything rankable
masked = full[~full["rankable"]].copy()   # thin evidence — mapped, never ranked

if country in ("singapore", "brunei", "brunei_darussalam"):
    st.sidebar.warning(
        "Negative control, not a target. Singapore is ~100% electrified yet the "
        "off-grid proxy still fires — it needs recalibration for dense urban areas."
    )
else:
    st.sidebar.caption("Same pipeline, different file. Nothing else changes.")

_vintage = "12 Aug — masked tiers, per-site abatement, SHAP" if len(masked) else "8 Aug"
st.sidebar.caption(f"Export: {_vintage}")

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
            if "top_shap_driver" in shortlist.columns and pd.notna(row.top_shap_driver):
                st.caption(
                    f"Pipeline SHAP agrees the strongest single driver of this tile's "
                    f"predicted speed is **{row.top_shap_driver}** "
                    f"({row.top_shap_value:+,.0f} kbps)."
                )
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
                "measured vs predicted (kbps)": (
                    f"{row.download_kbps:,.0f} vs {row.cv_predicted_speed:,.0f}"
                    if pd.notna(row.cv_predicted_speed)
                    else f"{row.download_kbps:,.0f} measured · no out-of-block prediction"
                ),
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

    cv = data[data["cv_trusted"]]
    wider = data[data["has_cv"] & ~data["cv_trusted"]]
    r2_block = r_squared(cv.download_kbps, cv.cv_predicted_speed)
    r2_in = r_squared(cv.download_kbps, cv.predicted_download_kbps)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Out-of-block R²", f"{r2_block:.3f}",
              help="Spatially blocked cross-validation on the validated population")
    m2.metric("In-sample R²", f"{r2_in:.3f}")
    if "spatial_block" in data:
        m3.metric("Spatial blocks", f"{data.spatial_block.nunique()}", help="0.5° blocks")
    else:
        m3.metric("Cross-validated tiles", f"{len(cv):,}")
    m4.metric("Tiles underperforming", f"{cv.underperforming.mean() * 100:.0f}%")

    st.caption("The gap is the cost of honest spatial validation. Random splits flatter.")

    if len(wider):
        all_cv = data[data["has_cv"]]
        st.warning(
            f"**Outside its design population the model fails.** It is trained and "
            f"validated on the {len(cv):,} underserved-target tiles above. This export "
            f"also predicts the wider sufficient-evidence set, and across all "
            f"{len(all_cv):,} ranked tiles out-of-block R² is "
            f"**{r_squared(all_cv.download_kbps, all_cv.cv_predicted_speed):.2f}** — worse "
            "than predicting the mean. That set includes urban tiles an order of magnitude "
            "faster than anything in training.\n\n"
            "So the shortfall term is applied only where the model is validated. The "
            "other tiles score zero on it rather than being ranked on an extrapolation. "
            "Both choices produce an identical top 50 — we took the defensible one."
        )

    sc = cv[["cv_predicted_speed", "download_kbps", "demographic_stratum"]].copy()
    sc.columns = ["predicted kbps", "measured kbps", "settlement"]
    st.scatter_chart(sc.sample(min(1500, len(sc)), random_state=0),
                     x="predicted kbps", y="measured kbps", color="settlement", height=380)
    st.caption("Below the diagonal = underperforming.")

    st.subheader("Where the shortfall is")
    under = cv[cv.underperforming].copy()
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
    st.caption(f"Only the {len(under):,} underperforming tiles are drawn.")

    st.subheader("Fairness — does the model work equally well everywhere?")
    fair = cv.assign(abs_err=cv.residual_signed.abs()).groupby("demographic_stratum").agg(
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

    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Ranked — sufficient evidence", f"{len(data):,}")
    e2.metric("Masked — thin evidence", f"{len(masked):,}",
              help="Present in the export, deliberately excluded from ranking")
    e3.metric("East Malaysia share", f"{(data.region == 'East').mean() * 100:.0f}%",
              help="The JENDELA Phase 2 priority region")
    e4.metric("Median tests per tile", f"{data.tests.median():.0f}",
              delta=f"{masked.tests.median():.0f} when masked" if len(masked) else None,
              delta_color="off")

    v = view_for(full)
    cov_layers = outline_layer(country)
    if len(masked):
        cov_layers.append(
            pdk.Layer("ScatterplotLayer", data=masked[["longitude", "latitude"]],
                      get_position=["longitude", "latitude"], get_fill_color=[170, 170, 170, 70],
                      get_radius=3000, radius_min_pixels=2, radius_max_pixels=8)
        )
    cov_layers.append(
        pdk.Layer("ScatterplotLayer", data=data[["longitude", "latitude"]],
                  get_position=["longitude", "latitude"], get_fill_color=[30, 130, 120, 150],
                  get_radius=3000, radius_min_pixels=2.5, radius_max_pixels=10)
    )
    st.pydeck_chart(
        pdk.Deck(layers=cov_layers,
                 initial_view_state=pdk.ViewState(latitude=v["lat"], longitude=v["lon"], zoom=v["zoom"]),
                 map_style=BASEMAP, height=MAP_HEIGHT),
        use_container_width=True,
    )
    if len(masked):
        st.caption(
            f"Grey tiles are masked: {len(masked):,} tiles carry a median of "
            f"{masked.tests.median():.0f} speed tests against {data.tests.median():.0f} for "
            "ranked tiles. They are shown so the thin-evidence areas read as thin, not absent."
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
        f"""
| # | Issue in the scored matrix | Correction | State |
|---|---|---|---|
| 1 | `priority_score` is multiplicative and unbounded, so one factor swamps the rest — {(raw.priority_score == 0).mean() * 100:.0f}% of rows sit at exactly 0 | Rebuilt from percentile ranks with visible, adjustable weights, bounded 0–100 | still applied |
| 2 | `indicative_abatement_tco2e_yr` shipped as one constant for every tile | Now varies per site upstream — **{raw.indicative_abatement_tco2e_yr.nunique():,} distinct values**, used as supplied | **fixed upstream** |
| 3 | `underperformance_residual` floored at 1.0, losing direction | Signed residual recovered as `download_kbps − cv_predicted_speed`; floor now affects {(raw.underperformance_residual <= 1).mean() * 100:.0f}% of rows | mostly fixed |
| 4 | `off_grid_likelihood` reaches {raw.off_grid_likelihood.max():.2f} despite a nominal 0–1 range | Converted to percentile ranks | still applied |
| 5 | Thin-evidence tiles were filtered out before export, so masking could not be shown | Now shipped and masked — {len(data):,} ranked, {len(masked):,} held back | **fixed upstream** |
        """
    )

    st.subheader("The finding we would rather not have")
    st.markdown(
        """
At default weights, **East Malaysia takes 0% of the top 50** — despite holding 12.3% of
our ranked tiles and being the region JENDELA Phase 2 explicitly prioritises.

The cause is the ease-of-access term. Mobilisation cost dominates at screening stage, so
remote Sabah and Sarawak tiles rank down. Set that weight to zero and East Malaysia's
share goes to **32%**, while total expected abatement moves from 951 to 947 tCO₂e — a
**0.4% difference.**

So the access weighting is not buying us carbon. It is buying us convenience, and it is
doing so at the direct expense of the region the policy targets. That slider is in the
sidebar and the effect is reproducible in about four seconds.

We have left the default where the pipeline's own convention puts it, and surfaced the
consequence here rather than tuning until the map looked equitable.
        """
    )

    st.subheader("Which export each country runs")
    st.markdown(
        """
Malaysia runs the 12 August export. The other seven countries stay on 8 August, because
they were not regenerated — we did not re-run anyone else's pipeline to make the set look
uniform.

The app reads both formats without branching. `load()` derives a `rankable` flag from
whether the index columns are populated; where thin-evidence rows are absent, every row
is rankable and the masking section simply has nothing to show. Nothing about the
scoring differs between the two.

| Export | Countries | What it carries |
|---|---|---|
| **12 Aug** | Malaysia | Two confidence tiers, per-site abatement, SHAP drivers, spatial blocks |
| **8 Aug** | Indonesia, Thailand, Vietnam, Philippines, Myanmar, Cambodia, Singapore | One tier, constant abatement — corrections below still apply in full |

Singapore was offered a 12 August file and we declined it: R² −1.49 against 0.990 on the
current one. It is a negative control, so there was nothing to gain.
        """
    )

    st.subheader("Limits we cannot fix downstream")
    st.markdown(
        f"""
- **The shortfall term is applied to {int(data.cv_trusted.sum()):,} of {len(data):,} ranked
  tiles** — the population the model is validated on. The rest score zero on it rather
  than being ranked on an extrapolation, so that slider does less work than it implies.
  See the Model tab.
- **The evidence filter biases against the target population** — see Evidence coverage.
- **Rows are Ookla zoom-16 tiles, not tower sites.** `site_id` is a 16-character quadkey.
- **Off-grid status is inferred** from night-lights and road/power proximity, not utility
  records. Every row is a candidate requiring operator confirmation.
- **Ease of access makes this a first-wave list, not a complete one.** See the finding
  above. The hardest Sabah and Sarawak sites need a different instrument — one that
  prices helicopter mobilisation rather than penalising it — and that is in the roadmap.
- `essential_service_weight` is 50.0 for over 75% of rows and `antenna_count` reaches
  43,394 on a single tile — both look like join artefacts and are excluded from scoring.
        """
    )

    k1, k2, k3 = st.columns(3)
    k1.metric("Distinct confidence tiers", data["confidence_tier"].nunique())
    k2.metric("Distinct abatement values (as shipped)", raw["indicative_abatement_tco2e_yr"].nunique())
    k3.metric("Supplied residual at floor", f"{(raw['underperformance_residual'] <= 1).mean() * 100:.0f}%")

    st.subheader("A re-export we tested and rejected")
    st.markdown(
        """
On 10 August the pipeline was re-run to restore the missing confidence tiers, and it
worked — thin-evidence rows survived the ETL for the first time. We ran the second
export through the same checks before adopting it, and did not adopt it.

`is_underserved_target == True` isolates exactly the rows in the export above: same
2,815 site IDs, byte-identical measured speeds. Only the predictions changed.

| Country | Out-of-block R², current | Same rows, re-export |
|---|---|---|
| Malaysia | **0.590** | **−8.73** |
| Philippines | **0.545** | **−10.01** |
| Thailand | **0.302** | **−8.43** |

A negative R² is worse than predicting the mean. In-sample fell to −6.97, so the model
was no longer fitting even its training data. The cause is that the expanded population
is 73% thin-evidence tiles carrying a median of **3 speed tests** against 42 for
sufficient-evidence tiles. Keeping those rows in the *output* is right. Keeping them in
*training* is what broke it — and those are separable.

The fix is a one-line filter on the training set. Until it lands, we ship the export
that measures better rather than the one that looks more complete.
        """
    )

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
