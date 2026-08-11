"""Compare a fresh export against the current one before trusting it.

Usage:
    1. Download "PARQUET FOLDER NEW" from Drive.
    2. Put the files in  app/data/NEW/   (create the folder).
    3. Run:  .venv\\Scripts\\python.exe check_new_data.py

Checks the six things that were wrong in the last export. Anything marked FAIL
means the dashboard's correction layer still has to compensate for it.
"""
from pathlib import Path
import sys
import numpy as np
import pandas as pd

DATA = Path(__file__).parent / "data"
NEW = DATA / "NEW"

BASELINE_LITRES = 13_000.0
DIESEL_KG_CO2_PER_L = 2.63
SOLAR_HYBRID_REDUCTION = 0.65


def r2(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    return 1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum()


def verdict(ok):
    return "PASS" if ok else "FAIL"


def audit(name, d, old=None):
    print("=" * 72)
    print(f"{name}   {len(d):,} rows   {len(d.columns)} columns")
    if old is not None:
        gained = set(d.columns) - set(old.columns)
        lost = set(old.columns) - set(d.columns)
        print(f"  rows: {len(old):,} -> {len(d):,}   ({len(d) - len(old):+,})")
        if gained:
            print(f"  NEW COLUMNS:  {sorted(gained)}")
        if lost:
            print(f"  DROPPED COLUMNS:  {sorted(lost)}   <-- may break the dashboard")

    # 1. confidence tiers -- were all 'Sufficient Evidence' before
    if "confidence_tier" in d:
        tiers = d.confidence_tier.value_counts()
        print(f"\n  1. confidence tiers: {len(tiers)}  {verdict(len(tiers) > 1)}")
        for k, v in tiers.items():
            print(f"       {v:>7,}  {k}")
        if len(tiers) == 1:
            print("       still filtered upstream -- thin/no-data rows never reach us")

    # 2. abatement -- was a single constant 22.235 for every row
    if "indicative_abatement_tco2e_yr" in d:
        n = d.indicative_abatement_tco2e_yr.nunique()
        print(f"\n  2. distinct abatement values: {n}  {verdict(n > 1)}")
        print(f"       range {d.indicative_abatement_tco2e_yr.min():.2f} "
              f"to {d.indicative_abatement_tco2e_yr.max():.2f} tCO2e/yr")
        expected = BASELINE_LITRES * DIESEL_KG_CO2_PER_L / 1000 * SOLAR_HYBRID_REDUCTION
        print(f"       full-conversion reference = {expected:.2f}")

    # 3. off_grid_likelihood -- was unbounded, values above 1.0
    if "off_grid_likelihood" in d:
        lo, hi = d.off_grid_likelihood.min(), d.off_grid_likelihood.max()
        ok = lo >= -1e-9 and hi <= 1 + 1e-9
        print(f"\n  3. off_grid_likelihood range: {lo:.3f} to {hi:.3f}  {verdict(ok)}")
        if not ok:
            print(f"       {(d.off_grid_likelihood > 1).mean():.1%} of rows exceed 1.0")

    # 4. residual -- was clamped at a floor of 1.0, destroying the sign
    if "underperformance_residual" in d:
        at_floor = (d.underperformance_residual <= 1.0 + 1e-9).mean()
        print(f"\n  4. residual at the 1.0 floor: {at_floor:.1%}  {verdict(at_floor < 0.05)}")
        if {"download_kbps", "cv_predicted_speed"} <= set(d.columns):
            true_under = (d.download_kbps < d.cv_predicted_speed).mean()
            print(f"       true underperforming share (recomputed): {true_under:.1%}")

    # 5. priority score -- multiplicative scoring gave a spike near zero
    if "priority_score" in d:
        s = d.priority_score
        top_share = s.nlargest(max(1, len(s) // 100)).sum() / s.sum()
        ok = top_share < 0.20
        print(f"\n  5. top 1% of sites hold {top_share:.1%} of total score  {verdict(ok)}")
        print(f"       median {s.median():.4g}   max {s.max():.4g}   "
              f"max/median {s.max() / max(s.median(), 1e-12):,.0f}x")
        if not ok:
            print("       still multiplicative -- one factor is swamping the rest")

    # 6. model quality
    if {"download_kbps", "cv_predicted_speed"} <= set(d.columns):
        oob = r2(d.download_kbps, d.cv_predicted_speed)
        ins = (r2(d.download_kbps, d.predicted_download_kbps)
               if "predicted_download_kbps" in d else float("nan"))
        print(f"\n  6. R2  out-of-block {oob:.3f}   in-sample {ins:.3f}   "
              f"gap {ins - oob:+.3f}")
        if old is not None and {"download_kbps", "cv_predicted_speed"} <= set(old.columns):
            print(f"       was {r2(old.download_kbps, old.cv_predicted_speed):.3f} out-of-block")


def main():
    if not NEW.exists():
        sys.exit(f"Put the new files in {NEW} first.")
    files = sorted(NEW.rglob("jendela_phase2_esg_matrix_*.parquet"))
    if not files:
        sys.exit(f"No matrix parquet files found under {NEW}")
    for f in files:
        old_path = DATA / f.name
        old = pd.read_parquet(old_path) if old_path.exists() else None
        audit(f.name.replace("jendela_phase2_esg_matrix_", "").replace(".parquet", ""),
              pd.read_parquet(f), old)
    print("=" * 72)
    print("Any FAIL above means keep the dashboard's correction layer for that item,")
    print("and keep the Data integrity tab honest about it.")


if __name__ == "__main__":
    main()
