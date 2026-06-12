"""Mechanical cohort selection for the OSS benchmark sweep.

Implements oss_sweep_protocol.md verbatim:
  - Agent cohort (~50): GitHub search for agent markers (Co-Authored-By: Claude,
    Generated with [Claude Code], Copilot-agent, openai-codex), filtered by
    ≥30 merged PRs in 180d, ≥2 contributors, not a fork, not archived,
    not docs-only. Size bands small <50 / medium 50–150 / large >150
    PRs in last 90d. Take top N per band stars-descending.
  - Baseline cohort (~50): repos created pre-2023, active in last 90 days,
    <5% agent-marked share (proxy via search for the same marker strings in
    recent PRs + commits), same hygiene filters and size bands.

Outputs:
  repo_list.json     — frozen final cohort (with selection metadata)
  exclusion_log.json — every candidate skipped + the filter that killed it

DETERMINISTIC: every iteration order is sorted, every search query is
fixed-string, every threshold is named at module level. Re-running produces
the same list unless GitHub's underlying data changes.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import defaultdict, OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ---- Protocol parameters (locked) -----------------------------------------

PROTOCOL_VERSION = "oss_sweep_protocol.md @ AI_Stewardship_Cert"
TOOL_VERSION = "commensa-audit 0.3.0"
TARGET_PER_BAND = 17                  # 3 bands × 17 ≈ 51 ≈ "~50" per cohort
WINDOW_DAYS = 90
ACTIVITY_DAYS = 180                   # ≥30 merged PRs in 180d
MIN_PRS_180D = 30
SMALL_LT = 50                         # PRs/90d
LARGE_GT = 150
MIN_CONTRIBUTORS = 2
BASELINE_MARKER_THRESHOLD = 0.05      # <5% agent-marked share
BASELINE_CREATED_BEFORE = "2023-01-01"
BASELINE_MIN_STARS = 100              # filter floor so we don't enrich noise
AGENT_MIN_STARS = 5                   # agent cohort has lower bar (newer repos)
ENRICH_CAP_PER_COHORT = 250           # cap enrichment list size (rate-budget guard)

DOCS_ONLY_LANGUAGES = {"Markdown", "AsciiDoc", "reStructuredText", "TeX",
                       "Roff", "HTML", None}

# Marker query strings — covers the protocol's named patterns.
AGENT_MARKER_QUERIES = [
    # /search/commits
    ('commits', '"Co-Authored-By: Claude"'),
    ('commits', '"Co-authored-by: openai-codex"'),
    ('commits', '"Co-authored-by: Copilot"'),
    # /search/issues — body signatures in PRs
    ('issues',  '"Generated with [Claude Code]" type:pr'),
    ('issues',  '"Co-authored by Cursor" type:pr'),
]

# Languages to sweep across for baseline diversity (top OSS languages)
BASELINE_LANGUAGES = ["Python", "JavaScript", "TypeScript", "Go",
                      "Rust", "Java", "C++"]

# ---- HTTP transport with throttling ---------------------------------------

API = "https://api.github.com"


class GitHub:
    def __init__(self, token: str, log=sys.stderr):
        self.token = token
        self.log = log
        self.core_calls = 0
        self.search_calls = 0
        self._last_search = 0.0

    def _wait_search(self):
        # 30 req/min => 1 every 2.05s. Be polite.
        gap = 2.05
        delta = time.time() - self._last_search
        if delta < gap:
            time.sleep(gap - delta)
        self._last_search = time.time()

    def _request(self, path: str, *, is_search: bool, accept: str | None = None) -> dict:
        if is_search:
            self._wait_search()
        url = path if path.startswith("http") else f"{API}{path}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": accept or "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": "commensa-sweep-cohort-select",
        }
        for attempt in range(5):
            req = Request(url, headers=headers)
            try:
                with urlopen(req, timeout=30) as resp:
                    body = resp.read()
            except HTTPError as e:
                if e.code in (403, 429):
                    reset = e.headers.get("X-RateLimit-Reset")
                    wait = max(5, int(reset) - int(time.time()) + 1) if reset else 60
                    self.log.write(f"  rate-limited {e.code}; sleep {wait}s\n")
                    time.sleep(min(wait, 300))
                    continue
                if e.code == 404:
                    return {"_status": 404}
                if e.code == 422:
                    return {"_status": 422, "_message": e.read().decode("utf-8", "replace")[:200]}
                if e.code >= 500:
                    time.sleep(2 ** attempt)
                    continue
                raise
            except URLError:
                time.sleep(2 ** attempt)
                continue
            if is_search:
                self.search_calls += 1
            else:
                self.core_calls += 1
            return json.loads(body)
        raise RuntimeError(f"retries exhausted for {url}")

    def repo(self, full: str) -> dict:
        return self._request(f"/repos/{full}", is_search=False)

    def contributors_count_ge2(self, full: str) -> bool:
        r = self._request(f"/repos/{full}/contributors?per_page=2&anon=1",
                          is_search=False)
        if isinstance(r, dict) and r.get("_status") == 404:
            return False
        return isinstance(r, list) and len(r) >= 2

    def search_issues_count(self, q: str) -> int:
        path = f"/search/issues?q={quote(q)}&per_page=1"
        r = self._request(path, is_search=True)
        return r.get("total_count", 0) if isinstance(r, dict) else 0

    def search_issues_pages(self, q: str, max_pages: int = 5) -> list[dict]:
        items = []
        for page in range(1, max_pages + 1):
            path = f"/search/issues?q={quote(q)}&sort=created&order=desc&per_page=100&page={page}"
            r = self._request(path, is_search=True)
            page_items = r.get("items", []) if isinstance(r, dict) else []
            items.extend(page_items)
            if len(page_items) < 100:
                break
        return items

    def search_commits_pages(self, q: str, max_pages: int = 5) -> list[dict]:
        items = []
        for page in range(1, max_pages + 1):
            path = f"/search/commits?q={quote(q)}&per_page=100&page={page}"
            r = self._request(
                path, is_search=True,
                accept="application/vnd.github.cloak-preview+json")
            page_items = r.get("items", []) if isinstance(r, dict) else []
            items.extend(page_items)
            if len(page_items) < 100:
                break
        return items

    def search_repos_pages(self, q: str, max_pages: int = 5) -> list[dict]:
        items = []
        for page in range(1, max_pages + 1):
            path = f"/search/repositories?q={quote(q)}&sort=stars&order=desc&per_page=100&page={page}"
            r = self._request(path, is_search=True)
            page_items = r.get("items", []) if isinstance(r, dict) else []
            items.extend(page_items)
            if len(page_items) < 100:
                break
        return items


# ---- Helpers ---------------------------------------------------------------

def _size_band(prs_90d: int) -> str:
    if prs_90d < SMALL_LT:
        return "small"
    if prs_90d <= LARGE_GT:
        return "medium"
    return "large"


def _repo_full(item: dict, source: str) -> Optional[str]:
    """Pull owner/name from a search-result item across endpoint shapes."""
    if source == "commits":
        r = item.get("repository") or {}
        return r.get("full_name")
    if source == "issues":
        url = item.get("repository_url") or ""
        if "/repos/" in url:
            return url.split("/repos/", 1)[1]
        return None
    if source == "repos":
        return item.get("full_name")
    return None


def _date_iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).date().isoformat()


# ---- Pipeline --------------------------------------------------------------

def discover_agent_candidates(gh: GitHub, log) -> dict:
    """Returns {owner/name: {discovered_via: [markers]}}."""
    candidates: dict[str, dict] = {}
    for source, q in AGENT_MARKER_QUERIES:
        log(f"agent search [{source}] {q}")
        if source == "commits":
            items = gh.search_commits_pages(q, max_pages=4)
        else:
            items = gh.search_issues_pages(q, max_pages=4)
        for it in items:
            full = _repo_full(it, source)
            if not full:
                continue
            d = candidates.setdefault(full, {"discovered_via": []})
            tag = f"{source}:{q}"
            if tag not in d["discovered_via"]:
                d["discovered_via"].append(tag)
        log(f"  cumulative agent candidates: {len(candidates)}")
    return candidates


def discover_baseline_candidates(gh: GitHub, log) -> dict:
    """Pre-2023 repos active in last 90d, ≥BASELINE_MIN_STARS, by language."""
    candidates: dict[str, dict] = {}
    pushed_since = _date_iso(WINDOW_DAYS)
    for lang in BASELINE_LANGUAGES:
        q = (f"created:<{BASELINE_CREATED_BEFORE} pushed:>={pushed_since} "
             f"language:{lang} stars:>={BASELINE_MIN_STARS} "
             f"is:public archived:false fork:false")
        log(f"baseline search [language={lang}] {q}")
        items = gh.search_repos_pages(q, max_pages=2)
        for it in items:
            full = _repo_full(it, "repos")
            if not full:
                continue
            candidates.setdefault(full, {"discovered_via": []})
            tag = f"repos:language:{lang}"
            if tag not in candidates[full]["discovered_via"]:
                candidates[full]["discovered_via"].append(tag)
        log(f"  cumulative baseline candidates: {len(candidates)}")
    return candidates


def enrich_and_filter(gh: GitHub, candidates: dict, cohort: str,
                      log, exclusions: list) -> list:
    """For each candidate, fetch metadata + apply filters in fixed order.
    Returns list of enriched survivors. Logs every exclusion."""
    pushed_since = _date_iso(WINDOW_DAYS)
    activity_since = _date_iso(ACTIVITY_DAYS)
    survivors = []

    # Sort candidates deterministically (alphabetical) before any star-aware
    # truncation; the cap is applied AFTER metadata-driven sort.
    ordered = sorted(candidates.keys())
    log(f"\n[{cohort}] enriching {len(ordered)} candidates "
        f"(cap {ENRICH_CAP_PER_COHORT} by stars-desc after a cheap repo lookup)")

    # Stage 1 — cheap metadata fetch (1 core call/repo) and basic filters.
    stage1 = []
    for full in ordered:
        meta = gh.repo(full)
        if isinstance(meta, dict) and meta.get("_status") == 404:
            exclusions.append({"repo": full, "cohort": cohort,
                               "reason": "repo_not_found"})
            continue
        if meta.get("fork"):
            exclusions.append({"repo": full, "cohort": cohort,
                               "reason": "fork"})
            continue
        if meta.get("archived"):
            exclusions.append({"repo": full, "cohort": cohort,
                               "reason": "archived"})
            continue
        if meta.get("private"):
            exclusions.append({"repo": full, "cohort": cohort,
                               "reason": "private"})
            continue
        if meta.get("language") in DOCS_ONLY_LANGUAGES:
            exclusions.append({"repo": full, "cohort": cohort,
                               "reason": f"docs_only_lang={meta.get('language')}"})
            continue
        # heuristic: awesome-lists / curated lists by description or name
        name_lo = (meta.get("name") or "").lower()
        desc_lo = (meta.get("description") or "").lower()
        if (name_lo.startswith("awesome-") or " awesome " in f" {desc_lo} "
                or "curated list" in desc_lo):
            exclusions.append({"repo": full, "cohort": cohort,
                               "reason": "awesome_or_list"})
            continue
        if (meta.get("size") or 0) < 50:
            # size is in KB; under 50 KB is effectively empty
            exclusions.append({"repo": full, "cohort": cohort,
                               "reason": "empty_or_tiny_repo"})
            continue
        if cohort == "agent" and (meta.get("stargazers_count") or 0) < AGENT_MIN_STARS:
            exclusions.append({"repo": full, "cohort": cohort,
                               "reason": f"stars<{AGENT_MIN_STARS}"})
            continue
        stage1.append({"full": full, "meta": meta,
                       "discovered_via": candidates[full]["discovered_via"]})

    log(f"[{cohort}] after stage 1 hygiene: {len(stage1)} survivors")

    # Stage 2 — sort by stars-desc and cap (rate-budget guard).
    stage1.sort(key=lambda x: (-x["meta"].get("stargazers_count", 0), x["full"]))
    capped = stage1[:ENRICH_CAP_PER_COHORT]
    if len(stage1) > len(capped):
        for x in stage1[ENRICH_CAP_PER_COHORT:]:
            exclusions.append({"repo": x["full"], "cohort": cohort,
                               "reason": "enrich_cap_excess",
                               "stars": x["meta"].get("stargazers_count", 0)})
    log(f"[{cohort}] enrichment list capped at {len(capped)} (stars-desc)")

    # Stage 3 — activity counts + contributors + baseline marker gate.
    for i, x in enumerate(capped, 1):
        full = x["full"]
        log(f"  [{i}/{len(capped)}] {full} ({x['meta'].get('stargazers_count', 0)}★)")
        prs_90d = gh.search_issues_count(
            f"is:pr is:merged repo:{full} merged:>={pushed_since}")
        prs_180d = gh.search_issues_count(
            f"is:pr is:merged repo:{full} merged:>={activity_since}")
        if prs_180d < MIN_PRS_180D:
            exclusions.append({"repo": full, "cohort": cohort,
                               "reason": f"low_activity_prs180d={prs_180d}",
                               "stars": x["meta"].get("stargazers_count", 0)})
            continue
        if not gh.contributors_count_ge2(full):
            exclusions.append({"repo": full, "cohort": cohort,
                               "reason": "solo_contributor",
                               "stars": x["meta"].get("stargazers_count", 0)})
            continue

        marker_share = None
        if cohort == "baseline":
            # cheap proxy for the tool's marker detection — count PRs with the
            # marker strings (body or commit trailer) in the 90d window
            mq_body = (f"repo:{full} type:pr created:>={pushed_since} "
                       f'("Generated with [Claude Code]" OR '
                       f'"Co-authored by Cursor" OR '
                       f'"Co-Authored-By: Claude")')
            marker_prs = gh.search_issues_count(mq_body)
            marker_share = (marker_prs / prs_90d) if prs_90d else 0.0
            if marker_share >= BASELINE_MARKER_THRESHOLD:
                exclusions.append({"repo": full, "cohort": cohort,
                                   "reason": f"marker_share>={BASELINE_MARKER_THRESHOLD}",
                                   "marker_share": round(marker_share, 4),
                                   "marker_prs": marker_prs,
                                   "prs_90d": prs_90d,
                                   "stars": x["meta"].get("stargazers_count", 0)})
                continue

        survivors.append({
            "full": full,
            "stars": x["meta"].get("stargazers_count", 0),
            "language": x["meta"].get("language"),
            "default_branch": x["meta"].get("default_branch", "main"),
            "created_at": x["meta"].get("created_at"),
            "prs_90d": prs_90d,
            "prs_180d": prs_180d,
            "size_band": _size_band(prs_90d),
            "discovered_via": x["discovered_via"],
            "marker_share_estimate": marker_share,
        })
    log(f"[{cohort}] after activity + contributor + marker filters: {len(survivors)}")
    return survivors


def select_top_per_band(survivors: list, cohort: str, log, exclusions: list) -> list:
    """Bucket by size band, take TARGET_PER_BAND per band stars-desc."""
    bands = defaultdict(list)
    for s in survivors:
        bands[s["size_band"]].append(s)
    final = []
    for band in ("small", "medium", "large"):
        bands[band].sort(key=lambda s: (-s["stars"], s["full"]))
        chosen, leftover = bands[band][:TARGET_PER_BAND], bands[band][TARGET_PER_BAND:]
        for i, s in enumerate(chosen, 1):
            s["selection_rank_within_band"] = i
            s["cohort"] = cohort
            final.append(s)
        for x in leftover:
            exclusions.append({"repo": x["full"], "cohort": cohort,
                               "reason": f"band_full:{band}",
                               "stars": x["stars"],
                               "prs_90d": x["prs_90d"]})
        log(f"[{cohort}] band={band} candidates={len(bands[band])} "
            f"chosen={len(chosen)} leftover={len(leftover)}")
    return final


# ---- Main ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)),
                    help="directory to write repo_list.json + exclusion_log.json")
    args = ap.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        token = subprocess.check_output(["gh", "auth", "token"]).decode().strip()
    if not token:
        sys.exit("no GitHub token (set GH_TOKEN or `gh auth login`)")

    log = lambda s: print(s, file=sys.stderr, flush=True)
    gh = GitHub(token, log=sys.stderr)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log(f"\n=== OSS sweep cohort selection ===")
    log(f"started_utc      : {started}")
    log(f"protocol         : {PROTOCOL_VERSION}")
    log(f"tool_version     : {TOOL_VERSION}")
    log(f"target_per_band  : {TARGET_PER_BAND}")
    log(f"window_days      : {WINDOW_DAYS}")
    log(f"baseline_marker_threshold: {BASELINE_MARKER_THRESHOLD}")
    log("")

    exclusions: list[dict] = []

    log("--- AGENT cohort: discovery ---")
    agent_cands = discover_agent_candidates(gh, log)
    log(f"agent: {len(agent_cands)} unique candidates after discovery\n")

    log("--- BASELINE cohort: discovery ---")
    baseline_cands = discover_baseline_candidates(gh, log)
    log(f"baseline: {len(baseline_cands)} unique candidates after discovery\n")

    # Strip overlap: a repo discovered as agent-marked CAN'T also be in baseline.
    overlap = set(agent_cands) & set(baseline_cands)
    for full in overlap:
        exclusions.append({"repo": full, "cohort": "baseline",
                           "reason": "overlap_with_agent_cohort"})
        baseline_cands.pop(full, None)
    log(f"removed {len(overlap)} agent/baseline overlap from baseline\n")

    log("--- AGENT cohort: enrich + filter ---")
    agent_surv = enrich_and_filter(gh, agent_cands, "agent", log, exclusions)
    log("--- BASELINE cohort: enrich + filter ---")
    baseline_surv = enrich_and_filter(gh, baseline_cands, "baseline", log, exclusions)

    log("\n--- bucketing + selection ---")
    agent_final = select_top_per_band(agent_surv, "agent", log, exclusions)
    baseline_final = select_top_per_band(baseline_surv, "baseline", log, exclusions)

    finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = OrderedDict([
        ("protocol", PROTOCOL_VERSION),
        ("tool_version", TOOL_VERSION),
        ("frozen_at_utc", finished),
        ("selection_started_utc", started),
        ("parameters", {
            "TARGET_PER_BAND": TARGET_PER_BAND,
            "WINDOW_DAYS": WINDOW_DAYS,
            "ACTIVITY_DAYS": ACTIVITY_DAYS,
            "MIN_PRS_180D": MIN_PRS_180D,
            "SMALL_LT": SMALL_LT,
            "LARGE_GT": LARGE_GT,
            "MIN_CONTRIBUTORS": MIN_CONTRIBUTORS,
            "BASELINE_MARKER_THRESHOLD": BASELINE_MARKER_THRESHOLD,
            "BASELINE_CREATED_BEFORE": BASELINE_CREATED_BEFORE,
            "BASELINE_MIN_STARS": BASELINE_MIN_STARS,
            "AGENT_MIN_STARS": AGENT_MIN_STARS,
            "AGENT_MARKER_QUERIES": AGENT_MARKER_QUERIES,
            "BASELINE_LANGUAGES": BASELINE_LANGUAGES,
            "DOCS_ONLY_LANGUAGES": sorted(
                [l or "<none>" for l in DOCS_ONLY_LANGUAGES]),
        }),
        ("counts", {
            "agent_candidates_discovered": len(agent_cands),
            "baseline_candidates_discovered": len(baseline_cands),
            "agent_survivors_pre_band": len(agent_surv),
            "baseline_survivors_pre_band": len(baseline_surv),
            "agent_final": len(agent_final),
            "baseline_final": len(baseline_final),
            "exclusions_total": len(exclusions),
            "api_calls_core": gh.core_calls,
            "api_calls_search": gh.search_calls,
        }),
        ("agent_cohort", agent_final),
        ("baseline_cohort", baseline_final),
    ])
    os.makedirs(args.out, exist_ok=True)
    repo_list_path = os.path.join(args.out, "repo_list.json")
    excl_path = os.path.join(args.out, "exclusion_log.json")
    with open(repo_list_path, "w") as f:
        json.dump(out, f, indent=2)
    with open(excl_path, "w") as f:
        json.dump({"frozen_at_utc": finished, "exclusions": exclusions}, f, indent=2)
    log(f"\nwrote {repo_list_path}")
    log(f"wrote {excl_path}")
    log(f"agent_final={len(agent_final)}  baseline_final={len(baseline_final)}  "
        f"excluded={len(exclusions)}")
    log(f"API calls: core={gh.core_calls} search={gh.search_calls}")


if __name__ == "__main__":
    main()
