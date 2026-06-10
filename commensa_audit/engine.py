"""Metrics engine — stdlib-only port of reference/commensa_validate.py.

The keystone question it answers is unchanged: does durable/accepted output
track what the team called WINS, and does raw VOLUME fail to predict wins
(the inversion)?

Port notes (deliberate deviations from the reference, logged in BUILD_LOG):
- numpy/pandas/matplotlib removed — SPEC.md guardrail is stdlib+requests
  (+jinja2 in Phase C). Rank/Pearson/Spearman are hand-rolled below; the
  rank correlation stays scipy-free exactly as in the reference.
- chart() is not ported (matplotlib). The Phase C HTML report replaces it.
- Rows are lists of dicts (the units.csv schema + extra columns), not
  DataFrames.

Field expectations: the keystone path needs `tokens` and `surviving_lines`
per unit. v1 git-only extraction does not produce tokens (harness-era; the
no-unsupported-claims guardrail forbids estimating them) — this engine is
for validation datasets that carry them, and for Phase B survival output.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import sys

LABEL_ORD = {"slop": 0, "neutral": 1, "win": 2}


# ---------- rank / correlation (no scipy, no numpy) ----------

def rank_average(xs) -> list[float]:
    """Ranks 1..n with ties sharing the average rank (pandas method='average')."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1  # mean of positions i..j, 1-based
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def pearson(x, y) -> float:
    n = len(x)
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    if sx == 0 or sy == 0:
        return 0.0
    return cov / (sx * sy)


def spearmanr(x, y):
    """Spearman rho = Pearson on ranks. Returns (rho, None). No scipy needed."""
    rx, ry = rank_average(list(x)), rank_average(list(y))
    if len(set(rx)) <= 1 or len(set(ry)) <= 1:
        return 0.0, None
    return pearson(rx, ry), None


def _rank01(xs) -> list[float]:
    r = rank_average(list(xs))
    lo, hi = min(r), max(r)
    span = max(hi - lo, 1e-9)
    return [(v - lo) / span for v in r]


# ---------- metrics ----------

def compute_metrics(rows: list[dict]) -> list[dict]:
    """Per-unit durability metrics. Needs tokens, lines_added, surviving_lines."""
    required = {"tokens", "lines_added", "surviving_lines"}
    missing = required - (rows[0].keys() if rows else required)
    if missing:
        raise KeyError(
            f"compute_metrics needs columns {sorted(required)}; missing {sorted(missing)}. "
            "v1 git-only units.csv has no tokens — see module docstring.")
    out = []
    for row in rows:
        d = dict(row)
        surviving = max(d["surviving_lines"], 0)
        d["surviving_lines"] = surviving
        surv = max(surviving, 1)  # avoid /0
        d["survival_rate"] = min(max(surviving / max(d["lines_added"], 1), 0.0), 1.0)
        d["tokens_per_surviving"] = d["tokens"] / surv      # lower is better — the core metric
        d["lines_per_surviving"] = d["lines_added"] / surv  # lower is better — design economy
        # slop = lots of tokens AND lots of code per unit that actually lasted
        d["slop_raw"] = (d["tokens"] * d["lines_added"]) / (surv ** 2)
        out.append(d)
    for d, s in zip(out, _rank01([d["slop_raw"] for d in out])):
        d["slop_score"] = s * 100  # 0..100, higher = sloppier
    return out


# ---------- the keystone test ----------

def analyze(rows: list[dict]) -> dict:
    d = [dict(r) for r in rows]
    for r in d:
        r["label_ord"] = LABEL_ORD[r["label"]]
        r["is_win"] = 1 if r["label"] == "win" else 0

    # 1) does slop separate wins from slop?  expect slop_score: win < neutral < slop
    means = {}
    for lab in ("win", "neutral", "slop"):
        vals = [r["slop_score"] for r in d if r["label"] == lab]
        means[lab] = sum(vals) / len(vals) if vals else math.nan
    rho_slop, _ = spearmanr([r["slop_score"] for r in d],
                            [r["label_ord"] for r in d])  # expect NEGATIVE

    # 2) the inversion: does raw volume predict wins?  expect ~0 / negative
    is_win = [r["is_win"] for r in d]
    rho_vol_lines, _ = spearmanr([r["lines_added"] for r in d], is_win)
    rho_vol_tok, _ = spearmanr([r["tokens"] for r in d], is_win)

    # 3) does durability predict wins? expect POSITIVE
    rho_surv, _ = spearmanr([r["survival_rate"] for r in d], is_win)

    # verdict heuristic
    separates = rho_slop < -0.25
    inversion_holds = rho_vol_lines <= 0.15 and rho_vol_tok <= 0.15
    durable_predicts = rho_surv > 0.25
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


# ---------- console report ----------

def report(a: dict):
    print("\n" + "=" * 60)
    print("COMMENSA — KEYSTONE VALIDATION")
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


# ---------- synthetic data (proves the engine end-to-end, stdlib RNG) ----------

def synthetic(n: int = 120, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        q = rng.betavariate(2, 2)  # hidden craft quality 0..1
        model = rng.choices(["Claude", "GPT", "Llama"], weights=[.45, .35, .20])[0]
        lines = round(rng.lognormvariate(4.7, .6))
        tok_per_line = rng.lognormvariate(4.2, .35) * (1.8 - q)
        tokens = round(tok_per_line * lines)
        survival = min(max(0.35 + 0.55 * q + rng.gauss(0, .08), 0.02), 0.99)
        score = q + rng.gauss(0, .12)
        label = "win" if score > 0.62 else ("slop" if score < 0.40 else "neutral")
        rows.append(dict(unit_id=f"PR-{i + 1}", model=model, tokens=int(tokens),
                         lines_added=int(lines),
                         lines_deleted=int(lines * rng.uniform(.1, .4)),
                         merged=True, reverted_in_window=survival < .3,
                         surviving_lines=int(round(lines * survival)), label=label,
                         _q=q, _survival=survival))
    # inject high-volume slop units (the inversion trap)
    for i in rng.sample(range(n), max(3, n // 20)):
        r = rows[i]
        r["lines_added"] = int(r["lines_added"] * 2.4)
        r["tokens"] = int(r["tokens"] * 2.6)
        s = min(max(r["_survival"] * 0.4, 0.02), 0.5)
        r["surviving_lines"] = int(round(r["lines_added"] * s))
        r["label"] = "slop"
    for r in rows:
        r.pop("_q"), r.pop("_survival")
    return rows


# ---------- CLI (mirrors the reference; chart intentionally absent) ----------

def _read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k, v in r.items():
            if v is not None and k != "label":
                try:
                    r[k] = int(v)
                except ValueError:
                    try:
                        r[k] = float(v)
                    except ValueError:
                        pass
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--synthetic", type=int, metavar="N")
    ap.add_argument("--units")
    ap.add_argument("--labels")
    args = ap.parse_args(argv)
    if args.synthetic:
        rows = synthetic(args.synthetic)
    elif args.units and args.labels:
        units = _read_csv(args.units)
        labels = {r["unit_id"]: str(r["label"]).strip().lower()
                  for r in _read_csv(args.labels) if r.get("label")}
        rows = [dict(u, label=labels[u["unit_id"]]) for u in units
                if labels.get(u["unit_id"]) in LABEL_ORD]
        if not rows:
            sys.exit("No overlapping unit_id between units and labels.")
    else:
        sys.exit("Pass --synthetic N  OR  --units units.csv --labels labels.csv")
    report(analyze(compute_metrics(rows)))


if __name__ == "__main__":
    main()
