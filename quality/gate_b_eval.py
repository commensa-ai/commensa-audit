#!/usr/bin/env python3
"""Gate B evaluation — classifier vs the Pilot 1 corrective subset.

Pilot 1 grouping (RESULTS_pilot1.md): 30 labeled PRs split "Corrective
(fix/correct/superseded)" n=7 vs Generative n=23, with corrective = 4 slop /
2 win / 1 neutral and mean lines 69.

Reconstruction of the 7 (the pilot tags were never stored per-PR):
- title-explicit (fix/correct tokens): PR-136, PR-31, PR-119, PR-125,
  PR-117 (fix*), PR-9 (correct) — 6 PRs
- superseded: PR-138 (palette unify, replaced by the PR-141 revert 12h later)
The arithmetic confirms it: labels of these 7 = slop(31,119,125,138) win(136,117)
neutral(9) = 4/2/1 exactly, mean lines_added = 69. No other subset of the 30
matches both the rule and the arithmetic.

GATE B (SPEC.md): classifier's corrective/generative split agrees ≥80% on
the 30. Run AFTER `commensa-audit … --out <dir>`:
    python3 quality/gate_b_eval.py <dir>/audit_order-sheet-web-v2.json
"""

import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LABELS = os.path.join(HERE, "..", "reference", "LABEL_THESE.csv")

PILOT_CORRECTIVE = {
    "PR-136", "PR-31", "PR-119", "PR-125", "PR-117", "PR-9",  # title-explicit
    "PR-138",                                                  # superseded
}


def main(audit_path: str) -> int:
    audit = json.load(open(audit_path, encoding="utf-8"))
    cls = audit["classifications"]
    with open(LABELS, newline="", encoding="utf-8") as f:
        labeled = list(csv.DictReader(f))
    assert len(labeled) == 30, f"expected 30 labeled PRs, got {len(labeled)}"

    sanity = sorted(u["unit_id"] for u in labeled if u["unit_id"] in PILOT_CORRECTIVE)
    assert len(sanity) == 7, f"pilot reconstruction broken: {sanity}"

    rows, agree_strict, agree_sup = [], 0, 0
    for u in labeled:
        uid = u["unit_id"]
        pilot = "corrective" if uid in PILOT_CORRECTIVE else "generative"
        mine = cls[uid]["classification"]
        mine_sup = "corrective" if (mine == "corrective" or cls[uid].get("superseded_by")) else "generative"
        agree_strict += mine == pilot
        agree_sup += mine_sup == pilot
        rows.append((uid, u["label"], pilot, mine, cls[uid].get("signal") or "—",
                     cls[uid].get("superseded_by") or "", mine == pilot))

    print(f"{'unit':8s} {'label':8s} {'pilot':11s} {'classifier':11s} {'signal':16s} {'superseded_by':14s} agree")
    for r in sorted(rows, key=lambda r: (r[6], r[0])):
        print(f"{r[0]:8s} {r[1]:8s} {r[2]:11s} {r[3]:11s} {r[4]:16s} {r[5]:14s} {'✓' if r[6] else '✗ DISAGREE'}")

    n = len(labeled)
    print(f"\nagreement (classification only):           {agree_strict}/{n} = {100 * agree_strict / n:.1f}%")
    print(f"agreement (corrective-or-superseded,")
    print(f"           the pilot's own grouping rule):  {agree_sup}/{n} = {100 * agree_sup / n:.1f}%")
    ok = agree_sup / n >= 0.80
    print(f"\nGATE B (≥80%): {'MET — pending Matt spot-check of 10 classifications' if ok else 'NOT MET'}")

    print("\ndisagreements (documented, not hidden — product learning):")
    for r in rows:
        if not r[6]:
            print(f"  {r[0]} ({r[1]}): pilot={r[2]}, classifier={r[3]}"
                  f"{' via ' + r[4] if r[4] != '—' else ''}"
                  f"{'; superseded_by ' + r[5] if r[5] else ''}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "audit_order-sheet-web-v2.json"))
