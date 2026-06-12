"""GitHub PR extractor — read-only, paginated, emits the units.csv schema.

API behavior verified against docs.github.com REST reference on 2026-06-09
(not coded from memory — PICKUP warning):
- GET /repos/{owner}/{repo}/pulls: state=all, per_page max 100, pagination
  via the Link header (rel="next"). The list response is "Pull Request
  Simple" and does NOT include additions/deletions/changed_files.
- GET /repos/{owner}/{repo}/pulls/{number}: returns additions, deletions,
  changed_files, merged, merged_at.
- Recommended headers: Accept: application/vnd.github+json and
  X-GitHub-Api-Version (current: 2026-03-10). Auth: Bearer token.
- Rate limits: 5,000 req/hr authenticated, 60 unauthenticated. On 403/429
  honor Retry-After, else X-RateLimit-Reset.

Guardrail (SPEC.md): read-only — this module issues GET requests only and a
token with read scope is sufficient.
"""

from __future__ import annotations

import time
from typing import Callable, Iterator

import requests

from ..markers import detect_markers
from ..units import looks_revert, sanitize_title

API_ROOT = "https://api.github.com"
API_VERSION = "2026-03-10"
PER_PAGE = 100
MAX_RETRIES = 4


class GitHubError(RuntimeError):
    pass


class GitHubExtractor:
    """Pull units (one per PR, all states) from a GitHub repo, oldest first."""

    def __init__(self, repo: str, token: str | None = None,
                 session: requests.Session | None = None):
        if "/" not in repo:
            raise ValueError(f"--repo must be owner/name, got {repo!r}")
        self.repo = repo
        self.requests = 0   # HTTP round-trips made — for API-budget reporting
        self.capped = False  # set True when max_prs truncated the listing
        self.session = session or requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "commensa-audit",
        })
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    # -- transport ---------------------------------------------------------

    def _get(self, url: str, params: dict | None = None) -> requests.Response:
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = self.session.get(url, params=params, timeout=30)
                self.requests += 1
            except (requests.Timeout, requests.ConnectionError) as e:
                if attempt < MAX_RETRIES:
                    time.sleep(2 ** attempt)
                    continue
                raise GitHubError(f"network failure after {MAX_RETRIES} retries "
                                  f"for {url}: {e}") from e
            if resp.status_code == 200:
                return resp
            if resp.status_code in (403, 429) and attempt < MAX_RETRIES:
                wait = _rate_limit_wait(resp)
                if wait is not None:
                    time.sleep(min(wait, 120))
                    continue
            if resp.status_code >= 500 and attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            raise GitHubError(
                f"GitHub API {resp.status_code} for {url}: {resp.text[:200]}")
        raise GitHubError(f"GitHub API retries exhausted for {url}")

    # -- extraction --------------------------------------------------------

    def select_pull_numbers(self, since: str | None = None,
                            max_prs: int | None = None) -> list[int]:
        """PR numbers (open + closed) to audit, returned ascending.

        Default (since=None, max_prs in {None, 0}): every PR in the repo —
        unchanged, the Gate A behaviour (same request params, full pagination).
        A positive max_prs keeps the N newest; `since` keeps PRs created on/after
        an inclusive YYYY-MM-DD UTC date. When either limit is active the listing
        switches to newest-first (sort=created&direction=desc) and pagination
        early-stops as soon as the cap is reached or the first PR older than
        `since` appears — so a large repo costs ~N list rows + their detail
        calls, not its whole history. Sets self.capped=True iff max_prs truncated
        the result (more PRs existed than were returned).
        """
        self.capped = False
        cap = max_prs if (max_prs and max_prs > 0) else None  # 0/None/neg ⇒ no cap
        limited = since is not None or cap is not None
        numbers: list[int] = []
        url = f"{API_ROOT}/repos/{self.repo}/pulls"
        params: dict | None = {"state": "all", "per_page": PER_PAGE}
        if limited:
            params |= {"sort": "created", "direction": "desc"}
        while url:
            resp = self._get(url, params=params)
            page = resp.json()
            for i, pr in enumerate(page):
                if since is not None and (pr.get("created_at") or "")[:10] < since:
                    return sorted(numbers)  # desc order ⇒ every remaining PR is older
                numbers.append(pr["number"])
                if cap is not None and len(numbers) >= cap:
                    # truncated iff more PRs remain — in this page or a next one
                    self.capped = (i < len(page) - 1) or bool(
                        resp.links.get("next", {}).get("url"))
                    return sorted(numbers)
            url = resp.links.get("next", {}).get("url")
            params = None  # the Link URL already carries the query string
        return sorted(numbers)

    def list_pull_numbers(self) -> list[int]:
        """All PR numbers in the repo (open + closed), ascending. Back-compat
        alias for select_pull_numbers() with no limits."""
        return self.select_pull_numbers()

    def fetch_pull(self, number: int) -> dict:
        resp = self._get(f"{API_ROOT}/repos/{self.repo}/pulls/{number}")
        return resp.json()

    def fetch_pull_files(self, number: int) -> list[dict]:
        """All changed files for a PR. Docs (verified 2026-06-09): per_page
        max 100, response capped at 3000 files, `patch` absent for binary /
        oversized diffs, `previous_filename` present when status=renamed."""
        files: list[dict] = []
        url = f"{API_ROOT}/repos/{self.repo}/pulls/{number}/files"
        params: dict | None = {"per_page": PER_PAGE}
        while url:
            resp = self._get(url, params=params)
            files.extend(resp.json())
            url = resp.links.get("next", {}).get("url")
            params = None
        return files

    def fetch_commit_messages(self, number: int) -> list[str]:
        """Commit messages for a PR (Co-Authored-By trailers live here).
        Docs (verified 2026-06-10): per_page max 100, response capped at 250
        commits — PRs beyond that lose trailer visibility (lower-bound metric,
        documented)."""
        messages: list[str] = []
        url = f"{API_ROOT}/repos/{self.repo}/pulls/{number}/commits"
        params: dict | None = {"per_page": PER_PAGE}
        while url:
            resp = self._get(url, params=params)
            messages.extend((c.get("commit") or {}).get("message") or "" for c in resp.json())
            url = resp.links.get("next", {}).get("url")
            params = None
        return messages

    def units(self, progress: Callable[[int, int], None] | None = None,
              with_files: bool = False, since: str | None = None,
              max_prs: int | None = None) -> Iterator[dict | tuple[dict, dict]]:
        """Yield one units.csv row per PR, ascending by PR number.

        with_files=True additionally fetches each PR's file list + patches and
        yields (unit_row, sidecar_row) tuples — the Phase B detail the rework
        model replays. The sidecar keeps the raw (unsanitized) title and
        merged_at; units.csv keeps its locked Gate A schema.

        since / max_prs scope the audit to the newest PRs (see
        select_pull_numbers); both default to None = the whole repo."""
        numbers = self.select_pull_numbers(since=since, max_prs=max_prs)
        total = len(numbers)
        for i, number in enumerate(numbers, 1):
            pr = self.fetch_pull(number)
            title = pr.get("title") or ""
            unit = {
                "unit_id": f"PR-{number}",
                "title": sanitize_title(title),
                "created_at": pr["created_at"],
                "merged": 1 if pr.get("merged") else 0,
                "lines_added": pr.get("additions", 0),
                "lines_deleted": pr.get("deletions", 0),
                "changed_files": pr.get("changed_files", 0),
                "looks_revert": looks_revert(title),
            }
            if with_files:
                files = [
                    {k: f.get(k) for k in ("filename", "status", "previous_filename",
                                           "additions", "deletions", "patch")}
                    for f in self.fetch_pull_files(number)
                ]
                sidecar = {
                    "unit_id": unit["unit_id"],
                    "number": number,
                    "raw_title": title,
                    "created_at": pr["created_at"],
                    "merged_at": pr.get("merged_at"),
                    "merged": bool(pr.get("merged")),
                    "state": pr.get("state"),          # open | closed
                    "closed_at": pr.get("closed_at"),
                    # marker strings only — bodies/messages stay off disk (local-first, lean sidecar)
                    "ai_markers": detect_markers(pr.get("body"),
                                                 self.fetch_commit_messages(number)),
                    "files": files,
                }
                yield unit, sidecar
            else:
                yield unit
            if progress:
                progress(i, total)


def _rate_limit_wait(resp: requests.Response) -> float | None:
    """Seconds to wait per rate-limit headers, or None if not rate-limited."""
    retry_after = resp.headers.get("Retry-After")
    if retry_after and retry_after.isdigit():
        return float(retry_after)
    if resp.headers.get("X-RateLimit-Remaining") == "0":
        reset = resp.headers.get("X-RateLimit-Reset")
        if reset and reset.isdigit():
            return max(0.0, float(reset) - time.time()) + 1.0
    return None
