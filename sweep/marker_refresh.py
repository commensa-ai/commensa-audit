"""Marker re-run on the FROZEN cohort with the hardened M-A detector.

Pre-registration integrity (HANDOFF_MARKER_HARDENING.md §"Sweep re-run"):
this is an INSTRUMENT FIX applied uniformly, NOT a cohort change or a
per-repo tweak. It does exactly one thing:

  for every PR ALREADY captured in the sweep (the exact unit_id/number set
  in each repo's prs.jsonl — frozen, not re-listed), re-fetch the marker
  inputs (PR body + commit messages + author identity), re-run the M-A
  detect_markers(), and rewrite ONLY the `ai_marked` block of that repo's
  audit JSON (+ the matching ai_markers/ai_model on each sidecar entry).

What it does NOT touch (so drift stays byte-identical and the PR slice
cannot shift): units.csv, survival, classifications, rework_tax,
churn_clusters, supersessions, velocity_context, abandoned, hotspots.
Re-scanning the SAME frozen PR numbers means no new PRs enter — the
slice the sweep measured is the slice we re-mark.

Resumable: each refreshed audit is stamped `ai_marked._detector = "M-A"` +
a UTC timestamp; a re-run skips repos already at M-A. Atomic per-repo
write (temp + rename) so an interrupt never leaves a half-written JSON.

Bodies/messages are scanned in-memory and never persisted — only the
marker RESULT + structured model are written (the bodies-off-disk stance).

Usage:
    GH_TOKEN=$(gh auth token) python3 sweep/marker_refresh.py \\
        --repo-list sweep/repo_list.json --sweep-out /tmp/commensa_sweep \\
        --stamp 2026-06-14T00:00:00Z [--limit N] [--force]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from commensa_audit.extractors.github import GitHubExtractor
from commensa_audit.markers import detect_markers

DETECTOR_TAG = "M-A"   # provenance stamp written into ai_marked._detector

METHOD_STRING = (
    "PRs with ≥1 agent marker (M-A hardened detector): Co-Authored-By / "
    "Assisted-by / Generated-by / On-behalf-of trailer naming a known agent "
    "identity, a body signature, or an author/committer identity matching the "
    "agent allowlist (GitHub web-UI noreply@github.com EXCLUDED). Lower bound "
    "— unmarked agent work is invisible; absence of a marker is NOT evidence "
    "of human authorship."
)


def _author_identity(pr: dict) -> str | None:
    user = pr.get("user") or {}
    login = user.get("login")
    return f"{login} <{login}@users.noreply.github.com>" if login else None


def _atomic_write(path: str, obj) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def refresh_repo(repo_full: str, repo_dir: str, token: str, stamp: str,
                 force: bool, log) -> dict | None:
    """Re-mark one repo. Returns a per-repo log row, or None if skipped."""
    audits = glob.glob(os.path.join(repo_dir, "audit_*.json"))
    sidecar_path = os.path.join(repo_dir, "prs.jsonl")
    if not audits or not os.path.exists(sidecar_path):
        log(f"  SKIP {repo_full}: missing audit/sidecar in {repo_dir}")
        return None
    audit_path = audits[0]
    audit = json.load(open(audit_path, encoding="utf-8"))

    old_am = audit.get("ai_marked", {})
    if old_am.get("_detector") == DETECTOR_TAG and not force:
        log(f"  SKIP {repo_full}: already at detector {DETECTOR_TAG}")
        return {"repo": repo_full, "skipped": True,
                "agent_marked_pct": old_am.get("pct_of_prs_lower_bound")}

    sidecar = [json.loads(l) for l in open(sidecar_path, encoding="utf-8") if l.strip()]
    extractor = GitHubExtractor(repo_full, token=token)

    new_per_unit: dict[str, list[str]] = {}
    new_per_model: dict[str, dict] = {}
    updated_sidecar: list[dict] = []

    unfetchable = 0
    for entry in sidecar:
        uid = entry["unit_id"]
        number = entry["number"]
        try:
            pr = extractor.fetch_pull(number)
            msgs = extractor.fetch_commit_messages(number)
            result = detect_markers(
                pr.get("body"), msgs,
                author_identity=_author_identity(pr),
            )
            markers, model = result["markers"], result["model"]
        except Exception as e:
            # A PR captured at sweep time can be deleted/transferred later
            # (404). Don't abort the repo — fall back to this unit's EXISTING
            # (pre-M-A) marker result so a marked PR isn't silently dropped.
            # Documented per-PR exception; preserves count honesty.
            unfetchable += 1
            markers = entry.get("ai_markers") or []
            model = entry.get("ai_model")
            log(f"    PR-{number} unfetchable ({str(e)[:40]}); kept prior marker")
        # rewrite the sidecar entry's marker fields (consistency); bodies/msgs
        # are NOT stored — only the result + model.
        entry["ai_markers"] = markers
        entry["ai_model"] = model
        updated_sidecar.append(entry)
        if markers:
            new_per_unit[uid] = markers
        if model:
            new_per_model[uid] = model

    total = audit["rework_tax"]["total_prs"]
    old_count = old_am.get("count", 0)
    old_pct = old_am.get("pct_of_prs_lower_bound", 0.0)
    new_count = len(new_per_unit)
    new_pct = round(100 * new_count / max(total, 1), 1)

    audit["ai_marked"] = {
        "count": new_count,
        "pct_of_prs_lower_bound": new_pct,
        "per_unit": new_per_unit,
        "per_unit_model": new_per_model,
        "method": METHOD_STRING,
        "_detector": DETECTOR_TAG,
        "_refreshed_utc": stamp,
        "_prev_detector_count": old_count,
        "_prev_detector_pct": old_pct,
    }

    # Atomic writes: audit first, then sidecar.
    _atomic_write(audit_path, audit)
    tmp_side = sidecar_path + ".tmp"
    with open(tmp_side, "w", encoding="utf-8") as f:
        for e in updated_sidecar:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp_side, sidecar_path)

    delta = new_count - old_count
    log(f"  {repo_full}: {old_count} ({old_pct}%) -> {new_count} ({new_pct}%)  "
        f"Δ{delta:+d}  models={len(new_per_model)}  api={extractor.requests}")
    return {
        "repo": repo_full, "total_prs": total,
        "old_count": old_count, "old_pct": old_pct,
        "new_count": new_count, "new_pct": new_pct,
        "delta": delta, "api_calls": extractor.requests,
    }


def _wait_for_rate(token: str, log, headroom: int = 500) -> None:
    """Sleep until core rate-limit recovers above headroom."""
    import urllib.request
    while True:
        req = urllib.request.Request(
            "https://api.github.com/rate_limit",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json",
                     "User-Agent": "commensa-marker-refresh"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                core = json.loads(r.read())["resources"]["core"]
        except Exception:
            return
        if core["remaining"] >= headroom:
            return
        nap = max(30, int(core["reset"]) - int(time.time()) + 5)
        log(f"  rate low ({core['remaining']}); sleep {min(nap,1800)}s")
        time.sleep(min(nap, 1800))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-list", required=True)
    ap.add_argument("--sweep-out", required=True)
    ap.add_argument("--stamp", required=True,
                    help="UTC timestamp string for the refresh provenance "
                         "(pass in; scripts can't call Date.now in some envs)")
    ap.add_argument("--limit", type=int, default=None,
                    help="process only the first N repos (dry-run / smoke)")
    ap.add_argument("--force", action="store_true",
                    help="re-mark even repos already stamped M-A")
    args = ap.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        token = subprocess.check_output(["gh", "auth", "token"]).decode().strip()

    rl = json.load(open(args.repo_list, encoding="utf-8"))
    cohort = ([(r["full"], "agent") for r in rl["agent_cohort"]]
              + [(r["full"], "baseline") for r in rl["baseline_cohort"]])
    if args.limit:
        cohort = cohort[:args.limit]

    log = lambda s: print(s, flush=True)
    log(f"=== marker refresh (instrument fix, frozen cohort) ===")
    log(f"detector       : {DETECTOR_TAG} (hardened)")
    log(f"cohort source  : {args.repo_list} (frozen {rl.get('frozen_at_utc')})")
    log(f"sweep out      : {args.sweep_out}")
    log(f"stamp          : {args.stamp}")
    log(f"repos          : {len(cohort)}")
    log(f"NOTE: drift (survival/rework/clusters) is NOT recomputed — only the")
    log(f"      ai_marked block is rewritten, on the SAME frozen PR set.")
    log("")

    rows = []
    for i, (repo_full, coh) in enumerate(cohort, 1):
        safe = repo_full.replace("/", "__")
        repo_dir = os.path.join(args.sweep_out, safe)
        if not os.path.isdir(repo_dir):
            # the sweep used owner__name; some may differ — glob fallback
            cands = glob.glob(os.path.join(args.sweep_out, f"*{repo_full.split('/')[-1]}*"))
            repo_dir = cands[0] if cands else repo_dir
        log(f"[{i}/{len(cohort)}] {repo_full} ({coh})")
        _wait_for_rate(token, log)
        try:
            row = refresh_repo(repo_full, repo_dir, token, args.stamp,
                               args.force, log)
            if row:
                row["cohort"] = coh
                rows.append(row)
        except Exception as e:
            log(f"  ERROR {repo_full}: {e}")
            rows.append({"repo": repo_full, "cohort": coh, "error": str(e)})

    # pre-registration audit log
    changed = [r for r in rows if r.get("delta") not in (None, 0) and not r.get("skipped")]
    total_api = sum(r.get("api_calls", 0) for r in rows)
    summary = {
        "refresh_utc": args.stamp,
        "detector_before": "pre-M-A (Claude/Copilot-era idents, trailers+body only)",
        "detector_after": f"{DETECTOR_TAG} (broadened idents + identity scan + "
                          f"Assisted/Generated/On-behalf-of trailers + model extraction)",
        "cohort_source": args.repo_list,
        "cohort_frozen_at": rl.get("frozen_at_utc"),
        "instrument_fix_only": True,
        "drift_recomputed": False,
        "pr_slice_changed": False,
        "repos_processed": len([r for r in rows if not r.get("error")]),
        "repos_with_marker_delta": len(changed),
        "total_api_calls": total_api,
        "per_repo": rows,
    }
    out_log = os.path.join(args.sweep_out, "marker_refresh_log.json")
    _atomic_write(out_log, summary)
    log("")
    log(f"=== DONE === processed={summary['repos_processed']} "
        f"with_delta={len(changed)} api_calls={total_api}")
    log(f"wrote {out_log}")


if __name__ == "__main__":
    main()
