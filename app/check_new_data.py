"""Validate staged JENDELA parquet exports before promoting them to production.

Workflow:
    1. Put fresh exports in: data/NEW/
    2. Run: python check_new_data.py
    3. Promote only after the checks make sense.

Production app.py intentionally loads only top-level data/*.parquet files, so
staged files under data/NEW never silently replace approved dashboard data.
"""

from pathlib import Path
import sys
import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
NEW = DATA / "NEW"
APPROVED_TIER = "Sufficient Evidence - Ranked Screening Approved"

REQUIRED_FINAL_COLUMNS = {
    "site_id",
    "latitude",
    "longitude",
    "download_kbps",
    "tests",
    "devices",
    "demographic_stratum",
    "is_underserved_target",
    "confidence_tier",
    "cv_predicted_speed",
    "predicted_download_kbps",
    "prediction_uncertainty_kbps",
    "prediction_uncertainty_pct",
    "model_validation_status",
    "model_residual_enabled",
    "spatial_cv_r2",
    "off_grid_likelihood",
    "solar_viability",
    "community_impact",
    "off_grid_score_n",
    "solar_score_n",
    "community_impact_n",
    "access_ease_n",
    "priority_score",
    "field_survey_triggered",
    "national_rank",
}


def r2(y, p):
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    ok = np.isfinite(y) & np.isfinite(p)
    y, p = y[ok], p[ok]
    if len(y) < 2:
        return float("nan")
    denom = ((y - y.mean()) ** 2).sum()
    if denom == 0:
        return float("nan")
    return 1.0 - ((y - p) ** 2).sum() / denom


def verdict(ok):
    return "PASS" if ok else "FAIL"


def audit(name, d, old=None):
    print("=" * 78)
    print(f"{name.upper()}   {len(d):,} rows   {len(d.columns)} columns")

    if old is not None:
        gained = set(d.columns) - set(old.columns)
        lost = set(old.columns) - set(d.columns)
        print(f"rows: {len(old):,} -> {len(d):,} ({len(d) - len(old):+,})")
        if gained:
            print(f"NEW COLUMNS: {sorted(gained)}")
        if lost:
            print(f"DROPPED COLUMNS: {sorted(lost)}  <-- review before promotion")

    # 1) Final schema
    missing = sorted(REQUIRED_FINAL_COLUMNS - set(d.columns))
    print(f"\n1. final dashboard schema: {verdict(not missing)}")
    if missing:
        print("   missing:", missing)

    # 2) Governance tiers / approved ranking population
    if "confidence_tier" in d.columns:
        tiers = d["confidence_tier"].value_counts(dropna=False)
        approved = int(d["confidence_tier"].eq(APPROVED_TIER).sum())
        print(f"\n2. governance tiers: {len(tiers)} tier(s); approved={approved:,}")
        for k, v in tiers.items():
            print(f"   {v:>7,}  {k}")
        print("   " + verdict(approved > 0))

    # 3) Priority inputs bounded and populated only where expected
    if "off_grid_likelihood" in d.columns:
        s = d["off_grid_likelihood"].dropna()
        bounded = len(s) == 0 or ((s >= -1e-9) & (s <= 1 + 1e-9)).all()
        print(f"\n3. off_grid_likelihood bounded [0,1]: {verdict(bounded)}")
        if len(s):
            print(f"   range {s.min():.3f} -> {s.max():.3f}")

    native = ["off_grid_score_n", "solar_score_n", "community_impact_n", "access_ease_n"]
    if all(c in d.columns for c in native):
        ok = True
        for c in native:
            s = d[c].dropna()
            ok &= len(s) == 0 or ((s >= -1e-9) & (s <= 1 + 1e-9)).all()
        print(f"   native four-pillar scores bounded [0,1]: {verdict(ok)}")

    # 4) Missingness provenance survives export
    flags = ["power_distance_missing", "road_distance_missing", "amenity_distance_missing"]
    present_flags = [c for c in flags if c in d.columns]
    print(f"\n4. missing-distance provenance flags: {verdict(len(present_flags) == 3)}")
    if present_flags:
        for c in present_flags:
            print(f"   {c}: {int(d[c].fillna(False).sum()):,} flagged")

    # 5) Model validation / circuit-breaker status
    if {"download_kbps", "cv_predicted_speed", "is_underserved_target"} <= set(d.columns):
        status = "Legacy export — status unavailable"
        if "model_validation_status" in d.columns:
            statuses = d["model_validation_status"].dropna().astype(str)
            if len(statuses):
                status = statuses.mode().iloc[0]

        eval_mask = (
            d["is_underserved_target"].fillna(False).astype(bool)
            & d["download_kbps"].notna()
            & d["cv_predicted_speed"].notna()
        )
        if "model_residual_enabled" in d.columns:
            trusted_mask = eval_mask & d["model_residual_enabled"].fillna(False).astype(bool)
        else:
            trusted_mask = eval_mask

        eval_df = d[trusted_mask]
        print(f"\n5. model validation status: {status}")

        if status == "Validated" and len(eval_df) > 1:
            oob = r2(eval_df["download_kbps"], eval_df["cv_predicted_speed"])
            ins = (
                r2(eval_df["download_kbps"], eval_df["predicted_download_kbps"])
                if "predicted_download_kbps" in eval_df.columns
                else float("nan")
            )
            print(f"   validated design population: {len(eval_df):,} tiles")
            print(f"   spatial/out-of-block R²: {oob:.3f}")
            print(f"   production-model R²:     {ins:.3f}")

            if "spatial_cv_r2" in d.columns and d["spatial_cv_r2"].notna().any():
                stored_r2 = float(d["spatial_cv_r2"].dropna().iloc[0])
                print(f"   stored spatial_cv_r2:     {stored_r2:.3f}")
                print("   " + verdict(abs(stored_r2 - oob) < 1e-9))

            if "demographic_stratum" in eval_df.columns:
                print("   by stratum:")
                for stratum, g in eval_df.groupby("demographic_stratum"):
                    print(
                        f"     {stratum:<12} R²={r2(g.download_kbps, g.cv_predicted_speed): .3f}"
                        f"  n={len(g):,}"
                    )
        else:
            diagnostic_r2 = float("nan")
            if "spatial_cv_r2" in d.columns and d["spatial_cv_r2"].notna().any():
                diagnostic_r2 = float(d["spatial_cv_r2"].dropna().iloc[0])
            if np.isfinite(diagnostic_r2):
                print(f"   diagnostic spatial-CV R² before bypass: {diagnostic_r2:.3f}")
            enabled = (
                bool(d["model_residual_enabled"].fillna(False).any())
                if "model_residual_enabled" in d.columns
                else True
            )
            print(f"   ML residual enabled anywhere: {enabled}")
            print("   " + verdict(not enabled))

        if old is not None and {"download_kbps", "cv_predicted_speed", "is_underserved_target"} <= set(old.columns):
            old_mask = (
                old["is_underserved_target"].fillna(False).astype(bool)
                & old["download_kbps"].notna()
                & old["cv_predicted_speed"].notna()
            )
            if "model_residual_enabled" in old.columns:
                old_mask &= old["model_residual_enabled"].fillna(False).astype(bool)
            old_eval = old[old_mask]
            if len(old_eval) > 1:
                print(
                    f"   approved baseline R²:    "
                    f"{r2(old_eval.download_kbps, old_eval.cv_predicted_speed):.3f}"
                )

    # 6) Default priority distribution among approved candidates
    if {"priority_score", "confidence_tier"} <= set(d.columns):
        ranked = d[d["confidence_tier"].eq(APPROVED_TIER)].copy()
        s = ranked["priority_score"].dropna()
        print(f"\n6. approved priority distribution ({len(ranked):,} rows)")
        if len(s):
            print(
                f"   min={s.min():.2f}  median={s.median():.2f}  "
                f"p95={s.quantile(.95):.2f}  max={s.max():.2f}"
            )
            print(f"   zero-score approved rows: {(s == 0).mean():.1%}")

    # 7) Missing power data must fall back to VIIRS only, never to the imputed
    # 10 km distance. Missingness itself is not evidence of off-grid status.
    needed = {
        "power_distance_missing",
        "night_radiance_nw_cm2_sr",
        "off_grid_likelihood",
        "confidence_tier",
    }
    if needed <= set(d.columns):
        approved_rows = d[d["confidence_tier"].eq(APPROVED_TIER)].copy()
        pm = approved_rows["power_distance_missing"].fillna(False).astype(bool)
        missing_rows = approved_rows[pm]
        expected_darkness = (
            1.0 - approved_rows.loc[pm, "night_radiance_nw_cm2_sr"] / 10.0
        ).clip(0.0, 1.0)

        fallback_ok = True
        if len(missing_rows):
            fallback_ok = np.allclose(
                missing_rows["off_grid_likelihood"].astype(float),
                expected_darkness.astype(float),
                equal_nan=False,
            )

        top = d[d.get("national_rank", pd.Series(0, index=d.index)).between(1, 50)]
        top_missing = (
            int(top["power_distance_missing"].fillna(False).sum())
            if "power_distance_missing" in top.columns
            else 0
        )
        print(f"\n7. VIIRS-only fallback for missing power mapping: {verdict(fallback_ok)}")
        print(f"   approved rows using fallback: {len(missing_rows):,}")
        print(f"   top-50 rows using fallback:   {top_missing:,}")

    # 8) Continuous impact-scaling consistency
    impact_cols = {
        "off_grid_likelihood",
        "indicative_abatement_tco2e_yr",
        "indicative_opex_saving_usd",
    }
    if impact_cols <= set(d.columns):
        ranked = d[d.get("confidence_tier", pd.Series(index=d.index, dtype=object)).eq(APPROVED_TIER)].copy()
        if len(ranked):
            positive_proxy = ranked["off_grid_likelihood"].fillna(0) > 0
            zero_abatement = ranked["indicative_abatement_tco2e_yr"].fillna(0) <= 0
            zero_opex = ranked["indicative_opex_saving_usd"].fillna(0) <= 0
            inconsistent = int((positive_proxy & (zero_abatement | zero_opex)).sum())
            print(f"\n8. continuous impact scaling: {verdict(inconsistent == 0)}")
            print(f"   positive off-grid proxy but zero abatement/OPEX: {inconsistent}")

            expected_abatement = 34.2 * 0.65 * ranked["off_grid_likelihood"].clip(0, 1)
            expected_opex = 17000.0 * ranked["off_grid_likelihood"].clip(0, 1)
            abatement_match = np.allclose(
                ranked["indicative_abatement_tco2e_yr"].to_numpy(dtype=float),
                expected_abatement.to_numpy(dtype=float),
                equal_nan=True,
                rtol=1e-9,
                atol=1e-9,
            )
            opex_match = np.allclose(
                ranked["indicative_opex_saving_usd"].to_numpy(dtype=float),
                expected_opex.to_numpy(dtype=float),
                equal_nan=True,
                rtol=1e-9,
                atol=1e-9,
            )
            print(f"   abatement formula exact match: {verdict(abatement_match)}")
            print(f"   OPEX formula exact match:      {verdict(opex_match)}")

    # 9) Country-specific grid comparison sanity
    if "grid_equivalent_tco2e_yr" in d.columns:
        nonnull = int(d["grid_equivalent_tco2e_yr"].notna().sum())
        print(f"\n9. grid-equivalent comparison populated rows: {nonnull:,}")
        if name.lower() != "malaysia" and nonnull > 0:
            print("   FAIL: non-Malaysia export is carrying a Malaysia-specific grid comparison")
        else:
            print("   PASS")


def main():
    if not NEW.exists():
        sys.exit(f"Create {NEW} and place staged parquet exports there first.")

    files = sorted(NEW.glob("jendela_phase2_esg_matrix_*.parquet"))
    if not files:
        sys.exit(f"No staged matrix parquet files found directly under {NEW}")

    for f in files:
        old_path = DATA / f.name
        old = pd.read_parquet(old_path) if old_path.exists() else None
        name = f.stem.replace("jendela_phase2_esg_matrix_", "")
        audit(name, pd.read_parquet(f), old)

    print("=" * 78)
    print("Review every FAIL before promoting a staged file into the top-level data/ folder.")


if __name__ == "__main__":
    main()
