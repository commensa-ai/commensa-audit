"""commensa-audit CLI.

Pipeline: extract → units.csv + prs.jsonl → classify (corrective vs
generative) + churn clusters + supersession + survival + v1.1 additions
(abandoned attempts, module hotspots, agent-marked lower bound) →
audit_<repo>.json + the one-page HTML report.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys

from . import __version__
from .classify import CONFIG, classify
from .extractors.github import GitHubExtractor
from .extractors.local_clone import LocalCloneExtractor
from .rework import replay
from .units import read_units_csv, write_units_csv


DEFAULT_MAX_PRS = 500  # safety cap so a naive run on a huge repo isn't unbounded


def _since_date(s: str) -> str:
    """argparse type: accept only an ISO YYYY-MM-DD date."""
    from datetime import datetime
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(f"--since must be YYYY-MM-DD, got {s!r}")
    return s


def _non_negative_int(s: str) -> int:
    """argparse type for --max-prs: an int >= 0 (0 = no cap)."""
    try:
        v = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--max-prs must be an integer, got {s!r}")
    if v < 0:
        raise argparse.ArgumentTypeError(f"--max-prs must be >= 0 (0 = no cap), got {v}")
    return v


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="commensa-audit",
        description="Point it at a GitHub repo (PR-mode) OR a local git clone "
                    "(commit-mode), get an AI Rework Report. Drift measurement is "
                    "author-agnostic — what survived, what was rewritten — so the "
                    "same engine reads both modes.")
    # PR-mode (network) vs commit-mode (local-only) — exactly one is required.
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--repo", metavar="owner/name",
                        help="GitHub repository to audit (PR-mode, read-only)")
    source.add_argument("--local-clone", metavar="PATH", dest="local_clone",
                        help="local git clone to audit (commit-mode, "
                             "read-only, NO network)")
    ap.add_argument("--token", default=None,
                    help="GitHub token (default: $GH_TOKEN or $GITHUB_TOKEN); "
                         "read scope is sufficient. Ignored in commit-mode.")
    ap.add_argument("--window", type=int, default=CONFIG["window_days"], metavar="DAYS",
                    help=f"self-correction/churn/supersession window in days "
                         f"(default {CONFIG['window_days']})")
    cost = ap.add_mutually_exclusive_group()
    cost.add_argument("--cost-per-pr", type=float, metavar="USD",
                      help="estimated all-in cost per PR for the dollar line")
    cost.add_argument("--ai-spend", type=float, metavar="USD",
                      help="total AI spend over the audited period for the dollar line")
    ap.add_argument("--since", type=_since_date, default=None, metavar="YYYY-MM-DD",
                    help="only audit PRs created on/after this UTC date "
                         "(default: all history)")
    ap.add_argument("--max-prs", type=_non_negative_int, default=DEFAULT_MAX_PRS,
                    metavar="N",
                    help=f"cap to the N newest PRs (default {DEFAULT_MAX_PRS}; "
                         f"0 = no cap). Combine with --since for cheap windowed "
                         f"audits of large repos")
    ap.add_argument("--out", default=".", metavar="DIR",
                    help="output directory (default: current dir)")
    ap.add_argument("--reuse", action="store_true",
                    help="reuse units.csv + prs.jsonl already in --out instead of "
                         "re-hitting the API (offline re-classification)")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return ap


def _extract(args, token) -> tuple[list[dict], list[dict]]:
    units_path = os.path.join(args.out, "units.csv")
    sidecar_path = os.path.join(args.out, "prs.jsonl")

    if args.reuse and os.path.exists(units_path) and os.path.exists(sidecar_path):
        print(f"reusing {units_path} + {sidecar_path} (no API calls)", file=sys.stderr)
        units = read_units_csv(units_path)
        with open(sidecar_path, encoding="utf-8") as f:
            sidecar = [json.loads(line) for line in f if line.strip()]
        return units, sidecar

    if args.local_clone:
        return _extract_local(args, units_path, sidecar_path)

    extractor = GitHubExtractor(args.repo, token=token)

    def progress(i, total):
        if i == 1 or i % 25 == 0 or i == total:
            print(f"  PR {i}/{total}", file=sys.stderr)

    scope = ", ".join(
        b for b in (f"since {args.since}" if args.since else "",
                    f"newest {args.max_prs}" if args.max_prs else "") if b)
    scope = f" [{scope}]" if scope else ""
    print(f"extracting PRs + file patches from {args.repo} (read-only){scope}…",
          file=sys.stderr)
    units, sidecar = [], []
    with open(sidecar_path, "w", encoding="utf-8") as f:
        for unit, side in extractor.units(progress=progress, with_files=True,
                                          since=args.since, max_prs=args.max_prs):
            units.append(unit)
            sidecar.append(side)
            f.write(json.dumps(side, ensure_ascii=False) + "\n")
    write_units_csv(units_path, units)
    print(f"wrote {len(units)} units -> {units_path} "
          f"({extractor.requests} GitHub API calls)", file=sys.stderr)
    if extractor.capped:
        print(f"NOTE: capped at the newest {args.max_prs} PRs — this repo has more. "
              f"Raise with --max-prs N (default {DEFAULT_MAX_PRS}), or --max-prs 0 "
              f"for no cap.", file=sys.stderr)
    return units, sidecar


def _extract_local(args, units_path: str, sidecar_path: str) -> tuple[list[dict], list[dict]]:
    """Commit-mode extraction: local git clone, no network. The extractor's
    units() yields (unit_row, sidecar_row) tuples mirroring the GitHub shape,
    so the engine downstream consumes them unchanged."""
    extractor = LocalCloneExtractor(args.local_clone)
    scope = f" [since {args.since}]" if args.since else ""
    print(f"extracting commits from local clone {args.local_clone} "
          f"(read-only, no network){scope}…", file=sys.stderr)
    units, sidecar = [], []
    n = 0
    with open(sidecar_path, "w", encoding="utf-8") as f:
        for unit, side in extractor.units(with_files=True, since=args.since):
            units.append(unit)
            sidecar.append(side)
            f.write(json.dumps(side, ensure_ascii=False) + "\n")
            n += 1
            if n == 1 or n % 50 == 0:
                print(f"  commit {n}", file=sys.stderr)
    print(f"  commit {n} (done)", file=sys.stderr)
    write_units_csv(units_path, units)
    print(f"wrote {len(units)} units -> {units_path} "
          f"(2 local git invocations, no API calls)", file=sys.stderr)
    return units, sidecar


def _aggregate(units, res, result, args, sidecar) -> dict:
    cls = result["classifications"]
    side = {s["unit_id"]: s for s in sidecar}
    corrective = [u for u in units if cls[u["unit_id"]]["classification"] == "corrective"]
    churn = lambda u: u["lines_added"] + u["lines_deleted"]  # noqa: E731
    total_churn = sum(churn(u) for u in units) or 1
    merged = [u for u in units if u["merged"]]

    # velocity context — context only, never a target (LOC-trap guardrail)
    n = max(len(units), 1)  # a 0-PR repo audits to zeros, not a crash
    times = sorted(u["created_at"] for u in units)
    weeks = max((_iso(times[-1]) - _iso(times[0])) / (7 * 86400), 1 / 7) if len(times) > 1 else 1 / 7
    sizes = sorted(u["lines_added"] for u in units) or [0]
    q = lambda p: sizes[min(int(p * len(sizes)), len(sizes) - 1)]  # noqa: E731

    survival_rates = {
        uid: (res.surviving.get(uid, 0) / a) if (a := res.added.get(uid, 0)) else None
        for uid in res.added
    }
    rated = [v for v in survival_rates.values() if v is not None]

    out = {
        "repo": args.repo,
        "window_days": args.window,
        "rework_tax": {
            "pct_prs_corrective": round(100 * len(corrective) / n, 1),
            "pct_changed_lines_corrective": round(
                100 * sum(churn(u) for u in corrective) / total_churn, 1),
            "corrective_prs": len(corrective),
            "total_prs": len(units),
            "by_signal": _by_signal(cls),
        },
        "churn_clusters": result["clusters"],
        "supersessions": result["superseded"],
        "survival": {
            "method": "line-attribution replay of PR patches (see rework.py docstring "
                      "for limits: exact-content match, trivial lines excluded, "
                      "renames followed via PR file entries, direct pushes invisible)",
            "overall_rate": round(sum(res.surviving.values()) / max(sum(res.added.values()), 1), 3),
            "median_rate": round(statistics.median(rated), 3) if rated else None,
            "per_unit": {k: (round(v, 3) if v is not None else None)
                         for k, v in survival_rates.items()},
        },
        "velocity_context": {
            "prs_per_week": round(len(units) / weeks, 1),
            "merge_rate": round(100 * len(merged) / n, 1),
            "size_lines_added": {"p25": q(.25), "median": q(.5), "p75": q(.75), "max": sizes[-1]},
            "note": "context only — velocity is never a target (LOC trap)",
        },
        "abandoned": _abandoned(units, side),
        "hotspots": _hotspots(units, cls, side),
        "ai_marked": _ai_marked(units, side),
        # v1.1 §4 — external published norms for the context line. Source:
        # ../references/competition.md "Code Turnover Rate" figures
        # (larridin.com developer-productivity-hub). NOT a Commensa benchmark.
        "external_norms": {
            "metric": "Code Turnover Rate — share of merged code reverted/rewritten within 30 days",
            "healthy": "< 15%",
            "ai_vs_human": "AI-assisted teams measured at 1.8–2.5× human baselines "
                           "(target < 1.5×)",
            "label": "external published research, not a Commensa benchmark; "
                     "methods differ from the rework tax above",
        },
        "classifications": {u["unit_id"]: cls[u["unit_id"]] for u in units},
        "config": result["config"],
        "confidence_notes": [
            "classification is heuristic; every PR carries the signal that fired",
            "survival/supersession use exact-content line attribution from PR patches; "
            "squash merges, direct pushes, and moved lines limit attribution",
            "no token, model, or energy claims — git does not record them",
        ],
    }

    # dollar translation — clearly labeled estimate (SPEC metric 1)
    if args.cost_per_pr:
        out["rework_tax"]["estimated_rework_cost_usd"] = round(
            args.cost_per_pr * len(corrective), 2)
        out["rework_tax"]["estimate_basis"] = (
            f"${args.cost_per_pr:,.0f} per PR (your input) × {len(corrective)} corrective PRs")
    elif args.ai_spend:
        share = sum(churn(u) for u in corrective) / total_churn
        out["rework_tax"]["estimated_rework_cost_usd"] = round(args.ai_spend * share, 2)
        out["rework_tax"]["estimate_basis"] = (
            f"${args.ai_spend:,.0f} total AI spend (your input) × {round(100 * share, 1)}% corrective share of changed lines")
    return out


def _abandoned(units, side) -> dict:
    """v1.1 §1 — closed-unmerged PRs: attempts that shipped nothing. Open
    PRs are in-flight, not abandoned, and are excluded (counted separately)."""
    closed_unmerged = [u["unit_id"] for u in units if not u["merged"]
                       and (side.get(u["unit_id"], {}).get("state") == "closed")]
    in_flight = [u["unit_id"] for u in units if not u["merged"]
                 and (side.get(u["unit_id"], {}).get("state") == "open")]
    return {
        "count": len(closed_unmerged),
        "pct_of_prs": round(100 * len(closed_unmerged) / max(len(units), 1), 1),
        "units": closed_unmerged,
        "in_flight_open_prs": len(in_flight),
        "method": "PRs closed without merging (GitHub state=closed, merged_at null). "
                  "Invisible to merge-based metrics; open PRs are in-flight, not counted.",
    }


def _hotspots(units, cls, side, min_prs: int = 5, top_n: int = 5) -> dict:
    """v1.1 §2 — corrective share by top-level directory. A PR counts in
    every top-level dir it touches (PRs span modules); dirs with < min_prs
    PRs are suppressed as noise."""
    per_dir: dict[str, dict] = {}
    for u in units:
        files = side.get(u["unit_id"], {}).get("files") or []
        dirs = {f["filename"].split("/")[0] if "/" in f["filename"] else "(root)"
                for f in files}
        corrective = cls[u["unit_id"]]["classification"] == "corrective"
        for d in dirs:
            slot = per_dir.setdefault(d, {"prs": 0, "corrective": 0})
            slot["prs"] += 1
            slot["corrective"] += corrective
    rows = [dict(dir=d, prs=v["prs"], corrective=v["corrective"],
                 pct_corrective=round(100 * v["corrective"] / v["prs"], 1))
            for d, v in per_dir.items() if v["prs"] >= min_prs]
    rows.sort(key=lambda r: (-r["pct_corrective"], -r["prs"], r["dir"]))
    return {
        "top": rows[:top_n],
        "min_prs": min_prs,
        "suppressed_dirs": len(per_dir) - len(rows),
        "method": f"corrective share of PRs touching each top-level directory; a PR "
                  f"counts in every directory it touches; dirs with <{min_prs} PRs suppressed.",
    }


def _ai_marked(units, side) -> dict:
    """v1.1 §3 — LOWER BOUND share of PRs carrying agent markers
    (Co-Authored-By agent trailers in commits + body signatures)."""
    marked = {u["unit_id"]: m for u in units
              if (m := side.get(u["unit_id"], {}).get("ai_markers"))}
    return {
        "count": len(marked),
        "pct_of_prs_lower_bound": round(100 * len(marked) / max(len(units), 1), 1),
        "per_unit": marked,
        "method": "PRs with ≥1 agent marker: Co-Authored-By trailer naming a known "
                  "agent identity (commit messages, capped at 250 commits/PR by the "
                  "API) or a tool signature in the PR body. Lower bound — unmarked "
                  "agent work is invisible; absence of a marker is not evidence of "
                  "human authorship.",
    }


def _by_signal(cls: dict) -> dict:
    counts: dict[str, int] = {}
    for c in cls.values():
        if c["classification"] == "corrective":
            counts[c["signal"]] = counts.get(c["signal"], 0) + 1
    return counts


def _iso(s: str) -> float:
    from datetime import datetime
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def _survival_summary(survival: dict) -> str:
    """One-liner for the stdout summary. With no merged-line attribution the
    overall_rate is a 0/1 fallback — printing it as '0%' reads as 'everything
    was discarded' rather than 'no data', so guard on the same has_lines signal
    the report uses (report.py:render)."""
    has_lines = any(v is not None for v in survival["per_unit"].values())
    return ("overall line survival: "
            + (f"{survival['overall_rate']:.0%}" if has_lines
               else "no merged PR lines to measure yet"))


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    # commit-mode: derive a repo-style label from the path basename so the
    # rest of the pipeline (audit JSON, report header) treats it like any repo.
    if args.local_clone and not args.repo:
        # abspath first so "." resolves to the actual directory name
        args.repo = os.path.basename(os.path.abspath(args.local_clone)) or "local"
    token = args.token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token and not args.reuse and not args.local_clone:
        print("warning: no token — unauthenticated GitHub API is limited to 60 req/hr, "
              "which a repo with >25 PRs will exhaust (two requests per PR)", file=sys.stderr)

    os.makedirs(args.out, exist_ok=True)
    try:
        units, sidecar = _extract(args, token)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    # raw titles for the classifier (units.csv titles are sanitized)
    raw = {s["unit_id"]: s.get("raw_title") for s in sidecar}
    for u in units:
        u["raw_title"] = raw.get(u["unit_id"]) or u["title"]

    config = dict(CONFIG, window_days=args.window)
    res = replay(sidecar)
    result = classify(units, res, config)
    audit = _aggregate(units, res, result, args, sidecar)

    name = args.repo.split("/")[-1]
    audit_path = os.path.join(args.out, f"audit_{name}.json")
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, ensure_ascii=False)

    from datetime import date
    from .report import render
    report_path = os.path.join(args.out, f"report_{name}_{date.today().isoformat()}.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(render(audit, units))

    rt = audit["rework_tax"]
    print(f"\n{rt['pct_prs_corrective']}% of PRs ({rt['corrective_prs']}/{rt['total_prs']}) "
          f"and {rt['pct_changed_lines_corrective']}% of changed lines were corrective")
    print(f"churn clusters: {len(audit['churn_clusters'])}  ·  "
          f"superseded PRs: {len(audit['supersessions'])}  ·  "
          f"{_survival_summary(audit['survival'])}")
    print(f"audit  -> {audit_path}")
    print(f"report -> {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
