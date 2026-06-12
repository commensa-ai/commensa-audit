"""Resumable batch driver for the OSS benchmark sweep.

Reads the frozen repo_list.json (cohort_select.py output), runs the PUBLISHED
commensa-audit 0.3.0 binary against every repo with IDENTICAL flags, captures
per-repo summary metrics into runlog.jsonl, and continues on failure.

Resumability: skips any repo whose output dir already holds an audit_*.json.
Killable + restartable — the cohort list is frozen so re-runs are deterministic.

Politeness: before each repo, checks core rate-limit; if remaining < HEADROOM,
sleeps until reset. Per-repo audits naturally throttle themselves via the
extractor's existing 429/Retry-After handling.

Per protocol: same CONFIG for every repo (no per-repo tuning). No aggregation
here — analysis happens after the run completes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
import time
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError

WINDOW_DAYS = 90
MAX_PRS = 150
RATE_HEADROOM = 500    # if core remaining < this, sleep until reset
RUNLOG_NAME = "runlog.jsonl"


def _since_date(days: int) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).date().isoformat()


def _check_rate(token: str) -> dict:
    req = Request("https://api.github.com/rate_limit",
                  headers={"Authorization": f"Bearer {token}",
                           "Accept": "application/vnd.github+json",
                           "User-Agent": "commensa-sweep-runner"})
    try:
        with urlopen(req, timeout=20) as r:
            return json.loads(r.read())["resources"]["core"]
    except HTTPError:
        return {"remaining": 5000, "reset": int(time.time()) + 3600}


def _wait_for_rate(token: str, log) -> None:
    while True:
        c = _check_rate(token)
        if c["remaining"] >= RATE_HEADROOM:
            return
        nap = max(30, int(c["reset"]) - int(time.time()) + 5)
        log(f"  core remaining={c['remaining']} < {RATE_HEADROOM}; sleep {nap}s "
            f"until {dt.datetime.fromtimestamp(int(c['reset'])).isoformat(timespec='seconds')}")
        time.sleep(min(nap, 1800))


def _summarize(audit: dict, units_path: Optional[str], err: Optional[str]) -> dict:
    if err or not audit:
        return {"error": err or "no_audit_json"}
    rt = audit.get("rework_tax", {})
    sv = audit.get("survival", {})
    ai = audit.get("ai_marked", {})
    ab = audit.get("abandoned", {})
    vc = audit.get("velocity_context", {})
    n_merged_with_survival = sum(
        1 for v in (sv.get("per_unit") or {}).values() if v is not None)
    return {
        "repo": audit.get("repo"),
        "window_days": audit.get("window_days"),
        "rework_tax": {
            "corrective_prs": rt.get("corrective_prs"),
            "total_prs": rt.get("total_prs"),
            "pct_prs_corrective": rt.get("pct_prs_corrective"),
            "pct_changed_lines_corrective": rt.get("pct_changed_lines_corrective"),
            "by_signal": rt.get("by_signal"),
        },
        "churn_clusters": len(audit.get("churn_clusters") or []),
        "supersession_count": len(audit.get("supersessions") or {}),
        "survival": {
            "overall_rate": sv.get("overall_rate"),
            "median_rate": sv.get("median_rate"),
            "n_merged_with_survival": n_merged_with_survival,
        },
        "ai_marked": {
            "count": ai.get("count"),
            "pct_of_prs_lower_bound": ai.get("pct_of_prs_lower_bound"),
        },
        "abandoned": {
            "count": ab.get("count"),
            "pct_of_prs": ab.get("pct_of_prs"),
            "in_flight_open_prs": ab.get("in_flight_open_prs"),
        },
        "velocity": {
            "prs_per_week": vc.get("prs_per_week"),
            "merge_rate": vc.get("merge_rate"),
        },
    }


def _run_one(binary: str, owner: str, name: str, out_dir: str,
             since: str, token: str, log) -> dict:
    """Run a single audit. Returns the runlog row."""
    full = f"{owner}/{name}"
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    t0 = time.time()
    env = dict(os.environ, GH_TOKEN=token)
    proc = subprocess.run(
        [binary, "--repo", full, "--since", since, "--max-prs", str(MAX_PRS),
         "--out", out_dir],
        capture_output=True, text=True, env=env, timeout=3600,
    )
    runtime = round(time.time() - t0, 1)
    finished = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    # Parse "(<N> GitHub API calls)" line from stderr for honest cost report
    api_calls = None
    for line in (proc.stderr or "").splitlines():
        m = re.search(r"(\d+)\s+GitHub API calls", line)
        if m:
            api_calls = int(m.group(1))

    # Locate the audit JSON the tool wrote (filename derived from owner/name)
    audit, audit_path, err = None, None, None
    cands = sorted(glob.glob(os.path.join(out_dir, "audit_*.json")))
    if cands:
        audit_path = cands[0]
        try:
            audit = json.load(open(audit_path, encoding="utf-8"))
        except Exception as e:
            err = f"audit_json_parse_error:{e}"
    elif proc.returncode != 0:
        err = f"audit_exit={proc.returncode}; stderr_tail={(proc.stderr or '')[-300:]}"
    else:
        err = "audit_completed_but_no_json_written"

    summary = _summarize(audit, None, err)
    row = {
        "full": full,
        "started_utc": started,
        "finished_utc": finished,
        "runtime_sec": runtime,
        "exit_code": proc.returncode,
        "api_calls": api_calls,
        "out_dir": out_dir,
        "audit_path": audit_path,
        "summary": summary,
        "stderr_tail": (proc.stderr or "")[-200:],
    }
    log(f"  {full}: exit={proc.returncode} runtime={runtime}s api={api_calls} "
        f"PRs={summary.get('rework_tax',{}).get('total_prs')} err={err}")
    return row


def _append_runlog(runlog_path: str, row: dict) -> None:
    with open(runlog_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _already_done(out_dir: str) -> bool:
    return bool(glob.glob(os.path.join(out_dir, "audit_*.json")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-list", required=True,
                    help="frozen repo_list.json from cohort_select.py")
    ap.add_argument("--out", required=True,
                    help="root output dir (one subdir per repo)")
    ap.add_argument("--binary", required=True,
                    help="path to the published commensa-audit binary")
    args = ap.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        token = subprocess.check_output(["gh", "auth", "token"]).decode().strip()
    if not token:
        sys.exit("no GitHub token (set GH_TOKEN)")

    rl = json.load(open(args.repo_list, encoding="utf-8"))
    cohort = list(rl["agent_cohort"]) + list(rl["baseline_cohort"])
    os.makedirs(args.out, exist_ok=True)
    runlog_path = os.path.join(args.out, RUNLOG_NAME)
    since = _since_date(WINDOW_DAYS)

    log = lambda s: print(s, flush=True)
    log(f"=== OSS sweep run ===")
    log(f"started_utc      : {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}")
    log(f"tool_version     : {rl.get('tool_version')}")
    log(f"protocol         : {rl.get('protocol')}")
    log(f"repo_list_frozen : {rl.get('frozen_at_utc')}")
    log(f"binary           : {args.binary}")
    log(f"out_root         : {args.out}")
    log(f"--since          : {since}")
    log(f"--max-prs        : {MAX_PRS}")
    log(f"cohort size      : {len(cohort)} "
        f"(agent={len(rl['agent_cohort'])}, baseline={len(rl['baseline_cohort'])})")
    log("")

    done = skipped = failed = 0
    t_start = time.time()
    for i, repo in enumerate(cohort, 1):
        full = repo["full"]
        owner, name = full.split("/", 1)
        safe = f"{owner}__{name}".replace("/", "__")
        out_dir = os.path.join(args.out, safe)
        os.makedirs(out_dir, exist_ok=True)

        if _already_done(out_dir):
            log(f"[{i}/{len(cohort)}] SKIP (already audited): {full}")
            skipped += 1
            continue

        _wait_for_rate(token, log)
        log(f"[{i}/{len(cohort)}] AUDIT {full}  cohort={repo['cohort']}  "
            f"band={repo['size_band']}  stars={repo['stars']}")
        try:
            row = _run_one(args.binary, owner, name, out_dir, since, token, log)
            row["cohort"] = repo["cohort"]
            row["size_band"] = repo["size_band"]
            row["stars"] = repo["stars"]
            row["language"] = repo.get("language")
            _append_runlog(runlog_path, row)
            if row.get("exit_code") == 0 and not row["summary"].get("error"):
                done += 1
            else:
                failed += 1
        except subprocess.TimeoutExpired:
            failed += 1
            _append_runlog(runlog_path, {
                "full": full, "cohort": repo["cohort"], "error": "timeout_3600s",
                "finished_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
            log(f"  {full}: TIMEOUT after 3600s")
        except Exception as e:
            failed += 1
            _append_runlog(runlog_path, {
                "full": full, "cohort": repo["cohort"], "error": f"exception:{e}",
                "finished_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
            log(f"  {full}: EXCEPTION {e}")

    elapsed = int(time.time() - t_start)
    log(f"\n=== DONE === processed={done+failed+skipped} done={done} "
        f"skipped={skipped} failed={failed} elapsed={elapsed}s")


if __name__ == "__main__":
    main()
