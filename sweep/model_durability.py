#!/usr/bin/env python3
"""Model-durability from the ALREADY-CAPTURED sweep output (no re-run).

Greg's (theo) scan showed the Co-Authored-By trailers carry the MODEL
(Claude Opus 4.5 -> 4.6 -> 4.7 -> 4.8), and the per-repo audit JSON already
holds per-unit survival, per-unit classification, and the per-unit marker
strings. So "which model's code survives / gets reworked" is recoverable
from data you already have.

Run on the machine that holds the sweep --out dir:
    python3 model_durability.py --sweep-out /path/to/sweep_out [--min-age-days 90]

THE AGE-CONTROL (why it matters): survival in the audit is "lines still live
NOW." Recent code trivially "survives" because nothing has come after it to
rework it. So raw survival is confounded by code age, and newer models look
better only because their code is younger. --min-age-days censors that:
a unit is only SCORED if it is at least N days old (it has had a fair chance
to be reworked). Units too young are EXCLUDED, not counted as survivors.
A model whose code is all younger than N days correctly shows 0 aged units
-- "not enough aged code to judge yet" -- instead of a fake high survival.
(This is a crude censor; the rigorous version is fixed-horizon survival /
Kaplan-Meier, which needs an engine change to compute survival-at-age-N.)

Within ONE repo, model and code-age are collinear (newer model == newer
code), so a single repo can't separate them -- run on the COHORT, where
different repos adopted each model at different points in their lifecycle.

EXPLORATORY (discovered mid-stream), not the pre-registered analysis.
Report as a lower bound: unmarked / other-tool units are excluded, not human.
"""
from __future__ import annotations
import argparse, csv, glob, json, os, re, datetime
from collections import defaultdict

MODEL_RE = re.compile(r"opus\s*4\.(\d)", re.I)
OTHER_AGENTS = ["copilot", "cursor", "codex", "gemini", "devin", "aider", "claude code"]

def model_of(marker_strings):
    blob = " ".join(marker_strings or []).lower() if not isinstance(marker_strings, str) else marker_strings.lower()
    m = MODEL_RE.search(blob)
    if m: return f"Claude Opus 4.{m.group(1)}"
    if "claude" in blob or "anthropic" in blob: return "Claude (unversioned)"
    for a in OTHER_AGENTS:
        if a in blob: return a.title()
    return None

def load_units(audit_path):
    """unit_id -> (lines_added, created_date) from units.csv next to the audit."""
    p = os.path.join(os.path.dirname(audit_path), "units.csv")
    out = {}
    if os.path.exists(p):
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try: la = int(row.get("lines_added") or 0)
                except Exception: la = 0
                d = None
                ca = (row.get("created_at") or "")[:10]
                try: d = datetime.date.fromisoformat(ca)
                except Exception: pass
                out[row["unit_id"]] = (la, d)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep-out", required=True)
    ap.add_argument("--min-age-days", type=int, default=90,
                    help="only score units at least this old (censor young code; 0 = off)")
    ap.add_argument("--out", default="model_durability.json")
    args = ap.parse_args()

    audits = sorted(glob.glob(os.path.join(args.sweep_out, "**", "audit_*.json"), recursive=True))
    if not audits:
        print(f"no audit_*.json under {args.sweep_out}"); return 1

    n_units = defaultdict(int); n_corr = defaultdict(int)
    surv_num = defaultdict(float); surv_den = defaultdict(float)
    censored = defaultdict(int); no_date = defaultdict(int)
    repos_seen = 0; weighting = "line-weighted"; any_units_csv = False

    for ap_path in audits:
        try: a = json.load(open(ap_path, encoding="utf-8"))
        except Exception: continue
        repos_seen += 1
        per_marker = (a.get("ai_marked") or {}).get("per_unit") or {}
        per_surv   = (a.get("survival") or {}).get("per_unit") or {}
        cls        = a.get("classifications") or {}
        units      = load_units(ap_path)
        if units: any_units_csv = True
        # as-of date for this repo = latest unit date (proxy for measurement time)
        dates = [d for (_, d) in units.values() if d]
        as_of = max(dates) if dates else None

        for uid, info in cls.items():
            model = model_of(per_marker.get(uid))
            if model is None: continue
            la, created = units.get(uid, (1, None))
            # CORRECTIVE% is counted on ALL marked units — a commit is corrective by
            # its own nature when it lands; it does NOT need to age. (Matt's catch.)
            n_units[model] += 1
            if info.get("classification") == "corrective": n_corr[model] += 1
            # SURVIVAL only — this one needs aging; censor units too young to judge.
            sval = per_surv.get(uid)
            if sval is None: continue
            too_young = bool(args.min_age_days and as_of and created and (as_of - created).days < args.min_age_days)
            if too_young:
                censored[model] += 1
            else:
                w = float(la or 1)
                surv_num[model] += sval * w
                surv_den[model] += w

    if not any_units_csv: weighting = "simple-mean (no units.csv; age-control OFF)"
    order = ["Claude Opus 4.5","Claude Opus 4.6","Claude Opus 4.7","Claude Opus 4.8","Claude (unversioned)"]
    models = order + sorted(m for m in set(n_units) if m not in order)
    rows = []
    floor = f"survival aged >={args.min_age_days}d" if args.min_age_days else "no age floor"
    print(f"\nMODEL DURABILITY across {repos_seen} repos  ·  corrective%=all units · {floor} · survival {weighting}")
    print(f"{'model':24} {'units':>7} {'corrective%':>12} {'survival%(aged)':>16} {'svl-censored':>13}")
    for m in models:
        if not n_units.get(m): continue
        corr = 100*n_corr[m]/n_units[m]
        if surv_den.get(m):
            surv = 100*surv_num[m]/surv_den[m]; sv = f"{surv:>15.1f}%"
        else:
            surv = None; sv = f"{'too young':>16}"
        print(f"{m:24} {n_units[m]:>7} {corr:>11.1f}% {sv} {censored.get(m,0):>13}")
        rows.append({"model":m,"units":n_units[m],"corrective_pct":round(corr,1),
                     "survival_pct_aged":round(surv,1) if surv is not None else None,
                     "survival_censored":censored.get(m,0)})
    json.dump({"repos":repos_seen,"min_age_days":args.min_age_days,"weighting":weighting,"by_model":rows,
               "caveats":["EXPLORATORY not pre-registered",
                          "marker = lower bound; unmarked excluded not 'human'",
                          "age floor is a crude censor; rigorous = fixed-horizon survival (engine change)",
                          "within one repo model==age (collinear); the cohort is what separates them"]},
              open(args.out,"w"), indent=2)
    print(f"\nwrote {args.out}  ·  EXPLORATORY; survival is a lower-bound read, age-censored at {args.min_age_days}d.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
