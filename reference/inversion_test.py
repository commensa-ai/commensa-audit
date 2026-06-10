#!/usr/bin/env python3
"""
The inversion test, on REAL data — git-only, no tokens needed.
Question: do high-volume PRs turn out to be WINS, or SLOP?
If volume does NOT predict wins, the core thesis holds.

Run AFTER you fill the `label` column in LABEL_THESE.csv (win|neutral|slop):
    python3 inversion_test.py
Outputs: console verdict + inversion_test.png
"""
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

LABEL_ORD = {"slop": 0, "neutral": 1, "win": 2}

def spearman(x, y):
    rx, ry = pd.Series(x).rank().to_numpy(), pd.Series(y).rank().to_numpy()
    if rx.std() == 0 or ry.std() == 0: return 0.0
    return float(np.corrcoef(rx, ry)[0, 1])

units  = pd.read_csv("orderwebv2_units.csv")
labels = pd.read_csv("LABEL_THESE.csv")
labels["label"] = labels["label"].astype(str).str.strip().str.lower()
labels = labels[labels["label"].isin(LABEL_ORD)]
if labels.empty:
    raise SystemExit("No labels yet — fill the `label` column in LABEL_THESE.csv with win/neutral/slop.")

d = labels.merge(units[["unit_id", "lines_added", "changed_files"]], on="unit_id", how="left")
d["is_win"]    = (d.label == "win").astype(int)
d["label_ord"] = d.label.map(LABEL_ORD)

rho_win  = spearman(d.lines_added, d.is_win)      # want ~<= 0  (volume does NOT predict wins)
rho_ord  = spearman(d.lines_added, d.label_ord)   # want ~<= 0
means    = d.groupby("label")["lines_added"].mean().reindex([x for x in ["win","neutral","slop"] if x in d.label.values])

print("\n" + "="*58 + "\nINVERSION TEST — order-sheet-web-v2 (real PRs)\n" + "="*58)
print(f"labeled PRs: {len(d)}  (win {sum(d.label=='win')} / neutral {sum(d.label=='neutral')} / slop {sum(d.label=='slop')})")
print("\nmean lines_added by label:")
for k, v in means.items(): print(f"   {k:8s} {v:7.0f}")
print(f"\nvolume vs WIN   rho = {rho_win:+.2f}   (want <= ~0.15)")
print(f"volume vs label rho = {rho_ord:+.2f}")
holds = rho_win <= 0.15
print("\nINVERSION HOLDS (volume does NOT predict wins): " + ("YES — thesis supported on real data" if holds else "NO — volume tracks wins here; investigate"))

fig, ax = plt.subplots(1, 2, figsize=(11, 4.4)); fig.suptitle("Inversion test — does volume predict your wins? (order-sheet-web-v2)", weight="bold")
colors = {"win":"#1f9d62","neutral":"#c98a16","slop":"#d23f3f"}
for lab in [l for l in ["win","neutral","slop"] if l in d.label.values]:
    s = d[d.label==lab]; ax[0].scatter(s.lines_added, np.random.normal(LABEL_ORD[lab],.06,len(s)), c=colors[lab], s=60, alpha=.8, edgecolors="white", label=lab)
ax[0].set_yticks([0,1,2]); ax[0].set_yticklabels(["slop","neutral","win"]); ax[0].set_xlabel("lines added (volume)"); ax[0].set_title(f"volume vs label (rho={rho_win:+.2f})"); ax[0].legend()
means.plot(kind="bar", ax=ax[1], color=[colors[i] for i in means.index]); ax[1].set_title("mean volume by label"); ax[1].set_ylabel("lines added"); ax[1].tick_params(axis="x", rotation=0)
plt.tight_layout(rect=[0,0,1,.94]); plt.savefig("inversion_test.png", dpi=130); print("\nchart -> inversion_test.png")
