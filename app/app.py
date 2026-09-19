"""Powering the Last Mile — JENDELA Phase 2 screening dashboard.

Decision-facing Streamlit UI for the scored matrices produced by the backend.
The backend remains the single source of truth for the default priority score.

Run:
    streamlit run app.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MATRIX_GLOB = "jendela_phase2_esg_matrix_*.parquet"
BASEMAP = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
MAP_HEIGHT = 640

APPROVED_TIER = "Sufficient Evidence - Ranked Screening Approved"

PIPELINE_WEIGHTS = {
    "diesel": 0.40,
    "solar": 0.25,
    "community": 0.30,
    "feasibility": 0.05,
}

SCENARIOS = {
    "Balanced — pipeline default": PIPELINE_WEIGHTS,
    "Carbon-first scenario": {
        "diesel": 0.55,
        "solar": 0.30,
        "community": 0.10,
        "feasibility": 0.05,
    },
    "Community-first scenario": {
        "diesel": 0.25,
        "solar": 0.20,
        "community": 0.50,
        "feasibility": 0.05,
    },
}

PILLAR_COLS = {
    "diesel": "off_grid_score_n",
    "solar": "solar_score_n",
    "community": "community_impact_n",
    "feasibility": "access_ease_n",
}

GEOJSON_NAME = {
    "malaysia": "Malaysia",
    "indonesia": "Indonesia",
    "singapore": "Singapore",
    "thailand": "Thailand",
    "vietnam": "Vietnam",
    "viet_nam": "Vietnam",
    "myanmar": "Myanmar",
    "philippines": "Philippines",
    "cambodia": "Cambodia",
    "laos": "Laos DR",
    "lao_pdr": "Laos DR",
    "laos_dr": "Laos DR",
    "brunei": "Brunei Darussalam",
    "brunei_darussalam": "Brunei Darussalam",
}

st.set_page_config(
    page_title="Powering the Last Mile",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.5rem; padding-bottom: 2rem; max-width: 1450px;}
      [data-testid="stSidebar"] {min-width: 315px; max-width: 315px;}
      .hero {
        padding: 1.1rem 1.3rem 1rem 1.3rem;
        border: 1px solid rgba(128,128,128,.22);
        border-radius: 16px;
        margin-bottom: 1rem;
        background: rgba(128,128,128,.045);
      }
      .hero h1 {margin: 0; font-size: 2rem; line-height: 1.15;}
      .hero p {margin: .45rem 0 0 0; opacity: .78; font-size: 1rem;}
      .scope-badge {
        display:inline-block; padding:.18rem .55rem; margin-top:.6rem;
        border-radius:999px; border:1px solid rgba(128,128,128,.35);
        font-size:.82rem; opacity:.88;
      }
      .site-card {
        border: 1px solid rgba(128,128,128,.22);
        border-radius: 14px;
        padding: 1rem 1.1rem;
        background: rgba(128,128,128,.035);
      }
      .muted {opacity:.72;}
      div[data-testid="stMetric"] {
        border:1px solid rgba(128,128,128,.18);
        padding:.72rem .8rem;
        border-radius:12px;
        background:rgba(128,128,128,.025);
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# -----------------------------------------------------------------------------
# Data loading
# -----------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def matrix_paths() -> dict[str, Path]:
    """Load only approved matrices directly under data/.

    data/NEW is staging and is intentionally never auto-loaded by production.
    """
    best: dict[str, Path] = {}
    for p in DATA_DIR.glob(MATRIX_GLOB):
        key = p.stem.replace("jendela_phase2_esg_matrix_", "").lower()
        if key not in best or p.stat().st_mtime > best[key].stat().st_mtime:
            best[key] = p
    return best


@st.cache_data(show_spinner=False)
def available_countries() -> dict[str, str]:
    return {k.replace("_", " ").title(): k for k in sorted(matrix_paths())}


@st.cache_data(show_spinner=False)
def load_matrix(country_key: str, file_mtime_ns: int) -> pd.DataFrame:
    # file_mtime_ns is intentionally part of the cache key so replacing an
    # approved parquet refreshes the dashboard without requiring a manual
    # Streamlit cache clear.
    del file_mtime_ns
    path = matrix_paths()[country_key]
    df = pd.read_parquet(path)
    df = df.drop(
        columns=[c for c in ("geometry", ".geo", "__index_level_0__") if c in df.columns],
        errors="ignore",
    )

    # Explicit governance decision first; fallback only for legacy exports.
    if "confidence_tier" in df.columns:
        df["rankable"] = df["confidence_tier"].eq(APPROVED_TIER)
    else:
        needed = ["off_grid_likelihood", "solar_viability", "logistics_difficulty"]
        df["rankable"] = df[needed].notna().all(axis=1)

    # Fail loudly if the final backend-native pillars are missing.
    missing_pillars = [c for c in PILLAR_COLS.values() if c not in df.columns]
    if missing_pillars:
        raise ValueError(
            "This dashboard expects the final backend-native pillar columns. Missing: "
            + ", ".join(missing_pillars)
        )

    if "priority_score" not in df.columns:
        raise ValueError("Missing backend priority_score. Do not let the UI recreate production ranking.")

    return df


@st.cache_data(show_spinner=False)
def country_boundary(country_key: str):
    path = DATA_DIR / "Asean.geojson"
    if not path.exists():
        return None
    wanted = GEOJSON_NAME.get(country_key)
    if wanted is None:
        return None
    gj = json.loads(path.read_text(encoding="utf-8"))
    feats = [f for f in gj.get("features", []) if f.get("properties", {}).get("Country") == wanted]
    return {"type": "FeatureCollection", "features": feats} if feats else None


def prepare(df: pd.DataFrame, country_key: str) -> pd.DataFrame:
    d = df.copy()

    # Display-only helpers. No production score is changed here.
    d["amenity_km"] = d.get("distance_to_amenity_m", pd.Series(np.nan, index=d.index)) / 1000.0
    d["power_km"] = d.get("distance_to_power_m", pd.Series(np.nan, index=d.index)) / 1000.0
    d["road_km"] = d.get("distance_to_road_m", pd.Series(np.nan, index=d.index)) / 1000.0

    if country_key == "malaysia":
        # Practical regional split for the current dataset. It is a UI grouping,
        # not a state-level administrative classification.
        d["macro_region"] = np.where(d["longitude"] > 109.0, "East Malaysia", "Peninsular Malaysia")
    else:
        d["macro_region"] = "National"

    d["cv_trusted"] = False
    if "is_underserved_target" in d.columns and "cv_predicted_speed" in d.columns:
        d["cv_trusted"] = (
            d["is_underserved_target"].fillna(False).astype(bool)
            & d["cv_predicted_speed"].notna()
        )
        if "model_residual_enabled" in d.columns:
            d["cv_trusted"] &= d["model_residual_enabled"].fillna(False).astype(bool)

    if "prediction_uncertainty_pct" in d.columns:
        d["model_disagreement_pct"] = 100.0 * d["prediction_uncertainty_pct"].astype(float)
    else:
        d["model_disagreement_pct"] = np.nan

    if "indicative_abatement_tco2e_yr" in d.columns:
        d["expected_abatement_tco2e"] = d["indicative_abatement_tco2e_yr"]
    else:
        d["expected_abatement_tco2e"] = np.nan

    if "indicative_opex_saving_usd" not in d.columns:
        d["indicative_opex_saving_usd"] = np.nan

    return d


# -----------------------------------------------------------------------------
# Scoring / scope helpers
# -----------------------------------------------------------------------------

def scenario_score(d: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    total = sum(weights.values()) or 1.0
    raw = sum(weights[k] * d[PILLAR_COLS[k]] for k in weights) / total
    return (100.0 * raw).round(2)


def apply_policy_scope(
    approved: pd.DataFrame,
    policy_scope: str,
    geography: str,
    country_key: str,
) -> pd.DataFrame:
    d = approved.copy()

    if policy_scope == "Rural Last-Mile":
        d = d[d["demographic_stratum"].eq("rural")]

    if country_key == "malaysia":
        if geography == "East Malaysia (Sabah + Sarawak)":
            d = d[d["macro_region"].eq("East Malaysia")]
        elif geography == "Peninsular Malaysia":
            d = d[d["macro_region"].eq("Peninsular Malaysia")]

    return d.copy()


def add_scope_rank(d: pd.DataFrame, score_col: str) -> pd.DataFrame:
    out = d.sort_values(score_col, ascending=False, kind="mergesort").reset_index(drop=True).copy()
    out["scope_rank"] = np.arange(1, len(out) + 1)
    return out


def r_squared(y, p) -> float:
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    ok = np.isfinite(y) & np.isfinite(p)
    if ok.sum() < 2:
        return float("nan")
    y = y[ok]
    p = p[ok]
    denom = ((y - y.mean()) ** 2).sum()
    if denom == 0:
        return float("nan")
    return float(1.0 - ((y - p) ** 2).sum() / denom)


def view_for(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"lat": 4.2, "lon": 109.5, "zoom": 4.2}
    lon_span = max(float(df.longitude.max() - df.longitude.min()), 0.05)
    lat_span = max(float(df.latitude.max() - df.latitude.min()), 0.05)
    zoom = np.log2(360.0 / max(lon_span, lat_span)) + 0.8
    return {
        "lat": float(df.latitude.mean()),
        "lon": float(df.longitude.mean()),
        "zoom": float(np.clip(zoom, 2.5, 11.0)),
    }


def color_ramp(values) -> list[list[int]]:
    x = np.clip(np.nan_to_num(np.asarray(values, dtype=float)), 0.0, 1.0)
    return [
        [int(240 - 185 * v), int(175 + 45 * v), int(65 + 95 * v), 205]
        for v in x
    ]


def priority_legend_html() -> str:
    return """
    <div style="display:flex;flex-wrap:wrap;align-items:center;gap:18px;
                padding:6px 2px 12px 2px;font-size:13px;">
      <div style="display:flex;align-items:center;gap:8px;">
        <span style="opacity:.72;">Lower priority</span>
        <div style="width:220px;height:11px;border-radius:999px;
                    background:linear-gradient(90deg,rgb(240,175,65),rgb(55,220,160));"></div>
        <span style="opacity:.72;">Higher priority</span>
      </div>
      <div style="display:flex;align-items:center;gap:6px;">
        <span style="width:13px;height:13px;display:inline-block;
                     border:2px solid #222;border-radius:50%;"></span>
        <span style="opacity:.72;">Current shortlist</span>
      </div>
      <div style="opacity:.62;">Colour is relative to the currently selected decision scope</div>
    </div>
    """


def outline_layers(country_key: str):
    gj = country_boundary(country_key)
    if gj is None:
        return []
    return [
        pdk.Layer(
            "GeoJsonLayer",
            data=gj,
            stroked=True,
            filled=False,
            get_line_color=[85, 85, 85, 160],
            line_width_min_pixels=1,
        )
    ]


def site_reasons(row: pd.Series) -> list[str]:
    values = {
        "Inferred diesel / off-grid signal": float(row.get("off_grid_score_n", np.nan)),
        "Solar suitability": float(row.get("solar_score_n", np.nan)),
        "Community impact": float(row.get("community_impact_n", np.nan)),
        "Implementation feasibility": float(row.get("access_ease_n", np.nan)),
    }
    ranked = sorted(
        [(k, v) for k, v in values.items() if np.isfinite(v)],
        key=lambda kv: kv[1],
        reverse=True,
    )
    return [f"{name}: {score * 100:.0f}/100" for name, score in ranked[:2]]


def fmt_number(value, decimals=0, suffix="") -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:,.{decimals}f}{suffix}"


# -----------------------------------------------------------------------------
# Sidebar controls
# -----------------------------------------------------------------------------

st.sidebar.title("Decision controls")

COUNTRIES = available_countries()
if not COUNTRIES:
    st.error(
        f"No approved matrices found in {DATA_DIR}. Expected top-level files named {MATRIX_GLOB}."
    )
    st.stop()

_default_country = list(COUNTRIES).index("Malaysia") if "Malaysia" in COUNTRIES else 0
country_label = st.sidebar.selectbox("Country", list(COUNTRIES), index=_default_country)
country_key = COUNTRIES[country_label]

try:
    selected_matrix_path = matrix_paths()[country_key]
    raw = load_matrix(country_key, selected_matrix_path.stat().st_mtime_ns)
except Exception as exc:
    st.error(f"Cannot load the selected matrix: {exc}")
    st.stop()

full = prepare(raw, country_key)
approved = full[full["rankable"]].copy()

available_strata = set(approved.get("demographic_stratum", pd.Series(dtype=str)).dropna().astype(str))
default_policy = "Rural Last-Mile" if "rural" in available_strata else "All evidence-qualified"
policy_scope = st.sidebar.radio(
    "Policy scope",
    ["Rural Last-Mile", "All evidence-qualified"],
    index=0 if default_policy == "Rural Last-Mile" else 1,
    help="The model is national; the decision scope can be rural last-mile without changing the backend model.",
)

if country_key == "malaysia":
    geography = st.sidebar.selectbox(
        "Geography",
        ["Malaysia — national", "East Malaysia (Sabah + Sarawak)", "Peninsular Malaysia"],
        index=0,
    )
else:
    geography = "National"

strategy = st.sidebar.selectbox(
    "Ranking strategy",
    ["Balanced — pipeline default", "Carbon-first scenario", "Community-first scenario", "Custom sensitivity"],
    index=0,
    help="Pipeline default uses the backend priority_score. Other options are explicit sensitivity scenarios.",
)

custom_weights = None
if strategy == "Custom sensitivity":
    st.sidebar.caption("Sensitivity only — this does not overwrite the backend ranking.")
    custom_weights = {
        "diesel": st.sidebar.slider("Diesel / off-grid dependence", 0.0, 1.0, 0.40, 0.05),
        "solar": st.sidebar.slider("Solar suitability", 0.0, 1.0, 0.25, 0.05),
        "community": st.sidebar.slider("Community impact", 0.0, 1.0, 0.30, 0.05),
        "feasibility": st.sidebar.slider("Implementation feasibility", 0.0, 1.0, 0.05, 0.05),
    }

shortlist_n = st.sidebar.slider("Shortlist size", 5, 100, 20, 5)

st.sidebar.divider()
st.sidebar.caption(
    "Default ranking comes directly from model_pipeline.py. Candidate status is inferred and requires operator / field confirmation."
)

scoped_base = apply_policy_scope(approved, policy_scope, geography, country_key)

if strategy == "Balanced — pipeline default":
    scoped_base["display_score"] = scoped_base["priority_score"].astype(float)
    score_label = "Pipeline priority"
    scenario_weights = PIPELINE_WEIGHTS
else:
    scenario_weights = custom_weights if custom_weights is not None else SCENARIOS[strategy]
    scoped_base["display_score"] = scenario_score(scoped_base, scenario_weights)
    score_label = strategy

scoped = add_scope_rank(scoped_base, "display_score")
shortlist = scoped.head(min(shortlist_n, len(scoped))).copy()

# Same policy/geography population, but backend default ranking, for stability comparison.
default_scope = apply_policy_scope(approved, policy_scope, geography, country_key)
default_scope = add_scope_rank(default_scope.assign(display_score=default_scope["priority_score"]), "display_score")
default_top = set(default_scope.head(min(shortlist_n, len(default_scope)))["site_id"].astype(str))
current_top = set(shortlist["site_id"].astype(str))
strategy_overlap = 100.0 * len(default_top & current_top) / max(len(default_top), 1)


# -----------------------------------------------------------------------------
# Header
# -----------------------------------------------------------------------------

scope_text = policy_scope
if country_key == "malaysia" and geography != "Malaysia — national":
    scope_text += f" · {geography}"

st.markdown(
    f"""
    <div class="hero">
      <h1>⚡ Powering the Last Mile</h1>
      <p>GeoAI screening for solar-hybrid field assessment across evidence-qualified telecom locations.</p>
      <span class="scope-badge">Decision scope: {scope_text}</span>
    </div>
    """,
    unsafe_allow_html=True,
)

if strategy != "Balanced — pipeline default":
    st.info(
        f"You are viewing **{strategy}**. The official backend score remains available as the pipeline default. "
        f"Top-{min(shortlist_n, len(shortlist))} overlap with the pipeline default in this same scope: **{strategy_overlap:.0f}%**."
    )

if scoped.empty:
    st.warning("No evidence-qualified candidates remain under the selected policy/geography scope.")
    st.stop()

# -----------------------------------------------------------------------------
# Main tabs
# -----------------------------------------------------------------------------

tab_overview, tab_priority, tab_model, tab_method = st.tabs(
    ["Overview", "Rural prioritisation", "Model & evidence", "Methodology"]
)

# -----------------------------------------------------------------------------
# Overview
# -----------------------------------------------------------------------------

with tab_overview:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Candidates in scope", f"{len(scoped):,}")
    m2.metric("Shortlisted", f"{len(shortlist):,}")
    m3.metric(
        "Indicative abatement",
        f"{shortlist['expected_abatement_tco2e'].sum():,.0f} tCO₂e/yr",
        help="Published-average screening estimate, not site-specific engineering design.",
    )
    m4.metric(
        "Population associated",
        f"{shortlist['population_total'].sum():,.0f}",
        help="Sum across shortlisted analysis tiles; not deduplicated subscriber counts.",
    )

    st.caption(
        "Screening only: a ranked candidate is a field-survey trigger, not proof that a tower is off-grid and not an investment decision."
    )

    # Full-width map: the geospatial decision view is the hero of the dashboard.
    map_data = scoped.copy()
    map_data["shade"] = map_data["display_score"].rank(pct=True)
    map_data["color"] = color_ramp(map_data["shade"])
    map_data["radius"] = 1200 + 5200 * (map_data["display_score"] / 100) ** 2

    v = view_for(map_data)
    layers = outline_layers(country_key)
    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            data=map_data[
                [
                    "longitude", "latitude", "color", "radius", "scope_rank",
                    "display_score", "demographic_stratum", "site_id",
                ]
            ],
            get_position=["longitude", "latitude"],
            get_fill_color="color",
            get_radius="radius",
            radius_min_pixels=3.5,
            radius_max_pixels=25,
            pickable=True,
            opacity=0.78,
        )
    )

    if len(shortlist):
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=shortlist[["longitude", "latitude"]],
                get_position=["longitude", "latitude"],
                get_fill_color=[0, 0, 0, 0],
                get_line_color=[20, 20, 20, 230],
                stroked=True,
                filled=False,
                line_width_min_pixels=1.7,
                get_radius=2600,
                radius_min_pixels=7,
                radius_max_pixels=22,
            )
        )

    st.pydeck_chart(
        pdk.Deck(
            layers=layers,
            initial_view_state=pdk.ViewState(
                latitude=v["lat"], longitude=v["lon"], zoom=v["zoom"]
            ),
            map_style=BASEMAP,
            tooltip={
                "text": "Priority #{scope_rank}\nScore {display_score}\n{demographic_stratum}\nTile {site_id}"
            },
            height=MAP_HEIGHT,
        ),
        use_container_width=True,
    )

    st.markdown(priority_legend_html(), unsafe_allow_html=True)
    st.caption(
        "Each dot is an Ookla analysis tile linked to the nearest OpenCellID-derived "
        "candidate-site proxy. Black rings mark the current shortlist."
    )

    st.subheader("Top candidates")
    preview_cols = [
        "scope_rank", "site_id", "display_score", "demographic_stratum",
        "macro_region", "expected_abatement_tco2e", "population_total",
    ]
    preview = shortlist[preview_cols].copy()
    preview = preview.rename(
        columns={
            "scope_rank": "Rank",
            "site_id": "Tile",
            "display_score": "Score",
            "demographic_stratum": "Settlement",
            "macro_region": "Region",
            "expected_abatement_tco2e": "tCO₂e/yr",
            "population_total": "Population",
        }
    )
    st.dataframe(
        preview.round(2),
        hide_index=True,
        use_container_width=True,
        height=360,
    )


# -----------------------------------------------------------------------------
# Prioritisation / site inspector
# -----------------------------------------------------------------------------

with tab_priority:
    st.subheader("Decision shortlist")
    st.caption(
        f"{score_label}. Rankings below are re-numbered **within the selected policy scope**, so the first rural result is Rural Priority #1 rather than its national rank."
    )

    display_cols = [
        "scope_rank", "site_id", "display_score", "priority_score", "demographic_stratum",
        "macro_region", "off_grid_score_n", "solar_score_n", "community_impact_n",
        "access_ease_n", "expected_abatement_tco2e", "indicative_opex_saving_usd",
        "population_total",
    ]
    table = shortlist[[c for c in display_cols if c in shortlist.columns]].copy()
    table = table.rename(
        columns={
            "scope_rank": "Scope rank",
            "site_id": "Tile ID",
            "display_score": "Displayed score",
            "priority_score": "Pipeline score",
            "demographic_stratum": "Settlement",
            "macro_region": "Region",
            "off_grid_score_n": "Diesel pillar",
            "solar_score_n": "Solar pillar",
            "community_impact_n": "Community pillar",
            "access_ease_n": "Feasibility pillar",
            "expected_abatement_tco2e": "Indicative tCO₂e/yr",
            "indicative_opex_saving_usd": "Indicative OPEX saving USD/yr",
            "population_total": "Population associated",
        }
    )
    st.dataframe(table.round(3), hide_index=True, use_container_width=True, height=360)

    csv_bytes = table.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download current shortlist (CSV)",
        csv_bytes,
        file_name=f"jendela_{country_key}_{policy_scope.lower().replace(' ', '_')}_shortlist.csv",
        mime="text/csv",
    )

    st.divider()
    st.subheader("Inspect a candidate")

    labels = {
        str(r.site_id): (
            f"#{int(r.scope_rank)} · {r.site_id} · score {r.display_score:.1f} · "
            f"{r.demographic_stratum}"
        )
        for r in shortlist.itertuples()
    }
    selected_id = st.selectbox("Candidate", list(labels), format_func=labels.get)
    row = shortlist[shortlist["site_id"].astype(str).eq(selected_id)].iloc[0]

    left, right = st.columns([1.15, 1.0])

    with left:
        st.markdown(
            f"""
            <div class="site-card">
              <div class="muted">{policy_scope} priority</div>
              <h2 style="margin:.15rem 0 .25rem 0">#{int(row.scope_rank)} · Candidate location</h2>
              <div class="muted">Tile {row.site_id} · {row.demographic_stratum} · {row.macro_region}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("#### Why it ranks here")
        pillar_values = [
            ("Diesel / off-grid dependence", row.off_grid_score_n),
            ("Solar suitability", row.solar_score_n),
            ("Community impact", row.community_impact_n),
            ("Implementation feasibility", row.access_ease_n),
        ]
        for label, val in pillar_values:
            pct = float(np.clip(val, 0, 1))
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;align-items:center;"
                f"margin:.35rem 0 .1rem 0;'><span><strong>{label}</strong></span>"
                f"<span><strong>{pct * 100:.0f}/100</strong></span></div>",
                unsafe_allow_html=True,
            )
            st.progress(pct)

        reasons = site_reasons(row)
        if reasons:
            st.caption("Strongest pillar signals: " + " · ".join(reasons))

        model_enabled = bool(row.get("model_residual_enabled", True))
        if model_enabled and pd.notna(row.get("top_shap_driver", np.nan)):
            st.markdown("#### Speed-model explanation")
            shap_value = row.get("top_shap_value", np.nan)
            shap_text = f" ({shap_value:+,.0f} kbps contribution)" if np.isfinite(shap_value) else ""
            st.caption(
                f"Strongest SHAP driver of the Random Forest speed prediction: **{row.top_shap_driver}**{shap_text}. "
                "This explains the speed model, not the four-pillar priority score."
            )
        elif not model_enabled:
            st.markdown("#### Speed-model explanation")
            st.caption(
                "ML residual contribution is bypassed for this export because the speed model did not pass "
                "the spatial-validation guardrail. The deterministic ESG pillars remain active."
            )

    with right:
        k1, k2 = st.columns(2)
        k1.metric("Displayed score", f"{row.display_score:.1f}/100")
        k2.metric("Pipeline score", f"{row.priority_score:.1f}/100")

        k3, k4 = st.columns(2)
        k3.metric(
            "Model disagreement",
            fmt_number(row.get("model_disagreement_pct", np.nan), 1, "%"),
            help="Tree-to-tree Random Forest variation. This is not a calibrated confidence interval.",
        )
        k4.metric("Evidence", "Sufficient")

        st.markdown("#### Indicative impact")
        i1, i2 = st.columns(2)
        i1.metric("Abatement", fmt_number(row.get("expected_abatement_tco2e", np.nan), 1, " tCO₂e/yr"))
        i2.metric("OPEX saving", "$" + fmt_number(row.get("indicative_opex_saving_usd", np.nan), 0, "/yr"))

        i3, i4 = st.columns(2)
        i3.metric("Population associated", fmt_number(row.get("population_total", np.nan), 0))
        i4.metric("People / tCO₂e", fmt_number(row.get("people_connected_per_tonne_co2", np.nan), 1))

        st.caption(
            "Indicative abatement and OPEX scale continuously with the absolute inferred "
            "off-grid likelihood. The diesel pillar shown in the priority score is a relative "
            "percentile rank within the eligible candidate population."
        )

        st.markdown("#### Site context")
        context = pd.DataFrame(
            {
                "Measure": [
                    "Distance to mapped power infrastructure",
                    "Distance to mapped road",
                    "Distance to school / clinic",
                    "Measured download speed",
                    "Expected download speed",
                    "Ookla evidence",
                ],
                "Value": [
                    fmt_number(row.get("power_km", np.nan), 2, " km"),
                    fmt_number(row.get("road_km", np.nan), 2, " km"),
                    fmt_number(row.get("amenity_km", np.nan), 2, " km"),
                    fmt_number(row.get("download_kbps", np.nan), 0, " kbps"),
                    fmt_number(row.get("cv_predicted_speed", np.nan), 0, " kbps"),
                    f"{int(row.tests)} tests / {int(row.devices)} devices",
                ],
            }
        )
        st.dataframe(context, hide_index=True, use_container_width=True)

        warnings = []
        if bool(row.get("power_distance_missing", False)):
            warnings.append("Power-infrastructure distance was imputed; verify during field survey.")
        if bool(row.get("road_distance_missing", False)):
            warnings.append("Road distance was imputed; verify local accessibility.")
        if bool(row.get("amenity_distance_missing", False)):
            warnings.append("Amenity distance was imputed; verify local service context.")
        if warnings:
            for warning in warnings:
                st.warning(warning)
        else:
            st.success("No infrastructure-missing flags are raised for this candidate.")

        st.info(
            "Candidate only — inferred energy status and public-data proxies must be confirmed by the operator and a field survey before any investment decision."
        )


# -----------------------------------------------------------------------------
# Model & evidence
# -----------------------------------------------------------------------------

with tab_model:
    st.subheader("Model validation — where the ML signal is valid")

    has_explicit_model_status = False
    model_status = "Legacy export — status unavailable"
    if "model_validation_status" in full.columns:
        statuses = full["model_validation_status"].dropna().astype(str)
        if len(statuses):
            model_status = statuses.mode().iloc[0]
            has_explicit_model_status = True

    model_bypassed = has_explicit_model_status and model_status.startswith("Bypassed")

    if {"is_underserved_target", "download_kbps", "cv_predicted_speed"}.issubset(full.columns):
        cv_all = full[
            full["is_underserved_target"].fillna(False).astype(bool)
            & full["download_kbps"].notna()
            & full["cv_predicted_speed"].notna()
        ].copy()
        cv = cv_all[cv_all["cv_trusted"]].copy() if "cv_trusted" in cv_all.columns else cv_all
    else:
        cv_all = pd.DataFrame()
        cv = pd.DataFrame()

    v1, v2, v3, v4 = st.columns(4)

    if not model_bypassed and len(cv):
        if "spatial_cv_r2" in full.columns and full["spatial_cv_r2"].notna().any():
            overall_r2 = float(full["spatial_cv_r2"].dropna().iloc[0])
        else:
            overall_r2 = r_squared(cv["download_kbps"], cv["cv_predicted_speed"])
        v1.metric("Spatial-CV R²", f"{overall_r2:.3f}")
    elif model_bypassed:
        v1.metric("Spatial-CV R²", "Bypassed")
    else:
        v1.metric("Spatial-CV R²", "—")

    v2.metric("Validated tiles", f"{len(cv):,}")
    v3.metric(
        "Spatial blocks",
        f"{cv['spatial_block'].nunique():,}" if len(cv) and "spatial_block" in cv else "—",
    )
    v4.metric("Training scope", "Underserved")

    st.caption(
        "RF is trained on the verified underserved candidate population. The ML connectivity residual is "
        "allowed into Community Impact only when spatial validation passes the guardrail."
    )

    if not has_explicit_model_status and len(cv):
        st.info(
            "This is a legacy export without an explicit model-validation status. "
            "The displayed R² is recomputed from its saved out-of-block predictions."
        )

    if model_bypassed:
        observed_r2 = np.nan
        if "spatial_cv_r2" in full.columns and full["spatial_cv_r2"].notna().any():
            observed_r2 = float(full["spatial_cv_r2"].dropna().iloc[0])
        detail = (
            f" Observed diagnostic spatial-CV R² before bypass: {observed_r2:.3f}."
            if np.isfinite(observed_r2)
            else ""
        )
        st.warning(
            f"{model_status}. The ML residual is disabled in the priority score; deterministic ESG evidence remains active."
            + detail
        )
    elif len(cv):
        st.caption(
            "R² is reported across the screened underserved candidate population. It is not an accuracy percentage, "
            "and within-stratum performance is shown separately below."
        )

        rows = []
        if "demographic_stratum" in cv.columns:
            for stratum, group in cv.groupby("demographic_stratum"):
                rows.append(
                    {
                        "Stratum": stratum,
                        "Tiles": len(group),
                        "R²": r_squared(group["download_kbps"], group["cv_predicted_speed"]),
                        "Median absolute error (kbps)": np.median(
                            np.abs(group["download_kbps"] - group["cv_predicted_speed"])
                        ),
                    }
                )
        if rows:
            fairness = pd.DataFrame(rows)
            st.dataframe(fairness.round(3), hide_index=True, use_container_width=True)
            st.warning(
                "The pooled model can capture broad structure better than fine-grained variation within each settlement stratum. "
                "That is why the ML residual is only one bounded input inside the deterministic community pillar."
            )

        scatter = cv[["cv_predicted_speed", "download_kbps", "demographic_stratum"]].copy()
        scatter.columns = ["Predicted kbps", "Measured kbps", "Settlement"]
        st.scatter_chart(
            scatter.sample(min(1500, len(scatter)), random_state=42),
            x="Predicted kbps",
            y="Measured kbps",
            color="Settlement",
            height=360,
        )
    else:
        st.info("No validated CV population is available in this export.")

    st.divider()
    st.subheader("Evidence coverage & governance")
    tiers = full["confidence_tier"].value_counts(dropna=False).rename_axis("Confidence tier").reset_index(name="Tiles")
    st.dataframe(tiers, hide_index=True, use_container_width=True)

    e1, e2, e3, e4 = st.columns(4)
    e1.metric("All observed tiles", f"{len(full):,}")
    e2.metric("Ranked / approved", f"{int(full['rankable'].sum()):,}")
    e3.metric("Held back", f"{int((~full['rankable']).sum()):,}")
    e4.metric("Median Ookla tests", f"{full['tests'].median():.0f}" if "tests" in full else "—")

    st.caption(
        "Blank or masked areas mean insufficient measurement, not absence of mobile coverage. The dashboard keeps the governance distinction visible rather than converting missing evidence into zero."
    )

    if "demographic_stratum" in full.columns and "tests" in full.columns:
        st.bar_chart(
            full.groupby("demographic_stratum")["tests"].median(),
            y_label="Median Ookla tests",
            x_label="Settlement type",
        )

    st.divider()
    st.subheader("Ranking sensitivity")
    s1, s2 = st.columns(2)
    s1.metric(
        f"Top-{min(shortlist_n, len(shortlist))} overlap vs pipeline default",
        f"{strategy_overlap:.0f}%",
    )
    s2.metric("Current strategy", strategy.replace(" — pipeline default", ""))
    st.caption(
        "Alternative weight settings are stress tests. They never silently replace the production priority_score."
    )


# -----------------------------------------------------------------------------
# Methodology
# -----------------------------------------------------------------------------

with tab_method:
    st.subheader("Problem–decision contract")
    c1, c2 = st.columns(2)

    with c1:
        st.markdown(
            """
            **This tool may be used to**

            - Prioritise candidate locations for further assessment and field survey
            - Compare inferred diesel dependence, solar suitability, community impact and implementation feasibility
            - Highlight measured connectivity underperformance where the model has been validated
            - Produce indicative emissions / OPEX screening estimates from published benchmark assumptions, scaled continuously by inferred off-grid likelihood
            """
        )

    with c2:
        st.markdown(
            """
            **This tool may not be used to**

            - Assert that a specific tower is off-grid — grid status is inferred, not observed
            - Claim an area has no coverage because there is no public measurement
            - Treat an Ookla tile as a verified physical tower installation
            - Present the screening figures as a site-specific investment business case
            """
        )

    st.divider()
    st.subheader("How the ranking is built")
    formula = pd.DataFrame(
        {
            "Pillar": [
                "Diesel / off-grid dependence",
                "Solar suitability",
                "Community impact",
                "Implementation feasibility",
            ],
            "Pipeline weight": ["40%", "25%", "30%", "5%"],
            "Main evidence": [
                "50/50 mapped power distance + VIIRS darkness; VIIRS-only fallback if power mapping is missing",
                "Solar resource + canopy + slope + rainfall",
                "Population + essential services + bounded connectivity shortfall, diesel-gated",
                "Road access + terrain / slope / elevation",
            ],
        }
    )
    st.dataframe(formula, hide_index=True, use_container_width=True)

    st.markdown(
        """
        **Speed model:** Random Forest regression with 0.5° spatially blocked cross-validation.
        **SHAP:** explains the Random Forest speed prediction only; it does not explain the final four-pillar priority score.
        **Model disagreement:** standard deviation across Random Forest trees; useful as a stability signal, not a calibrated confidence interval.
        **ML circuit breaker:** if spatial validation fails, the connectivity residual is set to zero contribution while the deterministic ESG pillars remain active.
        """
    )

    st.divider()
    st.subheader("Geospatial engineering")
    st.markdown(
        """
        - OpenCellID records are consolidated into **candidate physical-site proxies** using Haversine DBSCAN.
        - A **50 m epsilon** is used as the conservative operating point from a radius sensitivity test: larger radii produced rapidly growing connected components, consistent with DBSCAN chaining.
        - Ookla tile → nearest candidate-site matching uses a Haversine BallTree.
        - Point → road / power / amenity distances use zone- and hemisphere-aware projected joins.
        """
    )

    cluster_test = pd.DataFrame(
        {
            "DBSCAN radius": ["25 m", "50 m", "75 m", "100 m", "500 m"],
            "Candidate clusters": [80413, 68792, 59502, 51940, 11503],
            "Singleton share": ["90.2%", "85.1%", "81.6%", "79.1%", "60.3%"],
            "Largest connected cluster": [110, 220, 848, 4208, 43393],
        }
    )
    st.dataframe(cluster_test, hide_index=True, use_container_width=True)
    st.caption(
        "50 m is treated as an empirically selected, tunable parameter — not an industry-standard guarantee of true tower identity."
    )

    st.divider()
    st.subheader("Known limitations")
    st.markdown(
        """
        - OpenCellID is crowdsourced; clusters are candidate site proxies, not an official tower registry.
        - Overture / open infrastructure mapping can be incomplete, so power distance remains a proxy for grid access.
        - The final rows are Ookla analysis tiles linked to candidate-site metadata; field confirmation is still required.
        - WorldPop is modelled population, not a community census.
        - Tree canopy uses the available tree-cover baseline and should not be presented as a current site survey.
        - The pooled spatial-CV R² is materially stronger than the within-stratum R² values; the model signal is therefore deliberately bounded inside the community pillar.
        """
    )

    st.info(
        "HOMER-style tools design one microgrid in detail. This dashboard answers the earlier question: which rural candidate locations are worth sending an engineer to first?"
    )
