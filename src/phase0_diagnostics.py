#!/usr/bin/env python3
"""Phase 0 diagnostics: is the beacon→real-device gap a calibration problem
(threshold tuning) or a discrimination problem (needs real-device training)?

Run from project root:  .venv/bin/python src/phase0_diagnostics.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.metrics import roc_auc_score

from features import build_table, NOT_HEARD
from config import WINDOW_S

# ---- Device MACs identified from REAL_* windows in the capture session ----
# Redacted to example values; fill in from your own (gitignored) data/ session.
REAL_MACS = {
    "aa:bb:cc:00:00:01",  # AirPods (primary: clean gradient IN→OUT)
    "aa:bb:cc:00:00:02",  # AirPods (rotated RPA, IN_POCKET only)
    "aa:bb:cc:00:00:03",  # Phone FindMy (clean gradient -55→-61→-68)
    "aa:bb:cc:00:00:04",  # Phone Nearby Info (flat -72 everywhere — adversarial case)
}

BEACON_MAC = os.getenv("ROOMSENSE_BEACON_MAC", "00:00:00:00:00:00").lower()


def header(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ---- Load data ----

print("Loading data...")
raw = pd.read_csv("data/readings_raw.csv")
lab = pd.read_csv("data/labels.csv")
labeled = pd.read_csv("data/readings_labeled.csv")
obj = joblib.load("models/model.joblib")

window_s = obj.get("window_s", WINDOW_S)
model_cols = obj["columns"]
saved_model = obj["model"]

# Build beacon feature table
X_beacon, meta_beacon = build_table(labeled, window_s=window_s)
y_beacon = (meta_beacon["inout"] == "in").astype(int).values
groups_beacon = meta_beacon["position"].values

# Build real-device feature table from raw data
real_windows = lab[lab["position"].str.startswith("REAL_")]
real_rows = []
for _, w in real_windows.iterrows():
    mask = (
        raw["mac"].str.lower().isin(REAL_MACS)
        & (raw["ts"] >= w.start_ts)
        & (raw["ts"] <= w.end_ts)
    )
    sub = raw[mask].copy()
    if len(sub) > 0:
        sub["position"] = w.position
        sub["inout"] = w.inout
        real_rows.append(sub)

if not real_rows:
    print("ERROR: No real-device data found in REAL_* windows.")
    print("       Check that REAL_MACS are correct and REAL_* labels exist.")
    sys.exit(1)

real_df = pd.concat(real_rows)
print(f"Real-device rows: {len(real_df)} across {real_df['position'].nunique()} positions")

X_real, meta_real = build_table(real_df, window_s=window_s)
y_real = (meta_real["inout"] == "in").astype(int).values
groups_real = meta_real["position"].values

# Differential-only columns (TX-power-invariant)
DIFF_COLS = [c for c in X_beacon.columns
             if c.startswith(("delta__", "is_loudest__"))
             or c in ("rssi_spread", "n_heard", "argmax_stability", "phy_is_wifi")]

print(f"Beacon samples: {len(X_beacon)}  Real-device samples: {len(X_real)}")
print(f"All features: {X_beacon.shape[1]}  Differential-only: {len(DIFF_COLS)}")


# ============================================================
#  EXPERIMENT 1: Calibration vs Discrimination
# ============================================================

def exp1():
    header("EXP 1: CALIBRATION vs DISCRIMINATION")
    print("  Scoring real devices with the beacon-trained model...\n")

    X_aligned = X_real.reindex(columns=model_cols, fill_value=NOT_HEARD)
    probs = saved_model.predict_proba(X_aligned)[:, 1]

    # Distributions by inout
    for label, mask_val in [("INSIDE", 1), ("OUTSIDE", 0)]:
        m = y_real == mask_val
        p = probs[m]
        if len(p) == 0:
            print(f"  {label}: no samples")
            continue
        print(f"  {label} (n={len(p)}):")
        print(f"    mean={p.mean():.3f}  median={np.median(p):.3f}  "
              f"std={p.std():.3f}  min={p.min():.3f}  max={p.max():.3f}")

    # Per-position breakdown
    print(f"\n  Per-position mean probability:")
    for pos in sorted(set(groups_real)):
        m = groups_real == pos
        print(f"    {pos:25} mean={probs[m].mean():.3f}  n={m.sum()}")

    # Per-MAC breakdown
    print(f"\n  Per-MAC mean probability:")
    for mac in sorted(REAL_MACS):
        mac_mask = meta_real["mac"] == mac
        if mac_mask.sum() == 0:
            continue
        p = probs[mac_mask.values]
        positions = groups_real[mac_mask.values]
        in_p = p[positions == "REAL_IN_POCKET"] if any(positions == "REAL_IN_POCKET") else []
        out_p = p[np.isin(positions, ["REAL_OUT_WALL", "REAL_OUT_HALLWAY"])] if any(np.isin(positions, ["REAL_OUT_WALL", "REAL_OUT_HALLWAY"])) else []
        in_str = f"in_mean={np.mean(in_p):.3f}" if len(in_p) else "in=N/A"
        out_str = f"out_mean={np.mean(out_p):.3f}" if len(out_p) else "out=N/A"
        print(f"    {mac:25} n={mac_mask.sum():3}  {in_str}  {out_str}")

    # AUC
    if len(set(y_real)) < 2:
        print("\n  AUC: cannot compute (only one class in real data)")
        return 0.5
    auc = roc_auc_score(y_real, probs)
    print(f"\n  AUC (real devices, beacon model): {auc:.3f}")

    # Threshold sweep
    print(f"\n  Threshold sweep:")
    print(f"  {'thresh':>7} {'recall':>7} {'FPR':>7} {'F1':>7}")
    print(f"  {'-'*30}")
    best_f1, best_t = 0, 0.5
    for t in np.arange(0.05, 0.95, 0.05):
        pred = (probs >= t).astype(int)
        tp = ((pred == 1) & (y_real == 1)).sum()
        fp = ((pred == 1) & (y_real == 0)).sum()
        fn = ((pred == 0) & (y_real == 1)).sum()
        tn = ((pred == 0) & (y_real == 0)).sum()
        recall = tp / max(1, tp + fn)
        fpr = fp / max(1, fp + tn)
        prec = tp / max(1, tp + fp)
        f1 = 2 * prec * recall / max(1e-9, prec + recall)
        if f1 > best_f1:
            best_f1, best_t = f1, t
        print(f"  {t:7.2f} {recall:7.3f} {fpr:7.3f} {f1:7.3f}")

    print(f"\n  Best F1={best_f1:.3f} at threshold={best_t:.2f}")

    verdict = "CALIBRATION" if auc >= 0.65 else "DISCRIMINATION"
    print(f"\n  >>> EXP 1 VERDICT: {verdict} PROBLEM (AUC={auc:.3f})")
    if verdict == "CALIBRATION":
        print(f"      Model ranks correctly. Threshold tuning can fix this.")
    else:
        print(f"      Model cannot separate inside from outside for real devices.")
        print(f"      Threshold tuning alone will NOT fix this.")

    return auc


# ============================================================
#  EXPERIMENT 2: Differential-only Feature Transfer
# ============================================================

def exp2():
    header("EXP 2: DIFFERENTIAL-ONLY FEATURE TRANSFER")

    # Train two models on ALL beacon data (for transfer test)
    print("  Training full-feature model on beacon data...")
    model_full = RandomForestClassifier(n_estimators=300, random_state=0, n_jobs=-1)
    model_full.fit(X_beacon, y_beacon)

    print("  Training differential-only model on beacon data...")
    X_b_diff = X_beacon[DIFF_COLS]
    model_diff = RandomForestClassifier(n_estimators=300, random_state=0, n_jobs=-1)
    model_diff.fit(X_b_diff, y_beacon)

    # Score real devices with both
    X_r_full = X_real.reindex(columns=X_beacon.columns, fill_value=NOT_HEARD)
    X_r_diff = X_real[DIFF_COLS] if all(c in X_real.columns for c in DIFF_COLS) else \
               X_real.reindex(columns=DIFF_COLS, fill_value=0)

    prob_full = model_full.predict_proba(X_r_full)[:, 1]
    prob_diff = model_diff.predict_proba(X_r_diff)[:, 1]

    print(f"\n  Real-device scoring (n={len(y_real)}):")
    for label, probs in [("Full features", prob_full), ("Diff-only", prob_diff)]:
        in_m = y_real == 1
        out_m = y_real == 0
        in_mean = probs[in_m].mean() if in_m.sum() else 0
        out_mean = probs[out_m].mean() if out_m.sum() else 0
        print(f"\n  {label}:")
        print(f"    Inside  mean={in_mean:.3f}  median={np.median(probs[in_m]):.3f}")
        print(f"    Outside mean={out_mean:.3f}  median={np.median(probs[out_m]):.3f}")
        print(f"    Gap (in - out) = {in_mean - out_mean:+.3f}")

    # AUC comparison
    auc_full = roc_auc_score(y_real, prob_full) if len(set(y_real)) >= 2 else 0.5
    auc_diff = roc_auc_score(y_real, prob_diff) if len(set(y_real)) >= 2 else 0.5

    print(f"\n  Transfer AUC:")
    print(f"    Full features:    {auc_full:.3f}")
    print(f"    Differential-only: {auc_diff:.3f}")
    print(f"    Delta:            {auc_diff - auc_full:+.3f}")

    # LOPO on beacon data for both (in-domain performance)
    print(f"\n  Beacon LOPO (in-domain, for reference):")
    for label, X_sub in [("Full", X_beacon), ("Diff-only", X_b_diff)]:
        logo = LeaveOneGroupOut()
        oof = np.zeros(len(y_beacon))
        for tr, te in logo.split(X_sub, y_beacon, groups_beacon):
            clf = RandomForestClassifier(n_estimators=300, random_state=0, n_jobs=-1)
            clf.fit(X_sub.iloc[tr], y_beacon[tr])
            oof[te] = clf.predict_proba(X_sub.iloc[te])[:, 1]

        wall_mask = np.array(["SHARED_WALL" in str(g) for g in groups_beacon])
        pocket_mask = (groups_beacon == "IN_POCKET") & (y_beacon == 1)
        # Find best threshold with pocket recall >= 0.95
        ok = [t for t in np.linspace(0.05, 0.95, 19)
              if pocket_mask.sum() == 0 or ((oof >= t).astype(int))[pocket_mask].mean() >= 0.95]
        thresh = max(ok) if ok else 0.5
        pred = (oof >= thresh).astype(int)
        acc = (pred == y_beacon).mean()
        wall_fp = pred[wall_mask].mean() if wall_mask.sum() else None
        pocket_rec = pred[pocket_mask].mean() if pocket_mask.sum() else None

        wall_str = f"{wall_fp:.3f}" if wall_fp is not None else "N/A"
        pocket_str = f"{pocket_rec:.3f}" if pocket_rec is not None else "N/A"
        print(f"    {label:10} acc={acc:.3f}  wall_FP={wall_str}  pocket_rec={pocket_str}  thresh={thresh:.2f}")

    # Feature importance comparison
    print(f"\n  Top 5 features (full model):")
    imp = sorted(zip(model_full.feature_importances_, X_beacon.columns), reverse=True)[:5]
    for v, c in imp:
        tag = " [DIFF]" if c in DIFF_COLS else " [ABS]"
        print(f"    {c:30} {v:.3f}{tag}")

    winner = "DIFFERENTIAL" if auc_diff > auc_full else "FULL"
    print(f"\n  >>> EXP 2 VERDICT: {winner} features transfer better")
    print(f"      Full AUC={auc_full:.3f}  Diff AUC={auc_diff:.3f}")
    if auc_diff > auc_full:
        print(f"      Differential features (TX-power-invariant) help transfer.")
    else:
        print(f"      Differential features do NOT improve transfer.")
        print(f"      The domain shift may include geometry, not just TX power.")

    return auc_full, auc_diff


# ============================================================
#  EXPERIMENT 3: argmax_stability Verification
# ============================================================

def exp3():
    header("EXP 3: argmax_stability VERIFICATION")

    col = "argmax_stability"
    if col not in X_beacon.columns:
        print("  argmax_stability NOT in feature set — not implemented!")
        return

    print("  Beacon data (per-position):")
    for pos in sorted(set(groups_beacon)):
        m = groups_beacon == pos
        vals = X_beacon[col].values[m]
        io = "in " if "IN_" in pos or pos.startswith("IN") else "out"
        print(f"    {pos:25} {io}  mean={vals.mean():.3f}  std={vals.std():.3f}  n={m.sum()}")

    beacon_in = X_beacon[col].values[y_beacon == 1]
    beacon_out = X_beacon[col].values[y_beacon == 0]
    print(f"\n  Beacon summary: inside mean={beacon_in.mean():.3f}  outside mean={beacon_out.mean():.3f}  gap={beacon_in.mean() - beacon_out.mean():.3f}")

    if col in X_real.columns and len(X_real) > 0:
        print(f"\n  Real-device data (per-position):")
        for pos in sorted(set(groups_real)):
            m = groups_real == pos
            vals = X_real[col].values[m]
            io = "in " if "IN" in pos else "out"
            print(f"    {pos:25} {io}  mean={vals.mean():.3f}  std={vals.std():.3f}  n={m.sum()}")

        real_in = X_real[col].values[y_real == 1]
        real_out = X_real[col].values[y_real == 0]
        print(f"\n  Real summary: inside mean={real_in.mean():.3f}  outside mean={real_out.mean():.3f}  gap={real_in.mean() - real_out.mean():.3f}")

    # Feature importance rank
    importances = saved_model.feature_importances_
    col_idx = list(model_cols).index(col) if col in model_cols else None
    if col_idx is not None:
        rank = sorted(range(len(importances)), key=lambda i: importances[i], reverse=True)
        pos_in_rank = rank.index(col_idx) + 1
        print(f"\n  Feature importance: rank #{pos_in_rank}/{len(importances)}  "
              f"importance={importances[col_idx]:.4f}")

    beacon_gap = abs(beacon_in.mean() - beacon_out.mean())
    if beacon_gap < 0.05:
        print(f"\n  >>> EXP 3 VERDICT: DEGENERATE — no in/out separation ({beacon_gap:.3f})")
    elif len(X_real) > 0 and abs(real_in.mean() - real_out.mean()) < 0.05:
        print(f"\n  >>> EXP 3 VERDICT: DOMAIN SHIFTED — separates beacon ({beacon_gap:.3f}) but not real devices")
    else:
        print(f"\n  >>> EXP 3 VERDICT: USEFUL — separates in/out in both domains")


# ============================================================
#  EXPERIMENT 4: n_heard Distribution Shift
# ============================================================

def exp4():
    header("EXP 4: n_heard DISTRIBUTION SHIFT")

    col = "n_heard"
    if col not in X_beacon.columns:
        print("  n_heard NOT in feature set!")
        return

    print("  Beacon n_heard distribution:")
    beacon_vals = X_beacon[col].values
    for v in sorted(set(beacon_vals.astype(int))):
        n = (beacon_vals == v).sum()
        pct = n / len(beacon_vals) * 100
        print(f"    n_heard={int(v)}: {n:5} ({pct:5.1f}%)")

    if col in X_real.columns and len(X_real) > 0:
        print(f"\n  Real-device n_heard distribution:")
        real_vals = X_real[col].values
        for v in sorted(set(real_vals.astype(int))):
            n = (real_vals == v).sum()
            pct = n / len(real_vals) * 100
            print(f"    n_heard={int(v)}: {n:5} ({pct:5.1f}%)")

        # Per-MAC breakdown
        print(f"\n  Per-MAC n_heard (mean):")
        for mac in sorted(REAL_MACS):
            mac_mask = meta_real["mac"] == mac
            if mac_mask.sum() == 0:
                continue
            vals = X_real[col].values[mac_mask.values]
            print(f"    {mac:25} mean={vals.mean():.2f}  n={mac_mask.sum()}")

        beacon_low = (beacon_vals < 3).mean() * 100
        real_low = (real_vals < 3).mean() * 100
        print(f"\n  Fraction with n_heard < 3:")
        print(f"    Beacon:  {beacon_low:.1f}%")
        print(f"    Real:    {real_low:.1f}%")

        shift = abs(real_low - beacon_low)
        impact = "MAJOR" if shift >= 20 else ("MODERATE" if shift >= 10 else "MINOR")
        print(f"\n  >>> EXP 4 VERDICT: Shift {'CONFIRMED' if shift > 5 else 'MINIMAL'} "
              f"({real_low:.0f}% vs {beacon_low:.0f}% low-heard). Impact: {impact}")
    else:
        print("  No real-device data for n_heard comparison.")


# ============================================================
#  FINAL VERDICT
# ============================================================

def final_verdict(auc_full, auc_diff):
    header("PHASE 0 FINAL VERDICT")

    print(f"  Beacon model AUC on real devices (full features):    {auc_full:.3f}")
    print(f"  Beacon model AUC on real devices (diff-only):        {auc_diff:.3f}")
    print()

    if auc_full >= 0.65:
        print("  VERDICT: CALIBRATION PROBLEM")
        print("  The beacon model ranks real devices correctly.")
        print("  Fix: threshold tuning + optional small real-device calibration set.")
        print("  You are ~1 day from a working result.")
    elif auc_diff >= 0.65:
        print("  VERDICT: PARTIAL DISCRIMINATION PROBLEM")
        print("  Full-feature model fails, but differential features transfer.")
        print("  Fix: retrain with differential-only features + threshold on real devices.")
        print("  Collect 30-60 min co-located real-device walk to close the gap.")
        print("  You are ~3-5 days from a working result.")
    else:
        print("  VERDICT: DISCRIMINATION PROBLEM")
        print("  Neither feature set transfers from beacon to real devices.")
        print("  Root cause: beacon's RSSI profile is too different from real devices.")
        print()
        print("  REQUIRED ACTIONS:")
        print("  1. Collect a co-located real-device walk (Phase 2 in the build plan)")
        print("     - Carry phone + AirPods through all positions")
        print("     - Record their MACs at each position for filtering")
        print("     - Train on beacon + carried real devices (MAC-filtered)")
        print("  2. Try the RSSI normalization ladder:")
        print("     - DIFF (current) → SSD → HLF/hyperbolic → rank-normalized")
        print("  3. Consider increasing WINDOW_S from 2s to 4-5s for stability")
        print()
        print("  You are ~1-2 weeks from a working result.")


# ---- Main ----

if __name__ == "__main__":
    print("\n" + "#" * 60)
    print("  ROOMSENSE — PHASE 0 DIAGNOSTICS")
    print("  Calibration vs Discrimination Analysis")
    print("#" * 60)

    auc1 = exp1()
    auc_full, auc_diff = exp2()
    exp3()
    exp4()
    final_verdict(auc_full, auc_diff)
    print()
