"""Blind enrichment of the frozen 102-repo cohort.

Runs AFTER the sweep completes, BEFORE any analyst opens runlog.jsonl. Pulls
repo metadata that turns the univariate "agent vs baseline" question into the
multivariate "agent_share + team_size + repo_size + ownership" question we
actually need to answer RQ1 honestly.

Per protocol discipline:
  - cohort identities are FROZEN (repo_list.json, committed)
  - enrichment ADDS metadata to those identities, does not change selection
  - this pass lands BEFORE any audit summary is read, so blind-enrichment
    holds: covariate set is locked alongside outcome set

Per repo, 3 core API calls:
  /repos/{full}                                metadata + owner.type
  /repos/{full}/languages                      bytes per language
  /repos/{full}/contributors?per_page=1&anon=1 contributor count via Link rel=last
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import argparse
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

API = "https://api.github.com"


def _call(token: str, path: str, *, accept="application/vnd.github+json"):
    """Returns (body_or_None, headers_dict, status). Handles 403/404/5xx."""
    url = path if path.startswith("http") else f"{API}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": "commensa-sweep-enrich",
    }
    for attempt in range(5):
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=30) as resp:
                body = resp.read()
                hdrs = {k: v for k, v in resp.getheaders()}
                return (json.loads(body) if body else None), hdrs, 200
        except HTTPError as e:
            if e.code == 404:
                return None, dict(e.headers or {}), 404
            if e.code in (403, 429):
                reset = e.headers.get("X-RateLimit-Reset")
                wait = max(5, int(reset) - int(time.time()) + 1) if reset else 60
                print(f"  rate-limited {e.code}; sleep {min(wait,300)}s",
                      file=sys.stderr, flush=True)
                time.sleep(min(wait, 300))
                continue
            if e.code >= 500:
                time.sleep(2 ** attempt)
                continue
            raise
        except URLError:
            time.sleep(2 ** attempt)
            continue
    return None, {}, -1


def _last_page_from_link(link_header: str) -> int | None:
    if not link_header:
        return None
    m = re.search(r'<([^>]+)>;\s*rel="last"', link_header)
    if not m:
        return None
    qs = parse_qs(urlparse(m.group(1)).query)
    if "page" in qs:
        try:
            return int(qs["page"][0])
        except ValueError:
            return None
    return None


def enrich(token: str, full: str) -> dict:
    """Pull the three metadata calls for one repo."""
    out: dict = {"full": full}

    # 1) repo metadata — owner.type, forks, issues, watchers, size_kb, etc.
    meta, _, status = _call(token, f"/repos/{full}")
    if status == 404 or not meta:
        out["error"] = f"repo_fetch_status={status}"
        return out
    owner = meta.get("owner") or {}
    out.update({
        "owner_login": owner.get("login"),
        "owner_type": owner.get("type"),                 # "User" | "Organization"
        "stars": meta.get("stargazers_count"),
        "forks_count": meta.get("forks_count"),
        "open_issues_count": meta.get("open_issues_count"),
        "subscribers_count": meta.get("subscribers_count"),  # watchers
        "size_kb": meta.get("size"),
        "primary_language": meta.get("language"),
        "default_branch": meta.get("default_branch"),
        "created_at": meta.get("created_at"),
        "pushed_at": meta.get("pushed_at"),
        "description": (meta.get("description") or "")[:300],
        "license": (meta.get("license") or {}).get("spdx_id"),
        "archived": meta.get("archived"),
        "topics": meta.get("topics") or [],
    })

    # 2) language bytes → total_loc_bytes proxy
    langs, _, status = _call(token, f"/repos/{full}/languages")
    if status == 200 and isinstance(langs, dict):
        total = sum(int(v) for v in langs.values())
        out["language_bytes"] = langs
        out["total_loc_bytes"] = total
        out["language_count"] = len(langs)
    else:
        out["language_bytes"] = None
        out["total_loc_bytes"] = None
        out["language_count"] = None

    # 3) contributor count via per_page=1 + Link rel=last (1 call, exact count)
    body, hdrs, status = _call(
        token, f"/repos/{full}/contributors?per_page=1&anon=1")
    if status == 200:
        link = hdrs.get("Link") or hdrs.get("link") or ""
        last_page = _last_page_from_link(link)
        if last_page is not None:
            out["contributors_count"] = last_page
        elif isinstance(body, list):
            out["contributors_count"] = len(body)
        else:
            out["contributors_count"] = 0
    else:
        out["contributors_count"] = None

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-list", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        token = subprocess.check_output(["gh", "auth", "token"]).decode().strip()

    rl = json.load(open(args.repo_list, encoding="utf-8"))
    repos = [r["full"] for r in rl["agent_cohort"]] + \
            [r["full"] for r in rl["baseline_cohort"]]
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"=== cohort enrichment ===")
    print(f"started_utc       : {started}")
    print(f"repos             : {len(repos)}")
    print(f"calls expected    : ~{3 * len(repos)} (core)")
    print(f"out               : {args.out}")
    print("")

    enriched: list[dict] = []
    errors = 0
    for i, full in enumerate(repos, 1):
        e = enrich(token, full)
        if "error" in e:
            errors += 1
            print(f"  [{i}/{len(repos)}] {full}: ERR {e['error']}", flush=True)
        else:
            print(f"  [{i}/{len(repos)}] {full}: "
                  f"contrib={e.get('contributors_count')} "
                  f"loc_bytes={e.get('total_loc_bytes')} "
                  f"owner={e.get('owner_type')}", flush=True)
        enriched.append(e)

    finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = {
        "started_utc": started,
        "finished_utc": finished,
        "repos_enriched": len(enriched),
        "errors": errors,
        "source_cohort_frozen_at": rl.get("frozen_at_utc"),
        "tool_version": rl.get("tool_version"),
        "repos": enriched,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"\nwrote {args.out}")
    print(f"enriched={len(enriched)}  errors={errors}")


if __name__ == "__main__":
    main()
