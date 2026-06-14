"""Gate D-B — cross-mode agreement on order-sheet-web-v2.

Spec (COMMIT_MODE_SPEC.md): run commit-mode on a repo that ALSO has a
known-good PR-mode audit. Commit-mode's drift metrics must ROUGHLY TRACK
the PR-mode result on the same repo — same rework story, no wild
divergence. Expected differences (squash merges collapse commits, etc.)
are documented, not gate failures.

This is intentionally a "tracks" gate, not an "equals" gate. PR-mode and
commit-mode measure at different rings:
  PR-mode    = drift visible at the team's review ring (the PR)
  commit-mode = drift visible at the author's individual ring (each commit)
The triad of (PR-corrective%, line-corrective%, merge-rate-equivalent)
should land in the same neighborhood; the cluster/superseded counts may
scale differently because the unit cardinality differs.

Inputs:
  --pr-audit  : path to the known-good PR-mode audit JSON
  --cm-audit  : path to the commit-mode audit JSON (this run)
Exit 0 = gate passed (within thresholds); 1 = wild divergence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# tolerance bands — "roughly tracks", not equals
LINE_PCT_ABS_TOL   = 5.0   # absolute pp band on corrective-LINES% (PR-mode 12.9% → cm in [7.9, 17.9])
SURVIVAL_ABS_TOL   = 0.10  # ±10pp on overall survival
PR_PCT_RATIO_MIN   = 0.30  # commit corrective-COMMIT% can be a fraction of PR%
PR_PCT_RATIO_MAX   = 3.00  # but not >3x (would suggest a different signal entirely)


def _read(path):
    return json.loads(Path(path).read_text())


def _band(name, pr_val, cm_val, abs_tol):
    delta = abs(pr_val - cm_val)
    ok = delta <= abs_tol
    return {"name": name, "pr": pr_val, "cm": cm_val,
            "delta_abs": round(delta, 3), "abs_tol": abs_tol, "ok": ok}


def _ratio(name, pr_val, cm_val, lo, hi):
    if pr_val == 0 and cm_val == 0:
        return {"name": name, "pr": pr_val, "cm": cm_val,
                "ratio": None, "lo": lo, "hi": hi,
                "ok": True, "note": "both zero"}
    if pr_val == 0:
        return {"name": name, "pr": pr_val, "cm": cm_val,
                "ratio": float("inf"), "lo": lo, "hi": hi,
                "ok": False, "note": "PR=0, CM>0 — possible signal divergence"}
    r = cm_val / pr_val
    return {"name": name, "pr": pr_val, "cm": cm_val,
            "ratio": round(r, 3), "lo": lo, "hi": hi,
            "ok": lo <= r <= hi}


def compare(pr_audit, cm_audit):
    pr_rt = pr_audit["rework_tax"]
    cm_rt = cm_audit["rework_tax"]
    pr_sv = pr_audit.get("survival", {})
    cm_sv = cm_audit.get("survival", {})
    pr_vc = pr_audit.get("velocity_context", {})
    cm_vc = cm_audit.get("velocity_context", {})

    checks = [
        # TRIAD-headline: corrective-LINE% — must roughly track (this is the
        # universal signal, author-agnostic, both modes measure the same thing)
        _band("corrective_LINE_pct",
              pr_rt["pct_changed_lines_corrective"],
              cm_rt["pct_changed_lines_corrective"],
              LINE_PCT_ABS_TOL),
        # corrective-PR/COMMIT% — different cardinality, expect a ratio band
        _ratio("corrective_unit_pct_ratio (CM/PR)",
               pr_rt["pct_prs_corrective"],
               cm_rt["pct_prs_corrective"],
               PR_PCT_RATIO_MIN, PR_PCT_RATIO_MAX),
        # Survival — same engine, content-attribution, should roughly track
        _band("survival_overall",
              pr_sv.get("overall_rate", 0),
              cm_sv.get("overall_rate", 0),
              SURVIVAL_ABS_TOL),
    ]

    # Context (informational, no pass/fail) — these by design diverge
    context = {
        "pr_total_units":  pr_rt["total_prs"],
        "cm_total_units":  cm_rt["total_prs"],
        "cm_to_pr_ratio":  (round(cm_rt["total_prs"] / pr_rt["total_prs"], 2)
                            if pr_rt["total_prs"] else None),
        "pr_churn_clusters":  len(pr_audit.get("churn_clusters", [])),
        "cm_churn_clusters":  len(cm_audit.get("churn_clusters", [])),
        "pr_supersessions":   len(pr_audit.get("supersessions", {})),
        "cm_supersessions":   len(cm_audit.get("supersessions", {})),
        "pr_per_week":        pr_vc.get("prs_per_week"),
        "cm_per_week":        cm_vc.get("prs_per_week"),
        "pr_median_size":     pr_vc.get("size_lines_added", {}).get("median"),
        "cm_median_size":     cm_vc.get("size_lines_added", {}).get("median"),
    }

    return checks, context


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pr-audit", required=True)
    ap.add_argument("--cm-audit", required=True)
    args = ap.parse_args()

    pr = _read(args.pr_audit)
    cm = _read(args.cm_audit)
    print(f"Gate D-B — cross-mode agreement")
    print(f"PR-mode audit : {args.pr_audit}")
    print(f"  -> repo={pr.get('repo')}  units={pr['rework_tax']['total_prs']}")
    print(f"CM-mode audit : {args.cm_audit}")
    print(f"  -> repo={cm.get('repo')}  units={cm['rework_tax']['total_prs']}")
    print()

    checks, ctx = compare(pr, cm)

    print("=== Tracked checks (the gate) ===")
    for c in checks:
        if "ratio" in c:
            note = c.get("note") or ""
            print(f"  [{'OK ' if c['ok'] else 'X  '}] {c['name']}: "
                  f"PR={c['pr']:.3g} CM={c['cm']:.3g}  "
                  f"ratio={c['ratio']} (need {c['lo']}–{c['hi']})  {note}")
        else:
            print(f"  [{'OK ' if c['ok'] else 'X  '}] {c['name']}: "
                  f"PR={c['pr']:.3g} CM={c['cm']:.3g}  "
                  f"|delta|={c['delta_abs']:.3g} (tol ±{c['abs_tol']:.3g})")

    print("\n=== Context (informational; divergence here is expected) ===")
    for k, v in ctx.items():
        print(f"  {k:24s}: {v}")

    print("\n=== Expected divergences (per spec, NOT gate failures) ===")
    if ctx["cm_to_pr_ratio"] and ctx["cm_to_pr_ratio"] > 1.2:
        print(f"  • commit/PR ratio = {ctx['cm_to_pr_ratio']}x — fan-out of "
              f"commits → squashed PRs is real (and the reason squash collapses "
              f"history). Both modes' headline LINE% still tracks if the "
              f"corrective work is what matters, not the count.")
    if ctx["cm_churn_clusters"] != ctx["pr_churn_clusters"]:
        print(f"  • cluster counts differ ({ctx['pr_churn_clusters']} PR vs "
              f"{ctx['cm_churn_clusters']} CM) — clustering is unit-cardinality "
              f"sensitive; the SAME saga shows up as different chain lengths.")
    if ctx["cm_supersessions"] != ctx["pr_supersessions"]:
        print(f"  • supersession counts differ ({ctx['pr_supersessions']} PR vs "
              f"{ctx['cm_supersessions']} CM) — same reason as clusters; the "
              f"replacement happens at finer granularity in commit-mode.")

    failed = [c for c in checks if not c["ok"]]
    print()
    if failed:
        print(f"GATE D-B: FAIL — {len(failed)} tracked check(s) out of band:")
        for c in failed:
            print(f"  - {c['name']}")
        return 1
    print(f"GATE D-B: PASS — all {len(checks)} tracked checks within tolerance. "
          f"Commit-mode roughly tracks PR-mode on the locked headline metric "
          f"(corrective_LINE_pct), survival, and corrective-unit ratio.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
