"""Generate synthetic sites_scored.csv matching SCHEMA.md.

Lets the dashboard be built and demoed before Member 2's real output lands.
Numbers are internally consistent so the app looks and behaves like the real thing.

    python make_sample_data.py
"""

import numpy as np
import pandas as pd
from pathlib import Path

RNG = np.random.default_rng(42)
N = 900

DIESEL_KG_CO2_PER_L = 2.63
BASELINE_LITRES = 13_000.0
CAPEX_BASE_USD = 42_000.0
TARGET_MEDIAN_OPEX_USD = 21_000.0

REGIONS = {
    "Peninsular": dict(w=0.45, lat=(1.4, 6.6), lon=(99.7, 104.5),
                       states=["Perak", "Pahang", "Kelantan", "Terengganu", "Johor", "Kedah"]),
    "Sarawak":    dict(w=0.32, lat=(0.9, 5.0), lon=(109.6, 115.4),
                       states=["Sarawak"]),
    "Sabah":      dict(w=0.23, lat=(4.0, 7.4), lon=(115.2, 119.3),
                       states=["Sabah"]),
}


def build():
    region = RNG.choice(list(REGIONS), size=N, p=[v["w"] for v in REGIONS.values()])
    lat = np.empty(N)
    lon = np.empty(N)
    state = np.empty(N, dtype=object)

    for name, cfg in REGIONS.items():
        m = region == name
        lat[m] = RNG.uniform(*cfg["lat"], size=m.sum())
        lon[m] = RNG.uniform(*cfg["lon"], size=m.sum())
        state[m] = RNG.choice(cfg["states"], size=m.sum())

    remote = region != "Peninsular"

    dist_road = np.abs(RNG.normal(np.where(remote, 14, 5), np.where(remote, 9, 3)))
    dist_road = np.clip(dist_road, 0.3, 70)
    slope = np.clip(RNG.gamma(2.0, np.where(remote, 3.4, 1.7)), 0, 42)
    terrain_distance = dist_road * (1 + slope / 45)

    dist_grid = np.clip(np.abs(RNG.normal(np.where(remote, 11, 3), 7)), 0.1, 80)
    in_electrified = dist_grid < RNG.uniform(2, 6, size=N)
    grid_source = np.where(RNG.random(N) < np.where(remote, 0.35, 0.75), "osm", "predicted")

    pvout = np.clip(RNG.normal(3.9, 0.30, size=N), 2.9, 4.9)

    pv_norm = (pvout - pvout.min()) / (pvout.max() - pvout.min())
    displaced_fraction = 0.60 + 0.10 * pv_norm
    displaced_litres = BASELINE_LITRES * displaced_fraction

    # Calibrate transport coefficient k so the median site reproduces GSMA OPEX.
    base_fuel = 0.95
    target_delivered = TARGET_MEDIAN_OPEX_USD / BASELINE_LITRES
    k = (target_delivered - base_fuel) / np.median(terrain_distance)
    delivered_cost = base_fuel + k * terrain_distance

    annual_savings = displaced_litres * delivered_cost
    logistics_multiplier = np.clip(terrain_distance / 60, 0, 0.9)
    capex = CAPEX_BASE_USD * (1 + logistics_multiplier)
    payback = capex / annual_savings
    avoided = displaced_litres * DIESEL_KG_CO2_PER_L / 1000

    population = np.clip(
        RNG.lognormal(np.where(remote, 6.4, 7.6), 1.0, size=N), 20, 90_000
    ).astype(int)
    facilities = RNG.poisson(np.clip(population / 4000, 0.2, 9)).astype(int)

    has_tile = RNG.random(N) < np.where(remote, 0.42, 0.86)
    tests = np.where(has_tile, RNG.poisson(28, size=N), 0)
    devices = np.where(has_tile, np.maximum(1, (tests * RNG.uniform(0.2, 0.5, N)).astype(int)), 0)

    expected = 9_000 + 380 * np.log1p(population) - 90 * slope - 55 * dist_road
    observed = expected + RNG.normal(0, 5_200, size=N)
    observed = np.clip(observed, 400, None)
    obs = np.where(has_tile, observed, np.nan)
    pred = np.where(has_tile, expected, np.nan)
    residual = obs - pred

    strong = has_tile & (tests >= 15) & (devices >= 5) & (grid_source == "osm")
    thin = (~strong) & has_tile
    tier = np.where(strong, "strong", np.where(thin, "thin", "unknown"))

    carbon_per_1k = avoided / (capex / 1000)
    people_per_tonne = population / avoided

    df = pd.DataFrame(dict(
        site_id=[f"MY-{i:05d}" for i in range(N)],
        lat=lat.round(5), lon=lon.round(5), state=state, region=region,
        n_cells=RNG.integers(1, 9, size=N),
        operators=RNG.integers(1, 4, size=N),
        radio_mix=RNG.choice(["GSM", "GSM,UMTS", "GSM,LTE", "LTE", "LTE,NR"], size=N,
                             p=[0.30, 0.12, 0.34, 0.20, 0.04]),
        in_electrified=in_electrified,
        dist_to_grid_km=dist_grid.round(2),
        grid_line_source=grid_source,
        dist_to_road_km=dist_road.round(2),
        slope_deg=slope.round(1),
        terrain_distance_km=terrain_distance.round(2),
        pvout_kwh_kwp_day=pvout.round(3),
        displaced_fraction=displaced_fraction.round(3),
        displaced_litres=displaced_litres.round(0),
        avoided_tco2e=avoided.round(2),
        delivered_cost_per_litre_usd=delivered_cost.round(3),
        annual_savings_usd=annual_savings.round(0),
        capex_usd=capex.round(0),
        payback_years=payback.round(2),
        population_served=population,
        facilities_served=facilities,
        ookla_avg_d_kbps=np.round(obs, 0),
        ookla_tests=tests,
        ookla_devices=devices,
        predicted_d_kbps=np.round(pred, 0),
        residual_kbps=np.round(residual, 0),
        confidence_tier=tier,
        rank_carbon_per_1k=carbon_per_1k.round(4),
        rank_payback=payback.round(2),
        rank_people_per_tonne=people_per_tonne.round(1),
    ))

    # Off-grid candidates only — this is what the pipeline hands over.
    df = df[(~df.in_electrified) | (df.dist_to_grid_km > 3)].reset_index(drop=True)

    pct = lambda s: s.rank(pct=True) * 100
    df["rank_combined"] = (
        pct(df.rank_carbon_per_1k) + pct(-df.rank_payback) + pct(df.rank_people_per_tonne)
    ).div(3).round(1)

    df["top_factors"] = [
        f"pvout:{RNG.uniform(.05,.4):+.2f}|dist_road:{RNG.uniform(.05,.35):+.2f}"
        f"|population:{RNG.uniform(-.2,.3):+.2f}|slope:{RNG.uniform(-.25,.1):+.2f}"
        for _ in range(len(df))
    ]

    out = Path(__file__).parent / "data"
    out.mkdir(exist_ok=True)
    path = out / "sites_scored.csv"
    df.to_csv(path, index=False)
    print(f"wrote {path}  rows={len(df)}")
    print(df.confidence_tier.value_counts().to_string())
    print(f"total avoided tCO2e/yr : {df.avoided_tco2e.sum():,.0f}")
    print(f"median payback (years) : {df.payback_years.median():.2f}")
    print(f"median delivered $/L   : {df.delivered_cost_per_litre_usd.median():.2f}")


if __name__ == "__main__":
    build()
