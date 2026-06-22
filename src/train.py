#!/usr/bin/env python3
"""v3 train: LOPO-only, single-sensor vs full-array comparison, guardrails.
LOPO = Leave-One-Position-Out (never a random split — that leaks position).
The two product numbers: adjacent-wall FP rate and in-pocket recall.

v3: uses aggregated features (20s windows, co-hearing alignment, transfer features).
Falls back to legacy build_table() if --legacy flag is passed."""
import json, os, sys, time
import joblib, numpy as np, pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.metrics import confusion_matrix

sys.path.insert(0, os.path.dirname(__file__))
from config import WINDOW_S, AGG_WINDOW_S, AGG_OVERLAP
from features import build_table, NOT_HEARD
from aggregation import build_aggregated_table
from env_features import build_env_table

HARD_OUT = "OUT_SHARED_WALL"
POCKET = "IN_POCKET"
TARGET_POCKET_RECALL = 0.95

USE_LEGACY = "--legacy" in sys.argv
USE_ENV = "--env" in sys.argv

# ---- load ----
data_file = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "data/readings_labeled.csv"
df = pd.read_csv(data_file)

# Load radar data if available
radar_readings = None
radar_file = "data/radar_labeled.csv"
for arg in sys.argv:
    if arg.startswith("--radar="):
        radar_file = arg.split("=", 1)[1]
if os.path.exists(radar_file):
    rdf = pd.read_csv(radar_file)
    # Convert radar CSV rows to list-of-dicts format for radar_features
    radar_readings = []
    for _, row in rdf.iterrows():
        targets = []
        for i in range(3):
            d = int(row.get(f"dist{i}", 0) or 0)
            if d > 0:
                targets.append({
                    "x": int(row.get(f"x{i}", 0) or 0),
                    "y": int(row.get(f"y{i}", 0) or 0),
                    "spd": int(row.get(f"spd{i}", 0) or 0),
                    "dist": d,
                })
        radar_readings.append({
            "source": row["source"],
            "ts": float(row["ts"]),
            "n_targets": int(row.get("n_targets", len(targets))),
            "targets": targets,
        })
    print(f"Loaded {len(radar_readings)} radar frames from {radar_file}")
else:
    if USE_ENV:
        print(f"No radar data at {radar_file} — training BLE-only env model")

has_radar = radar_readings is not None and len(radar_readings) > 0

if USE_LEGACY:
    print("[LEGACY MODE] Using 2s windows with build_table()")
    X, meta = build_table(df, window_s=WINDOW_S)
    window_label = f"{WINDOW_S}s (legacy)"
elif USE_ENV:
    print(f"[v3 env] Using {AGG_WINDOW_S}s environment-level windows, {AGG_OVERLAP:.0%} overlap")
    if has_radar:
        print(f"  + radar fusion ({len(radar_readings)} frames)")
    X, meta = build_env_table(df, A=AGG_WINDOW_S, overlap=AGG_OVERLAP,
                              radar_readings=radar_readings)
    window_label = f"{AGG_WINDOW_S}s env" + (" + radar" if has_radar else "")
else:
    print(f"[v3] Using {AGG_WINDOW_S}s aggregation windows, {AGG_OVERLAP:.0%} overlap")
    X, meta = build_aggregated_table(df, A=AGG_WINDOW_S, overlap=AGG_OVERLAP)
    window_label = f"{AGG_WINDOW_S}s agg, {AGG_OVERLAP:.0%} overlap"

y = (meta["inout"] == "in").astype(int).values
groups = meta["position"].values

print(f"Samples: {len(X)}  features: {X.shape[1]}  inside: {y.sum()}  outside: {(y==0).sum()}")

# ---- guardrails ----
src_counts = df.groupby("source").size()
print(f"\nPer-source row counts:\n{src_counts}")
max_src = src_counts.max()
for src, cnt in src_counts.items():
    if cnt < 0.2 * max_src:
        print(f"WARNING: {src} has only {cnt} rows ({cnt/max_src*100:.0f}% of max) — sensor may be dead")

wall_positions = [p for p in set(groups) if HARD_OUT in p]
if len(wall_positions) < 2:
    print(f"WARNING: only {len(wall_positions)} OUT_SHARED_WALL positions — need several for honest eval")

pocket_mask = (groups == POCKET) & (y == 1)
if pocket_mask.sum() == 0:
    print("WARNING: no IN_POCKET inside samples — threshold will default to 0.5")


def single_sensor_cols(cols, keep="esp_c1"):
    """Keep only columns for one sensor — drops all multi-sensor features."""
    multi_feats = {"rssi_spread", "rssi_vec_max", "argmax_stability", "n_heard",
                   "anisotropy", "argmax_coverage", "ref_delta"}
    out = []
    for c in cols:
        if c.startswith(("delta__", "is_loudest__", "rssi_normed__")):
            continue
        if c in multi_feats:
            continue
        if "__esp_" in c and f"__{keep}" not in c:
            continue
        out.append(c)
    return out


def run_eval(X_sub, label):
    """Run LOPO eval, return metrics dict."""
    logo = LeaveOneGroupOut()
    oof_prob = np.zeros(len(y))
    for tr, te in logo.split(X_sub, y, groups):
        clf = RandomForestClassifier(n_estimators=300, random_state=0, n_jobs=-1)
        clf.fit(X_sub.iloc[tr], y[tr])
        oof_prob[te] = clf.predict_proba(X_sub.iloc[te])[:, 1]

    # Pick highest threshold with pocket recall >= target
    if pocket_mask.sum() > 0:
        ok = [t for t in np.linspace(0.05, 0.95, 19)
              if ((oof_prob >= t).astype(int))[pocket_mask].mean() >= TARGET_POCKET_RECALL]
        thresh = max(ok) if ok else 0.5
    else:
        thresh = 0.5

    pred = (oof_prob >= thresh).astype(int)
    acc = float((pred == y).mean())

    # Adjacent-wall FP
    wall_mask = np.array([HARD_OUT in str(g) for g in groups])
    wall_fp = float(pred[wall_mask].mean()) if wall_mask.sum() else None

    # Pocket recall
    pocket_rec = float(pred[pocket_mask].mean()) if pocket_mask.sum() else None

    print(f"\n{'='*50}")
    print(f"  {label}")
    print(f"{'='*50}")
    print(f"  LOPO accuracy:        {acc:.3f}")
    print(f"  Threshold:            {thresh:.2f}")
    if wall_fp is not None:
        print(f"  Adjacent-wall FP:     {wall_fp:.3f}")
    if pocket_rec is not None:
        print(f"  IN_POCKET recall:     {pocket_rec:.3f}")

    print(f"\n  Confusion matrix (0=out, 1=in):")
    print(f"  {confusion_matrix(y, pred, labels=[0,1])}")

    print(f"\n  Per-position accuracy:")
    per_pos = {}
    for pos in sorted(set(groups)):
        m = groups == pos
        pacc = float((pred[m] == y[m]).mean())
        per_pos[pos] = pacc
        print(f"    {pos:25} acc={pacc:.3f}  (n={m.sum()})")

    return {
        "label": label, "accuracy": acc, "threshold": thresh,
        "adjacent_wall_fp": wall_fp, "pocket_recall": pocket_rec,
        "per_position": per_pos, "n_features": X_sub.shape[1],
    }


# ---- Run both evaluations ----
print("\n" + "#" * 60)
print("  SINGLE-SENSOR vs FULL-ARRAY COMPARISON (LOPO)")
print("#" * 60)

single_cols = single_sensor_cols(X.columns)
X_single = X[single_cols]
single_metrics = run_eval(X_single, "SINGLE SENSOR (esp_c1 only)")

full_metrics = run_eval(X, "FULL ARRAY")

# ---- The delta (the whole point) ----
print(f"\n{'='*50}")
print(f"  THE DELTA")
print(f"{'='*50}")
print(f"  LOPO accuracy:     single={single_metrics['accuracy']:.3f}  "
      f"array={full_metrics['accuracy']:.3f}  "
      f"delta={full_metrics['accuracy']-single_metrics['accuracy']:+.3f}")
if single_metrics["adjacent_wall_fp"] is not None and full_metrics["adjacent_wall_fp"] is not None:
    print(f"  Adj-wall FP:       single={single_metrics['adjacent_wall_fp']:.3f}  "
          f"array={full_metrics['adjacent_wall_fp']:.3f}  "
          f"delta={full_metrics['adjacent_wall_fp']-single_metrics['adjacent_wall_fp']:+.3f}")
if single_metrics["pocket_recall"] is not None and full_metrics["pocket_recall"] is not None:
    print(f"  Pocket recall:     single={single_metrics['pocket_recall']:.3f}  "
          f"array={full_metrics['pocket_recall']:.3f}  "
          f"delta={full_metrics['pocket_recall']-single_metrics['pocket_recall']:+.3f}")

# ---- Train final model (full array) and save ----
final = RandomForestClassifier(n_estimators=300, random_state=0, n_jobs=-1).fit(X, y)
os.makedirs("models", exist_ok=True)
feature_type = "legacy" if USE_LEGACY else ("environment" if USE_ENV else "per_device")
if USE_ENV and has_radar:
    feature_type = "environment_fused"
joblib.dump({
    "model": final, "columns": list(X.columns),
    "window_s": AGG_WINDOW_S if not USE_LEGACY else WINDOW_S,
    "threshold": float(full_metrics["threshold"]),
    "version": "v3" if not USE_LEGACY else "v2",
    "feature_type": feature_type,
    "has_radar": has_radar,
}, "models/model.joblib")
print("\nSaved models/model.joblib")

# Top features
imp = sorted(zip(final.feature_importances_, X.columns), reverse=True)[:8]
print("Top features:", [f"{c} ({v:.2f})" for v, c in imp])

# ---- Save metrics + report ----
metrics = {
    "single_sensor": single_metrics,
    "full_array": full_metrics,
    "per_source_counts": dict(src_counts),
    "window": window_label,
    "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
}
with open("models/metrics.json", "w") as f:
    json.dump(metrics, f, indent=2, default=str)

# Short report
n_sensors = len([s for s in df["source"].unique() if s.startswith("esp_")])
with open("models/REPORT.md", "w") as f:
    f.write("# Room Sentinel v3 — Training Report\n\n")
    f.write(f"Trained: {metrics['trained_at']}\n")
    f.write(f"Samples: {len(X)} ({y.sum()} inside, {(y==0).sum()} outside)\n")
    f.write(f"Window: {window_label}\n\n")
    f.write(f"| Metric | Single Sensor | Full Array ({n_sensors}) |\n")
    f.write("|--------|---------------|----------------|\n")
    f.write(f"| LOPO accuracy | {single_metrics['accuracy']:.3f} | {full_metrics['accuracy']:.3f} |\n")
    wp1 = f"{single_metrics['adjacent_wall_fp']:.3f}" if single_metrics['adjacent_wall_fp'] is not None else "N/A"
    wp2 = f"{full_metrics['adjacent_wall_fp']:.3f}" if full_metrics['adjacent_wall_fp'] is not None else "N/A"
    f.write(f"| Adjacent-wall FP | {wp1} | {wp2} |\n")
    pr1 = f"{single_metrics['pocket_recall']:.3f}" if single_metrics['pocket_recall'] is not None else "N/A"
    pr2 = f"{full_metrics['pocket_recall']:.3f}" if full_metrics['pocket_recall'] is not None else "N/A"
    f.write(f"| IN_POCKET recall | {pr1} | {pr2} |\n")
    f.write(f"| Threshold | {single_metrics['threshold']:.2f} | {full_metrics['threshold']:.2f} |\n")

print("\nSaved models/metrics.json and models/REPORT.md")
