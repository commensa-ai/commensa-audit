#!/usr/bin/env python3
"""
Commensa — keystone validation engine.

Answers the one question the company rests on:
  Does durable/accepted output (on a configurable gate) track what the team called WINS,
  and does raw VOLUME fail to predict wins (the inversion)?

Inputs (real mode):
  units.csv  : unit_id, model, tokens, lines_added, lines_deleted, merged, reverted_in_window, surviving_lines
  labels.csv : unit_id, label   (win | neutral | slop)
Join on unit_id. Survival window is applied upstream when computing surviving_lines.

Run:
  python3 commensa_validate.py --synthetic 120          # demo on generated data
  python3 commensa_validate.py --units units.csv --labels labels.csv
Outputs: console verdict + commensa_validation.png
"""
import argparse, sys
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

LABEL_ORD = {"slop": 0, "neutral": 1, "win": 2}

def spearmanr(x, y):
    """Spearman rho = Pearson on ranks. Returns (rho, None). No scipy needed."""
    rx = pd.Series(x).rank().to_numpy(); ry = pd.Series(y).rank().to_numpy()
    if rx.std() == 0 or ry.std() == 0:
        return 0.0, None
    return float(np.corrcoef(rx, ry)[0, 1]), None

# ---------- metrics ----------
def compute_metrics(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["surviving_lines"] = d["surviving_lines"].clip(lower=0)
    surv = d["surviving_lines"].clip(lower=1)                      # avoid /0
    d["survival_rate"]            = (d["surviving_lines"] / d["lines_added"].clip(lower=1)).clip(0, 1)
    d["tokens_per_surviving"]     = d["tokens"] / surv             # ↓ better — the core metric
    d["lines_per_surviving"]      = d["lines_added"] / surv        # ↓ better — design economy
    # slop = lots of tokens AND lots of code per unit that actually lasted
    d["slop_raw"]                 = (d["tokens"] * d["lines_added"]) / (surv ** 2)
    d["slop_score"]               = _rank01(d["slop_raw"]) * 100   # 0..100, higher = sloppier
    return d

def _rank01(s: pd.Series) -> pd.Series:
    r = s.rank(method="average")
    return (r - r.min()) / max(r.max() - r.min(), 1e-9)

# ---------- the keystone test ----------
def analyze(d: pd.DataFrame) -> dict:
    d = d.copy()
    d["label_ord"] = d["label"].map(LABEL_ORD)
    d["is_win"]    = (d["label"] == "win").astype(int)

    # 1) does slop separate wins from slop?  expect slop_score: win < neutral < slop
    means = d.groupby("label")["slop_score"].mean().reindex(["win", "neutral", "slop"])
    rho_slop, p_slop = spearmanr(d["slop_score"], d["label_ord"])   # expect NEGATIVE (slop up, label down)

    # 2) the inversion: does raw volume predict wins?  expect ~0 / negative
    rho_vol_lines, p_vl = spearmanr(d["lines_added"], d["is_win"])
    rho_vol_tok,   p_vt = spearmanr(d["tokens"],      d["is_win"])

    # 3) does durability predict wins? expect POSITIVE
    rho_surv, p_s = spearmanr(d["survival_rate"], d["is_win"])

    # verdict heuristic
    separates = (rho_slop < -0.25)
    inversion_holds = (rho_vol_lines <= 0.15 and rho_vol_tok <= 0.15)
    durable_predicts = (rho_surv > 0.25)
    if separates and inversion_holds and durable_predicts:
        verdict = "GREEN  → build the MVP"
    elif separates or durable_predicts:
        verdict = "YELLOW → tune the gate / try 2nd repo, re-test"
    else:
        verdict = "RED    → keystone not supported; rethink the metric"

    return dict(means=means, rho_slop=rho_slop, rho_vol_lines=rho_vol_lines,
                rho_vol_tok=rho_vol_tok, rho_surv=rho_surv,
                separates=separates, inversion_holds=inversion_holds,
                durable_predicts=durable_predicts, verdict=verdict, data=d)

# ---------- report + chart ----------
def report(a: dict):
    print("\n" + "=" * 60)
    print("KEEL — KEYSTONE VALIDATION")
    print("=" * 60)
    print("\nMean slop_score by label (expect win < neutral < slop):")
    for k, v in a["means"].items():
        print(f"   {k:8s} {v:6.1f}")
    print(f"\n[1] slop vs label rho        = {a['rho_slop']:+.2f}   (want < -0.25)  -> "
          f"{'PASS' if a['separates'] else 'fail'}")
    print(f"[2] volume(lines) vs win rho = {a['rho_vol_lines']:+.2f}   (want <= 0.15) -> "
          f"{'PASS' if a['rho_vol_lines'] <= 0.15 else 'fail'}")
    print(f"    volume(tokens) vs win rho= {a['rho_vol_tok']:+.2f}")
    print(f"[3] durability vs win rho    = {a['rho_surv']:+.2f}   (want > 0.25)  -> "
          f"{'PASS' if a['durable_predicts'] else 'fail'}")
    print(f"\nINVERSION HOLDS (volume does NOT predict wins): "
          f"{'YES' if a['inversion_holds'] else 'NO'}")
    print(f"\nVERDICT: {a['verdict']}\n")

def chart(a: dict, path="commensa_validation.png"):
    d = a["data"]; colors = {"win": "#1f9d62", "neutral": "#c98a16", "slop": "#d23f3f"}
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.6)); fig.suptitle("Commensa — keystone validation", fontsize=13, weight="bold")
    # panel 1: slop vs survival, colored by label
    for lab, c in colors.items():
        s = d[d.label == lab]
        ax[0].scatter(s.slop_score, s.survival_rate, c=c, label=lab, alpha=.75, edgecolors="white", s=55)
    ax[0].set_xlabel("slop score (→ sloppier)"); ax[0].set_ylabel("survival rate"); ax[0].legend(); ax[0].set_title("wins are low-slop / high-survival")
    # panel 2: mean slop by label
    a["means"].plot(kind="bar", ax=ax[1], color=[colors[i] for i in a["means"].index])
    ax[1].set_title(f"slop separates wins from slop (rho={a['rho_slop']:+.2f})"); ax[1].set_ylabel("mean slop"); ax[1].tick_params(axis="x", rotation=0)
    # panel 3: the inversion — volume vs win
    for lab, c in colors.items():
        s = d[d.label == lab]
        ax[2].scatter(s.lines_added, s.tokens, c=c, alpha=.75, edgecolors="white", s=55)
    ax[2].set_xlabel("lines added (volume)"); ax[2].set_ylabel("tokens (volume)")
    ax[2].set_title(f"volume ≠ wins (rho={a['rho_vol_lines']:+.2f})")
    plt.tight_layout(rect=[0, 0, 1, 0.95]); plt.savefig(path, dpi=130); print(f"chart -> {path}")

# ---------- synthetic data (proves the engine end-to-end) ----------
def synthetic(n=120, seed=7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # hidden "direction quality" drives everything; noise on top
    q = rng.beta(2, 2, n)                                   # 0..1 craft quality
    models = rng.choice(["Claude", "GPT", "Llama"], n, p=[.45, .35, .20])
    lines = (rng.lognormal(4.7, .6, n)).round()            # some big, some small
    # better quality -> fewer tokens per line, higher survival
    tok_per_line = rng.lognormal(4.2, .35, n) * (1.8 - q)  # high q -> fewer tokens/line
    tokens = (tok_per_line * lines).round()
    survival = np.clip(0.35 + 0.55 * q + rng.normal(0, .08, n), 0.02, 0.99)
    surviving = (lines * survival).round()
    # label from the LATENT quality (as a human would judge), not from the metrics
    score = q + rng.normal(0, .12, n)
    label = np.where(score > 0.62, "win", np.where(score < 0.40, "slop", "neutral"))
    # inject a few high-volume slop units (the inversion trap): big lines, low quality
    trap = rng.choice(n, size=max(3, n // 20), replace=False)
    lines[trap] *= 2.4; tokens[trap] *= 2.6; survival[trap] = np.clip(survival[trap]*0.4,0.02,.5)
    surviving[trap] = (lines[trap]*survival[trap]).round(); label[trap] = "slop"
    return pd.DataFrame(dict(
        unit_id=[f"PR-{i+1}" for i in range(n)], model=models, tokens=tokens.astype(int),
        lines_added=lines.astype(int), lines_deleted=(lines*rng.uniform(.1,.4,n)).astype(int),
        merged=True, reverted_in_window=(survival < .3),
        surviving_lines=surviving.astype(int), label=label))

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", type=int, metavar="N")
    ap.add_argument("--units"); ap.add_argument("--labels")
    args = ap.parse_args()
    if args.synthetic:
        df = synthetic(args.synthetic)
    elif args.units and args.labels:
        u = pd.read_csv(args.units); l = pd.read_csv(args.labels)
        df = u.merge(l, on="unit_id", how="inner")
        if df.empty: sys.exit("No overlapping unit_id between units and labels.")
    else:
        sys.exit("Pass --synthetic N  OR  --units units.csv --labels labels.csv")
    d = compute_metrics(df)
    a = analyze(d)
    report(a)
    chart(a)

if __name__ == "__main__":
    main()
