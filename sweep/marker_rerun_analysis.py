"""Post-marker-refresh analysis — confidence-split.

Reads the refreshed sweep output (drift untouched, ai_marked now M-A) and the
two model_durability JSONs, and emits:
  - CONFIRMATORY: rework triad + survival, by cohort (drift = author-agnostic,
    NOT changed by the marker refresh).
  - Marker before/after: pre-M-A vs M-A agent-marked, by cohort (from each
    audit's embedded _prev_detector_count).
  - BOT-DECONTAMINATED marker view: M-A's identity scan + generic `[bot]`
    ident flags infrastructure/sync bots (copybara, dependabot, CI) as
    "agent." This view recounts agent-marked using ONLY AI-coding-agent
    identities, so the agent-vs-baseline contrast is readable without the
    bot confound.
  - EXPLORATORY: model durability (pulled from the two JSONs).

Output: cohort_marker_rerun.json (structured) — the memo is written by hand.
"""

from __future__ import annotations
import glob, json, os, statistics
from collections import defaultdict, Counter

SWEEP = "/tmp/commensa_sweep"
REPO_LIST = "/Users/mattbuscher/Documents/claude/AI_Stewardship_Cert/commensa-audit/sweep/repo_list.json"

# AI *coding* agents — the LLM authorship signal the thesis cares about.
# copilot[bot] / gemini-code-assist[bot] ARE AI agents (kept).
AI_CODING_AGENTS = [
    "claude", "anthropic", "copilot", "cursor", "codex", "openai", "chatgpt",
    "gemini", "devin", "aider", "code-assist", "lovable", "windsurf", "cline",
    "codeium", "sourcegraph", "cody", "tabnine", "supermaven", "amazon q",
    "codewhisperer", "augment", "continue",
]
# Infra / CI / sync / dependency bots — automation, NOT AI authorship.
INFRA_BOTS = [
    "copybara", "dependabot", "renovate", "jenkins", "github-actions",
    "mergify", "greenkeeper", "snyk", "pre-commit-ci", "allcontributors",
    "stale[bot]", "codecov", "netlify", "vercel[bot]", "sonarcloud",
]

def is_ai_agent_marker(marker: str) -> bool:
    low = marker.lower()
    return any(a in low for a in AI_CODING_AGENTS)

def is_infra_only(markers: list) -> bool:
    """True if EVERY marker is an infra bot and none is an AI coding agent."""
    if not markers:
        return False
    if any(is_ai_agent_marker(m) for m in markers):
        return False
    return any(any(b in m.lower() for b in INFRA_BOTS) for m in markers)

def iqr(vals):
    vals = sorted(v for v in vals if v is not None)
    if not vals: return None
    n = len(vals)
    med = vals[n//2] if n%2 else (vals[n//2-1]+vals[n//2])/2
    return {"n": n, "median": round(med,2), "q1": round(vals[n//4],2),
            "q3": round(vals[(3*n)//4],2)}

def main():
    rl = json.load(open(REPO_LIST))
    cohort = {}
    for r in rl["agent_cohort"]: cohort[r["full"].split("/")[-1]] = ("agent", r["full"])
    for r in rl["baseline_cohort"]: cohort[r["full"].split("/")[-1]] = ("baseline", r["full"])

    rows = []
    for p in sorted(glob.glob(f"{SWEEP}/*/audit_*.json")):
        a = json.load(open(p))
        repo = a["repo"]
        coh = cohort.get(repo, (None, repo))[0]
        if coh is None:
            # try full-name match
            for short,(c,full) in cohort.items():
                if full == repo or full.endswith("/"+repo): coh=c; break
        am = a["ai_marked"]
        per = am.get("per_unit") or {}
        total = a["rework_tax"]["total_prs"]
        # bot-decontaminated count: units with >=1 AI-agent marker
        ai_count = sum(1 for markers in per.values()
                       if any(is_ai_agent_marker(m) for m in markers))
        infra_only = sum(1 for markers in per.values() if is_infra_only(markers))
        rows.append({
            "repo": repo, "cohort": coh, "total_prs": total,
            "corrective_line_pct": a["rework_tax"]["pct_changed_lines_corrective"],
            "corrective_pr_pct": a["rework_tax"]["pct_prs_corrective"],
            "merge_rate": a["velocity_context"]["merge_rate"],
            "survival_overall": a["survival"]["overall_rate"],
            "merged_pr_count": sum(1 for v in (a["survival"]["per_unit"] or {}).values() if v is not None),
            "marked_MA": am["count"],
            "marked_MA_pct": am["pct_of_prs_lower_bound"],
            "marked_prev": am.get("_prev_detector_count"),
            "marked_ai_only": ai_count,
            "marked_ai_only_pct": round(100*ai_count/max(total,1),1),
            "infra_only_units": infra_only,
        })

    def by_cohort(key, gate_survival=False):
        out = {}
        for coh in ("agent","baseline"):
            members = [r for r in rows if r["cohort"]==coh]
            if gate_survival:
                vals = [r[key] for r in members if r["merged_pr_count"]>=30]
            else:
                vals = [r[key] for r in members]
            out[coh] = iqr(vals)
        return out

    confirmatory = {
        "corrective_line_pct": by_cohort("corrective_line_pct"),
        "merge_rate": by_cohort("merge_rate"),
        "corrective_pr_pct": by_cohort("corrective_pr_pct"),
        "survival_overall_gated_n>=30": by_cohort("survival_overall", gate_survival=True),
    }

    # marker before/after + bot-decontamination, by cohort
    marker_view = {}
    for coh in ("agent","baseline"):
        members = [r for r in rows if r["cohort"]==coh]
        marker_view[coh] = {
            "n_repos": len(members),
            "agent_marked_pct_MA": iqr([r["marked_MA_pct"] for r in members]),
            "agent_marked_pct_ai_only": iqr([r["marked_ai_only_pct"] for r in members]),
            "agent_marked_pct_prev": iqr([round(100*(r["marked_prev"] or 0)/max(r["total_prs"],1),1) for r in members]),
            "total_marked_MA": sum(r["marked_MA"] for r in members),
            "total_marked_ai_only": sum(r["marked_ai_only"] for r in members),
            "total_infra_only_units": sum(r["infra_only_units"] for r in members),
        }

    # repos most inflated by infra bots
    inflated = sorted(rows, key=lambda r: -r["infra_only_units"])[:10]

    out = {
        "n_repos": len(rows),
        "confirmatory_triad_by_cohort": confirmatory,
        "marker_view_by_cohort": marker_view,
        "top_infra_inflated_repos": [
            {"repo": r["repo"], "cohort": r["cohort"],
             "marked_MA": r["marked_MA"], "marked_ai_only": r["marked_ai_only"],
             "infra_only_units": r["infra_only_units"]} for r in inflated],
        "model_durability_age90": json.load(open(f"{SWEEP}/model_durability_age90.json")),
        "model_durability_age0": json.load(open(f"{SWEEP}/model_durability_age0.json")),
    }
    json.dump(out, open(f"{SWEEP}/cohort_marker_rerun.json","w"), indent=2)

    # console summary
    print("=== CONFIRMATORY triad + survival (drift — UNCHANGED by marker refresh) ===")
    for metric, d in confirmatory.items():
        a, b = d["agent"], d["baseline"]
        fa = f"{a['median']} [{a['q1']}-{a['q3']}] n={a['n']}" if a else "n/a"
        fb = f"{b['median']} [{b['q1']}-{b['q3']}] n={b['n']}" if b else "n/a"
        print(f"  {metric:34s} agent={fa:28s} baseline={fb}")
    print()
    print("=== MARKER VIEW by cohort: raw M-A vs AI-only (bot-decontaminated) ===")
    for coh in ("agent","baseline"):
        m = marker_view[coh]
        print(f"  {coh:9s} agent-marked% median  M-A={m['agent_marked_pct_MA']['median']:>5}  "
              f"AI-only={m['agent_marked_pct_ai_only']['median']:>5}  "
              f"(prev={m['agent_marked_pct_prev']['median']:>5})")
        print(f"            total marked units  M-A={m['total_marked_MA']:>5}  "
              f"AI-only={m['total_marked_ai_only']:>5}  "
              f"infra-only(excluded)={m['total_infra_only_units']:>5}")
    print()
    print("=== Top infra-bot-inflated repos (M-A count vs AI-only) ===")
    for r in inflated[:8]:
        print(f"  {r['repo']:28s} {r['cohort']:8s} M-A={r['marked_MA']:>4}  "
              f"AI-only={r['marked_ai_only']:>4}  infra-only={r['infra_only_units']:>4}")
    print(f"\nwrote {SWEEP}/cohort_marker_rerun.json")

if __name__ == "__main__":
    main()
