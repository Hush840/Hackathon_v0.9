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

    # Matrices are stored with dictionary-encoded strings to keep the repo small. Read
    # them back as plain objects: a categorical dtype makes groupby carry unobserved
    # categories into the fairness table and the evidence chart, which produces empty
    # rows and NaN metrics on the smaller countries.
    for c in df.select_dtypes("category").columns:
        df[c] = df[c].astype(object)

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


def priority_legend_html(n_ranked=None, n_masked=None) -> str:
    """Legend for the decision map. Reads as evidence first, ranking second."""
    def cnt(n):
        return f" · {n:,}" if n else ""
    return f"""
    <div style="display:flex;flex-wrap:wrap;align-items:center;gap:20px;
                padding:8px 2px 4px 2px;font-size:12.5px;">
      <div style="display:flex;align-items:center;gap:8px;">
        <span style="opacity:.72;">Lower priority</span>
        <div style="width:190px;height:10px;border-radius:999px;
                    background:linear-gradient(90deg,rgb(240,175,65),rgb(55,220,160));"></div>
        <span style="opacity:.72;">Higher{cnt(n_ranked)} ranked</span>
      </div>
      <div style="display:flex;align-items:center;gap:6px;">
        <span style="width:9px;height:9px;display:inline-block;border-radius:50%;
                     background:rgb(168,172,170);opacity:.6;"></span>
        <span style="opacity:.72;">Thin evidence — masked{cnt(n_masked)}</span>
      </div>
      <div style="display:flex;align-items:center;gap:6px;">
        <span style="width:13px;height:13px;display:inline-block;
                     border:2px solid #222;border-radius:50%;"></span>
        <span style="opacity:.72;">Shortlist</span>
      </div>
    </div>
    <div style="opacity:.6;font-size:11.5px;padding:0 2px 10px 2px;">
      One dot is one Ookla analysis tile, roughly 600 m across, matched to the nearest
      candidate-site proxy — not a confirmed tower. Colour is relative to the current
      decision scope. Blank space inside the outline is <strong>absence of measurement,
      never absence of coverage</strong>.
    </div>
    """


# -----------------------------------------------------------------------------
# Indicative conversion sizing and local air quality
#
# Screening arithmetic only. Array sizing is what HOMER Pro and an engineer do properly
# once a site is confirmed; this exists so the shortlist carries an order-of-magnitude
# answer to "how big would it be", not so it replaces a design.
# -----------------------------------------------------------------------------

DIESEL_L_YR = 13_000        # GSMA, Tower Power Africa
GENSET_KWH_PER_L = 2.0      # conservative part-load genset efficiency
SOLAR_SHARE = 0.65          # GSMA solar-hybrid displacement
PERF_RATIO = 0.75           # tropical derate: heat, soiling, inverter, wiring
MODULE_EFF = 0.22           # module efficiency at STC
PANEL_W = 550               # a current utility-scale module

# Malaysian cost basis, back-solved from the team's single-site case:
#   RM98,000 installed PV + storage at 12.1 kWp  ->  RM8,100 / kWp
#   plus a fixed RM10,000 for logistics and civil works
# Diesel at RM5.27/L (unsubsidised, Sept 2026) x 13,000 L x 65% displaced
# = RM44,532 saved per year IF the site is confirmed off-grid.
MYR_PER_KWP = 8_100
MYR_MOBILISATION = 10_000
MYR_DIESEL_PER_L = 5.27


# g per kWh of diesel generation avoided. Regulatory bands, not site measurements.
POLLUTANT_G_PER_KWH = {
    "NOx": (4.0, 10.0),
    "PM2.5": (0.2, 0.5),
    "SO₂": (0.1, 0.4),
}


def conversion_sizing(row) -> dict | None:
    """Indicative solar array and avoided local pollutants for one candidate.

    Returns None where the site has no usable irradiance value, rather than inventing one.
    Array size is deliberately NOT scaled by off-grid likelihood: if the site turns out to
    be off-grid, that is the array it needs regardless of our prior confidence. Avoided
    pollutants ARE scaled, to stay consistent with the abatement and OPEX figures.
    """
    try:
        mj = float(row.get("solar_radiation_mj", float("nan")))
    except (TypeError, ValueError):
        return None
    if not np.isfinite(mj) or mj <= 0:
        return None

    ghi = mj / 3.6 / 30.4                       # MJ/m2/month -> kWh/m2/day
    yield_per_kwp = ghi * PERF_RATIO
    if yield_per_kwp <= 0:
        return None

    load_day = DIESEL_L_YR * GENSET_KWH_PER_L / 365.0
    kwp = load_day * SOLAR_SHARE / yield_per_kwp

    try:
        likelihood = float(np.clip(float(row.get("off_grid_likelihood", 0.0)), 0.0, 1.0))
    except (TypeError, ValueError):
        likelihood = 0.0
    kwh_avoided = DIESEL_L_YR * GENSET_KWH_PER_L * SOLAR_SHARE * likelihood

    capex = kwp * MYR_PER_KWP + MYR_MOBILISATION
    annual_saving = DIESEL_L_YR * MYR_DIESEL_PER_L * SOLAR_SHARE

    return {
        "ghi": ghi,
        "kwp": kwp,
        "capex_myr": capex,
        "saving_myr": annual_saving,
        "payback_yr": capex / annual_saving if annual_saving else float("nan"),
        "panels": int(np.ceil(kwp * 1000.0 / PANEL_W)),
        "panel_area": kwp / MODULE_EFF,
        "ground_area": kwp / MODULE_EFF * 1.4,
        "kwh_avoided": kwh_avoided,
        "pollutants": {
            name: (kwh_avoided * lo / 1000.0, kwh_avoided * hi / 1000.0)
            for name, (lo, hi) in POLLUTANT_G_PER_KWH.items()
        },
    }


def site_brief_html(row, country_label: str, scope_text: str) -> str:
    """One-page field brief for a single candidate. Opens and prints from a browser.

    This is the handoff artefact: what a survey engineer carries to the site, including
    space to record what they find. It is deliberately not a recommendation.
    """
    def n(v, dec=0, suf=""):
        try:
            v = float(v)
            return "—" if not np.isfinite(v) else f"{v:,.{dec}f}{suf}"
        except (TypeError, ValueError):
            return "—"

    pillars = [("Diesel / off-grid dependence", row.get("off_grid_score_n"), "40%"),
               ("Solar suitability", row.get("solar_score_n"), "25%"),
               ("Community impact", row.get("community_impact_n"), "30%"),
               ("Implementation feasibility", row.get("access_ease_n"), "5%")]
    bars = ""
    for lab, val, w in pillars:
        pc = float(np.clip(float(val) if pd.notna(val) else 0, 0, 1)) * 100
        bars += (
            f'<tr><td class="lab">{lab}<span class="w">weight {w}</span></td>'
            f'<td class="barcell"><div class="bar"><i style="width:{pc:.0f}%"></i></div></td>'
            f'<td class="num">{pc:.0f}<span class="o">/100</span></td></tr>'
        )

    flags = [t for c, t in (
        ("power_distance_missing", "Power-infrastructure distance imputed — verify on site"),
        ("road_distance_missing", "Road distance imputed — verify local accessibility"),
        ("amenity_distance_missing", "Amenity distance imputed — verify service context"),
    ) if bool(row.get(c, False))]
    flag_html = ("<ul class='flags'>" + "".join(f"<li>{f}</li>" for f in flags) + "</ul>"
                 if flags else "<p class='ok'>No infrastructure-missing flags raised.</p>")

    ctx = [("Distance to mapped power", n(row.get("power_km"), 2, " km")),
           ("Distance to mapped road", n(row.get("road_km"), 2, " km")),
           ("Distance to school / clinic", n(row.get("amenity_km"), 2, " km")),
           ("Measured download", n(row.get("download_kbps"), 0, " kbps")),
           ("Expected download", n(row.get("cv_predicted_speed"), 0, " kbps")),
           ("Ookla evidence", f"{n(row.get('tests'))} tests / {n(row.get('devices'))} devices"),
           ("Settlement type", str(row.get("demographic_stratum", "—"))),
           ("Region", str(row.get("macro_region", "—")))]
    ctx_html = "".join(f"<tr><td>{k}</td><td class='v'>{v}</td></tr>" for k, v in ctx)

    # Indicative sizing goes on the brief because it is what the surveyor is being sent to
    # sanity-check on the ground: is there anywhere to put roughly this much panel?
    sz = conversion_sizing(row)
    if sz is None:
        sizing_html = ""
    else:
        sizing_html = f"""
<h2>Indicative conversion sizing</h2>
<div class="grid">
  <div class="kpi"><b>{sz['kwp']:.1f} kWp</b><span>solar array to carry 65% of load</span></div>
  <div class="kpi"><b>{sz['panels']} panels</b><span>at {PANEL_W} W each</span></div>
  <div class="kpi"><b>{sz['ground_area']:.0f} m²</b><span>ground incl. spacing and access</span></div>
  <div class="kpi"><b>RM {sz['capex_myr']:,.0f}</b><span>indicative installed cost</span></div>
  <div class="kpi"><b>{sz['payback_yr']:.1f} yr</b><span>simple payback if confirmed off-grid</span></div>
</div>
<p class="sub">Sized from this site's irradiance of {sz['ghi']:.2f} kWh/m²/day at a
{PERF_RATIO:.2f} performance ratio. <strong>Confirm on site that a clear area of roughly this
size exists, and record any shading.</strong> Battery autonomy, load profile and generator
run-hours are for the engineering model, not this brief.</p>
"""

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Site brief — {row.get('site_id')}</title><style>
*{{box-sizing:border-box}}
body{{font:13px/1.5 -apple-system,Segoe UI,Inter,sans-serif;color:#13251d;margin:0;
     padding:34px 40px;background:#fff;max-width:840px}}
h1{{font-size:23px;margin:0 0 2px}} h2{{font-size:12px;letter-spacing:.09em;
     text-transform:uppercase;color:#5d6b64;margin:24px 0 8px;font-weight:700}}
.hdr{{border-bottom:2px solid #013d27;padding-bottom:12px;margin-bottom:6px}}
.sub{{color:#5d6b64;font-size:12.5px}}
.rank{{display:inline-block;background:#013d27;color:#e9ffe5;border-radius:6px;
     padding:3px 10px;font-weight:700;font-size:12px;margin-bottom:8px}}
.banner{{background:#fff6e5;border-left:4px solid #d08a1b;padding:10px 14px;
     margin:14px 0 4px;font-weight:600;font-size:12.5px}}
table{{width:100%;border-collapse:collapse;margin-top:4px}}
td{{padding:5px 0;border-bottom:1px solid #eceeed;vertical-align:middle}}
td.v,.num{{text-align:right;font-variant-numeric:tabular-nums}}
.lab{{width:44%}} .w{{display:block;color:#8a9691;font-size:10.5px;font-weight:400}}
.barcell{{width:40%;padding-right:14px}}
.bar{{background:#e9efec;border-radius:999px;height:9px;overflow:hidden}}
.bar i{{display:block;height:100%;background:#03c704}}
.num{{width:16%;font-weight:700}} .o{{color:#8a9691;font-weight:400;font-size:11px}}
.grid{{display:flex;gap:26px}} .grid>div{{flex:1}}
.kpi{{background:#f2f8f4;border-radius:8px;padding:11px 14px;margin-bottom:8px}}
.kpi b{{display:block;font-size:19px}} .kpi span{{color:#5d6b64;font-size:11px}}
.flags li{{color:#9a5b0c;margin-bottom:3px}} .ok{{color:#2c7a4b}}
.sign{{margin-top:22px;border:1px solid #d6dedb;border-radius:8px;padding:14px 16px}}
.sign .row{{display:flex;gap:26px;margin-top:14px}}
.sign .row div{{flex:1;border-bottom:1px solid #b9c5bf;padding-bottom:22px;font-size:11px;color:#8a9691}}
footer{{margin-top:26px;color:#8a9691;font-size:10.5px;border-top:1px solid #eceeed;padding-top:10px}}
@media print{{body{{padding:16px 20px}} .banner{{-webkit-print-color-adjust:exact}}}}
</style></head><body>
<div class="hdr">
  <div class="rank">{scope_text} · Priority #{int(row.get('scope_rank', 0))}</div>
  <h1>Site brief</h1>
  <div class="sub">Tile {row.get('site_id')} · {country_label} ·
    {n(row.get('latitude'), 4)}, {n(row.get('longitude'), 4)}</div>
</div>
<div class="banner">UNCONFIRMED SITE — VALIDATION REQUIRED. Off-grid status is inferred from open
data, not observed. This brief authorises a site survey, not an investment decision.</div>

<h2>Why this site ranks here</h2>
<table>{bars}</table>

<h2>Indicative screening impact</h2>
<div class="grid">
  <div class="kpi"><b>{n(row.get('expected_abatement_tco2e'), 1)} tCO₂e/yr</b>
    <span>avoided if converted to solar-hybrid</span></div>
  <div class="kpi"><b>${n(row.get('indicative_opex_saving_usd'))}</b>
    <span>indicative annual OPEX saving</span></div>
  <div class="kpi"><b>{n(row.get('population_total'))}</b>
    <span>population associated with this tile</span></div>
</div>
<p class="sub">Published-average estimates scaled by inferred off-grid likelihood. Not an
engineering design and not a business case.</p>

{sizing_html}

<h2>Site context</h2>
<table>{ctx_html}</table>

<h2>Data provenance warnings</h2>
{flag_html}

<div class="sign">
  <strong>Field survey record</strong>
  <div class="sub">To be completed on site.</div>
  <div class="row"><div>Grid connection confirmed? Y / N</div><div>Generator present? Y / N</div></div>
  <div class="row"><div>Access route / constraints</div><div>Shading or siting constraints</div></div>
  <div class="row"><div>Surveyor name</div><div>Date</div></div>
</div>
<footer>Powering the Last Mile · AGAIF 2026 · Generated from the JENDELA Phase 2 screening
matrix. Every figure is a screening estimate from open data and requires operator
confirmation.</footer>
</body></html>"""


def geo_subset(d: pd.DataFrame, geography: str, country_key: str) -> pd.DataFrame:
    """Geographic scope only — no policy filter. Used for the evidence backdrop."""
    if country_key != "malaysia" or "macro_region" not in d.columns:
        return d
    if geography == "East Malaysia (Sabah + Sarawak)":
        return d[d["macro_region"].eq("East Malaysia")]
    if geography == "Peninsular Malaysia":
        return d[d["macro_region"].eq("Peninsular Malaysia")]
    return d


REGION_LABELS = {
    "malaysia": [
        {"name": "PENINSULAR MALAYSIA", "lon": 102.15, "lat": 6.95},
        {"name": "SABAH", "lon": 117.10, "lat": 6.55},
        {"name": "SARAWAK", "lon": 112.40, "lat": 1.30},
    ]
}


def label_layer(country_key: str, geography: str):
    labels = REGION_LABELS.get(country_key, [])
    if not labels:
        return []
    if geography == "East Malaysia (Sabah + Sarawak)":
        labels = [l for l in labels if l["name"] != "PENINSULAR MALAYSIA"]
    elif geography == "Peninsular Malaysia":
        labels = [l for l in labels if l["name"] == "PENINSULAR MALAYSIA"]
    return [
        pdk.Layer(
            "TextLayer",
            data=labels,
            get_position=["lon", "lat"],
            get_text="name",
            get_size=11,
            get_color=[70, 88, 78, 190],
            get_alignment_baseline="'center'",
            character_set="auto",
            font_family="'Inter', sans-serif",
        )
    ]


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

# Off by default. On, the KPI row reports how each figure moved when you last changed scope —
# which makes a deliberate before/after comparison land, but is noise during ordinary reading.
show_deltas = st.sidebar.checkbox(
    "Show change vs previous scope",
    value=False,
    help="Adds a delta under each headline figure comparing it with the scope you had "
         "selected before this one. Useful when demonstrating the effect of a scope change.",
)

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
    st.warning("No evidence-qualified sites remain under the selected policy/geography scope.")
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
    # Deltas against the previously selected decision scope, so changing scope shows the
    # consequence rather than just a new number. This is the point of the tool.
    _scope_key = f"{country_key}|{policy_scope}|{geography}|{strategy}|{shortlist_n}"
    _cur = {
        "scope": float(len(scoped)),
        "short": float(len(shortlist)),
        "abate": float(shortlist["expected_abatement_tco2e"].sum()),
        "pop": float(shortlist["population_total"].sum()),
    }
    _h = st.session_state.setdefault("_kpi_hist", {"key": _scope_key, "vals": _cur, "base": None})
    if _h["key"] != _scope_key:
        _h["base"] = _h["vals"]
        _h["key"] = _scope_key
    _h["vals"] = _cur
    _base = _h["base"]

    def _delta(field, fmt="{:+,.0f}", pct=True):
        # Off by default. The deltas are a demo device — useful when you deliberately change
        # scope and want the consequence to land, noisy the rest of the time.
        if not show_deltas or not _base or field not in _base:
            return None
        diff = _cur[field] - _base[field]
        if abs(diff) < 0.5:
            return None
        out = fmt.format(diff)
        if pct and _base[field]:
            out += f"  ({diff / _base[field] * 100:+.0f}%)"
        return out

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Sites in scope", f"{len(scoped):,}", _delta("scope"))
    m2.metric("Shortlisted", f"{len(shortlist):,}", _delta("short", pct=False))
    m3.metric(
        "Indicative abatement",
        f"{_cur['abate']:,.0f} tCO₂e/yr",
        _delta("abate"),
        help="Published-average screening estimate, not site-specific engineering design."
             + (" Delta compares against your previous decision scope." if show_deltas else ""),
    )
    m4.metric(
        "Population associated",
        f"{_cur['pop']:,.0f}",
        _delta("pop"),
        help="Sum across shortlisted analysis tiles; not deduplicated subscriber counts.",
    )

    if show_deltas and _base:
        st.caption(
            "Deltas compare against your previous decision scope — change the policy scope "
            "or geography and the consequence is shown, not just the new total."
        )
    st.caption(
        "Screening only: a ranked candidate is a field-survey trigger, not proof that a tower is off-grid and not an investment decision."
    )

    # Full-width map: the geospatial decision view is the hero of the dashboard.
    #
    # Three evidence states are drawn underneath the ranking, because where we cannot
    # assess is as much a finding as where we rank. The background reflects the
    # geographic scope only — evidence coverage is a property of the place, not of the
    # policy filter sitting on top of it.
    map_data = scoped.copy()
    map_data["shade"] = map_data["display_score"].rank(pct=True)
    map_data["color"] = color_ramp(map_data["shade"])
    map_data["radius"] = 1200 + 5200 * (map_data["display_score"] / 100) ** 2

    backdrop = geo_subset(full, geography, country_key)
    if "confidence_tier" in backdrop.columns:
        masked = backdrop[backdrop["confidence_tier"].astype(str).str.startswith("Thin")]
    else:
        masked = backdrop[~backdrop["rankable"]]

    v = view_for(backdrop if len(backdrop) else map_data)
    layers = outline_layers(country_key)

    if len(masked):
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=masked[["longitude", "latitude"]],
                get_position=["longitude", "latitude"],
                get_fill_color=[168, 172, 170, 70],
                get_radius=2000, radius_min_pixels=1.4, radius_max_pixels=6,
            )
        )
    # Above-baseline tiles are deliberately not drawn. They are measured and already
    # performing, so they carry no decision. Leaving them off reduces the map to the only
    # two states that require an action: grey = go and measure, green = rank and survey.
    # The tier remains in the governance table on the Model & evidence tab.

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

    layers += label_layer(country_key, geography)

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

    st.markdown(
        priority_legend_html(len(scoped), len(masked)),
        unsafe_allow_html=True,
    )
    if len(masked):
        share = 100.0 * len(masked) / max(len(backdrop), 1)
        st.caption(
            f"**{share:.0f}% of tiles in view are masked for thin evidence.** They are drawn "
            "so the places we cannot assess read as gaps rather than as empty land."
        )

    st.subheader("Top sites")
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
        "scope_rank", "site_id", "latitude", "longitude", "display_score", "priority_score",
        "demographic_stratum", "macro_region", "off_grid_score_n", "solar_score_n",
        "community_impact_n", "access_ease_n", "expected_abatement_tco2e",
        "indicative_opex_saving_usd", "population_total",
    ]
    table = shortlist[[c for c in display_cols if c in shortlist.columns]].copy()
    table = table.rename(
        columns={
            "scope_rank": "Scope rank",
            "site_id": "Tile ID",
            "latitude": "Latitude",
            "longitude": "Longitude",
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
    # Coordinates are held at 6 dp and kept out of the 3-dp rounding applied to the scores.
    # At this latitude 3 dp is roughly 110 m and an analysis tile is about 600 m across, so
    # a rounded coordinate can point at the wrong tile — which defeats the purpose of
    # shipping it to a survey team.
    for _c in ("Latitude", "Longitude"):
        if _c in table.columns:
            table[_c] = table[_c].astype(float).round(6)

    shown = table.copy()
    _round = shown.select_dtypes("number").columns.difference(["Latitude", "Longitude"])
    shown[_round] = shown[_round].round(3)

    st.dataframe(
        shown,
        hide_index=True,
        use_container_width=True,
        height=360,
        column_config={
            "Latitude": st.column_config.NumberColumn(format="%.5f"),
            "Longitude": st.column_config.NumberColumn(format="%.5f"),
        },
    )
    st.caption(
        "Coordinates are the analysis-tile centroid — a search area of roughly 600 m, not a "
        "surveyed tower position."
    )

    csv_bytes = shown.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download current shortlist (CSV)",
        csv_bytes,
        file_name=f"jendela_{country_key}_{policy_scope.lower().replace(' ', '_')}_shortlist.csv",
        mime="text/csv",
    )

    st.divider()
    st.subheader("Inspect a site")

    labels = {
        str(r.site_id): (
            f"#{int(r.scope_rank)} · {r.site_id} · score {r.display_score:.1f} · "
            f"{r.demographic_stratum}"
        )
        for r in shortlist.itertuples()
    }
    pick_col, brief_col = st.columns([2.4, 1.0])
    with pick_col:
        selected_id = st.selectbox("Site", list(labels), format_func=labels.get)
    row = shortlist[shortlist["site_id"].astype(str).eq(selected_id)].iloc[0]
    with brief_col:
        st.write("")
        st.download_button(
            "Download field brief",
            site_brief_html(row, country_label, scope_text).encode("utf-8"),
            file_name=f"site_brief_{country_key}_{selected_id}.html",
            mime="text/html",
            use_container_width=True,
            help="One-page printable brief for the survey engineer, with space to record "
                 "what they find on site.",
        )

    left, right = st.columns([1.15, 1.0])

    with left:
        st.markdown(
            f"""
            <div class="site-card">
              <div class="muted">{policy_scope} priority</div>
              <h2 style="margin:.15rem 0 .25rem 0">#{int(row.scope_rank)} · Site</h2>
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

        _sz = conversion_sizing(row)
        if _sz is not None:
            st.markdown("#### Indicative conversion sizing")
            z1, z2 = st.columns(2)
            z1.metric(
                "Solar array",
                f"{_sz['kwp']:.1f} kWp",
                help="Sized from this tile's own irradiance to carry 65% of a 13,000 L/yr "
                     "diesel load. Not scaled by off-grid likelihood — if the site is "
                     "confirmed off-grid, this is the array it needs.",
            )
            z2.metric(
                "Panels / footprint",
                f"{_sz['panels']} · {_sz['panel_area']:.0f} m²",
                help=f"{PANEL_W} W modules at {MODULE_EFF:.0%} efficiency. Allow about "
                     f"{_sz['ground_area']:.0f} m² of ground including spacing and access.",
            )
            z3, z4 = st.columns(2)
            z3.metric(
                "Installed cost",
                f"RM {_sz['capex_myr']:,.0f}",
                help=f"RM{MYR_PER_KWP:,}/kWp for PV plus storage, at Malaysian commercial "
                     f"rates, plus RM{MYR_MOBILISATION:,} for logistics and civil works.",
            )
            z4.metric(
                "Simple payback",
                f"{_sz['payback_yr']:.1f} years",
                help=f"Against RM{_sz['saving_myr']:,.0f}/yr of diesel displaced — 13,000 L "
                     f"at RM{MYR_DIESEL_PER_L}/L, 65% replaced. Assumes the site is confirmed "
                     "off-grid. Excludes battery replacement.",
            )
            st.caption(
                f"Site irradiance {_sz['ghi']:.2f} kWh/m²/day · performance ratio "
                f"{PERF_RATIO:.2f} · diesel RM{MYR_DIESEL_PER_L}/L. Screening estimate — "
                "battery autonomy, load profile, generator run-hours and battery replacement "
                "are for the engineering model, not this tool."
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
            st.success("No infrastructure-missing flags are raised for this site.")

        st.info(
            "Unconfirmed site — inferred energy status and public-data proxies must be confirmed by the operator and a field survey before any investment decision."
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

        # Plain-language reading of the chart. A validation plot that only a statistician
        # can interpret is not evidence to a decision-maker — it is decoration.
        _worst = min(rows, key=lambda r: r["R²"]) if rows else None
        st.markdown("**How to read this chart**")
        st.markdown(
            "Each dot is one analysis tile. Left-to-right is the speed the model "
            "**predicted**; bottom-to-top is the speed Ookla actually **measured**. A flawless "
            "model would place every dot on a single straight diagonal.\n\n"
            "- **The three colours sit at different heights.** That is the model working: it "
            "correctly separates rural, peri-urban and urban.\n"
            "- **Each colour forms a round cloud, not a thin diagonal line.** That is the model's "
            "limit: inside any one settlement type, the prediction barely tracks reality."
        )
        _msg = (
            "**What we do about it.** The model is used only to place a tile in its broad "
            "settlement context, never to decide which of two similar tiles ranks higher. Its "
            "output enters the score as one bounded input inside the community pillar, and the "
            "other three pillars do not depend on it at all."
        )
        if _worst is not None:
            _msg += (
                f" Weakest stratum here is **{_worst['Stratum']}** at R² "
                f"{_worst['R²']:.3f} — effectively no better than predicting that stratum's "
                "average."
            )
        st.info(_msg)
    else:
        st.info("No validated CV population is available in this export.")




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

    # Weights follow the sidebar. The pipeline default is always shown alongside whatever
    # scenario is active, so a reader can see exactly what a stress test changed and by
    # how much — the production weights never disappear from view.
    _active = scenario_weights
    _is_default = strategy == "Balanced — pipeline default"
    _order = ["diesel", "solar", "community", "feasibility"]
    _tot = sum(_active.values()) or 1.0

    formula = pd.DataFrame(
        {
            "Pillar": [
                "Diesel / off-grid dependence",
                "Solar suitability",
                "Community impact",
                "Implementation feasibility",
            ],
            "Pipeline weight": [f"{PIPELINE_WEIGHTS[k]:.0%}" for k in _order],
            f"{'Active' if _is_default else strategy}": [
                f"{_active[k] / _tot:.0%}" for k in _order
            ],
            "Change": [
                "—" if abs(_active[k] / _tot - PIPELINE_WEIGHTS[k]) < 0.005
                else f"{(_active[k] / _tot - PIPELINE_WEIGHTS[k]) * 100:+.0f} pts"
                for k in _order
            ],
            "Main evidence": [
                "50/50 mapped power distance + VIIRS darkness; VIIRS-only fallback if power mapping is missing",
                "Solar resource + canopy + slope + rainfall",
                "Population + essential services + bounded connectivity shortfall, diesel-gated",
                "Road access + terrain / slope / elevation",
            ],
        }
    )
    st.dataframe(formula, hide_index=True, use_container_width=True)

    if _is_default:
        st.caption(
            "These are the production weights from `model_pipeline.py`. Change **Ranking "
            "strategy** in the sidebar to see how a different policy emphasis would move them "
            "— the pipeline column stays visible for comparison."
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

