"""Gate M-A — marker-completeness binary gate.

Per HANDOFF_MARKER_HARDENING.md §"Phase M-A":
  (a) theo: 87.8% agent-marked (1886/2149) + model ladder 4.5/4.6/4.7/4.8
      resolves with expected rough counts
  (b) 11 GitHub <noreply@github.com> web-UI commits + the Robyn co-author
      lines NOT flagged
  (c) new marker test corpus passes (run separately via unittest)
  (d) PR-mode regression: OSWv2's agent-marked output is byte-identical to
      before (the saved quality/audit_order-sheet-web-v2.json's
      ai_marked.per_unit dict)

Exit 0 = all four pass. Exit 1 = any divergence; prints the failures.

Usage:
  python3 quality/gateM_A_eval.py
  python3 quality/gateM_A_eval.py --skip-pr-regression  # if no token
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

THEO_PATH = Path("/Users/mattbuscher/Documents/claude/AI_Stewardship_Cert/_external/theo")
HERE = Path(__file__).parent
OSWV2_BASELINE = HERE / "audit_order-sheet-web-v2.json"

# Expected theo values per handoff (binary gate — these are exact)
THEO_TOTAL = 2149
THEO_MARKED = 1886
THEO_MARKED_PCT = 87.8
# Model-ladder counts: the handoff lists "≈" estimates; allow ±5% bands.
THEO_LADDER_EXPECTED = {
    "4.5": 685,
    "4.6": 858,   # observed 857 — within band
    "4.7": 284,
    "4.8": 52,
}
LADDER_TOLERANCE = 0.05     # ±5% allowed per version


def _run_audit(local_path: Path, out_dir: Path) -> dict:
    """Run commensa-audit in commit-mode and return the parsed audit JSON."""
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["/tmp/commensa_test_venv/bin/commensa-audit",
         "--local-clone", str(local_path),
         "--out", str(out_dir)],
        capture_output=True, check=True,
    )
    # audit JSON filename derives from the basename of the local path
    name = local_path.name
    audit_path = out_dir / f"audit_{name}.json"
    return json.loads(audit_path.read_text())


def check_theo() -> tuple[bool, list[str]]:
    """Acceptance items (a) and (b)."""
    failures: list[str] = []
    out = Path(tempfile.mkdtemp(prefix="gateM_A_theo_"))
    audit = _run_audit(THEO_PATH, out)
    am = audit["ai_marked"]
    rt = audit["rework_tax"]

    # (a) totals
    if rt["total_prs"] != THEO_TOTAL:
        failures.append(f"theo total: got {rt['total_prs']}, expected {THEO_TOTAL}")
    if am["count"] != THEO_MARKED:
        failures.append(f"theo marked: got {am['count']}, expected {THEO_MARKED}")
    if abs(am["pct_of_prs_lower_bound"] - THEO_MARKED_PCT) > 0.1:
        failures.append(f"theo pct: got {am['pct_of_prs_lower_bound']}, "
                        f"expected {THEO_MARKED_PCT}")

    # (a) model ladder
    from collections import Counter
    versions = Counter()
    for uid, m in (am.get("per_unit_model") or {}).items():
        v = m.get("version")
        if v:
            versions[v] += 1
    for ver, expected in THEO_LADDER_EXPECTED.items():
        actual = versions.get(ver, 0)
        delta_pct = abs(actual - expected) / expected
        ok = delta_pct <= LADDER_TOLERANCE
        if not ok:
            failures.append(f"theo Claude {ver}: got {actual}, expected ~{expected} "
                            f"(±{int(LADDER_TOLERANCE*100)}% — delta {delta_pct:.1%})")

    # (b) negatives — query git for the 11 web-UI commits and 82 Robyn lines
    marked_uids = set(am["per_unit"])

    webui_shas = subprocess.run(
        ["git", "-C", str(THEO_PATH), "log", "--all", "--format=%H %cE"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    webui_shas = [l.split()[0] for l in webui_shas if "noreply@github.com" in l]
    webui_uids = ["SHA-" + s[:12] for s in webui_shas]
    leaked = [u for u in webui_uids if u in marked_uids]
    if leaked:
        failures.append(f"theo web-UI commits flagged: {len(leaked)} (must be 0); "
                        f"first few: {leaked[:3]}")

    # The Robyn lines appear ON commits that ARE marked (Claude co-author), so
    # we check that "Robyn" never appears in the marker STRINGS (not whether
    # the commit itself is marked).
    robyn_appearances = sum(
        1 for markers in am["per_unit"].values()
        for m in markers
        if "robyn" in m.lower()
    )
    if robyn_appearances:
        failures.append(f"theo: 'Robyn' string appears in {robyn_appearances} "
                        f"marker entries (must be 0)")

    return (len(failures) == 0), failures


def check_pr_regression() -> tuple[bool, list[str]]:
    """Acceptance item (d): OSWv2 PR-mode ai_marked byte-identical to baseline."""
    failures: list[str] = []
    baseline = json.loads(OSWV2_BASELINE.read_text())["ai_marked"]
    out = Path(tempfile.mkdtemp(prefix="gateM_A_oswv2_"))
    subprocess.run(
        ["/tmp/commensa_test_venv/bin/commensa-audit",
         "--repo", "mattlaptopsanytime-collab/order-sheet-web-v2",
         "--out", str(out)],
        capture_output=True, check=True,
        env={**os.environ,
             "GH_TOKEN": subprocess.run(["gh", "auth", "token"],
                                        capture_output=True, text=True,
                                        check=True).stdout.strip()},
    )
    new_audit = json.loads(
        (out / "audit_order-sheet-web-v2.json").read_text())
    new_am = new_audit["ai_marked"]

    if new_am["count"] != baseline["count"]:
        failures.append(f"OSWv2 count: got {new_am['count']}, "
                        f"baseline {baseline['count']}")
    if new_am["pct_of_prs_lower_bound"] != baseline["pct_of_prs_lower_bound"]:
        failures.append(f"OSWv2 pct: got {new_am['pct_of_prs_lower_bound']}, "
                        f"baseline {baseline['pct_of_prs_lower_bound']}")
    # per_unit must be byte-identical for byte-identical output claim
    if new_am["per_unit"] != baseline["per_unit"]:
        # Show only the keys that differ to keep output sane
        old_keys = set(baseline["per_unit"])
        new_keys = set(new_am["per_unit"])
        only_old = old_keys - new_keys
        only_new = new_keys - old_keys
        diff_vals = [k for k in old_keys & new_keys
                     if baseline["per_unit"][k] != new_am["per_unit"][k]]
        failures.append(
            f"OSWv2 per_unit DIVERGED: only-baseline={sorted(only_old)[:5]} "
            f"only-new={sorted(only_new)[:5]} "
            f"value-diff={sorted(diff_vals)[:5]}")
    return (len(failures) == 0), failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-pr-regression", action="store_true",
                    help="Skip the OSWv2 PR-mode regression (requires GH token)")
    args = ap.parse_args()

    print("Gate M-A — marker completeness")
    print(f"  theo path : {THEO_PATH}")
    print(f"  baseline  : {OSWV2_BASELINE}")
    print()

    all_ok = True

    print("[1/2] theo — totals, model ladder, negatives")
    ok, failures = check_theo()
    if ok:
        print("  OK")
    else:
        all_ok = False
        for f in failures:
            print(f"  X  {f}")

    if args.skip_pr_regression:
        print("\n[2/2] PR-mode regression on OSWv2 — SKIPPED (--skip-pr-regression)")
    else:
        print("\n[2/2] PR-mode regression on OSWv2 (~500 API calls)")
        try:
            ok, failures = check_pr_regression()
            if ok:
                print("  OK — ai_marked byte-identical to baseline")
            else:
                all_ok = False
                for f in failures:
                    print(f"  X  {f}")
        except subprocess.CalledProcessError as e:
            all_ok = False
            print(f"  X  fresh extraction failed: {e.stderr.decode()[:300]}")

    print()
    if all_ok:
        print("GATE M-A: PASS — all checked items within tolerance.")
        return 0
    print("GATE M-A: FAIL — see failures above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
