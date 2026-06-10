"""Line-attribution replay — the data layer under self-correction,
supersession, survival, and churn clusters.

Model: walk merged PRs in merge order. For every file we keep a "live"
multiset of line contents, each attributed to the PR that added it (a stack
per content — last writer on top). When a later PR deletes a line some
earlier PR added, that is a rework edge (downstream PR reworked upstream
PR's lines). What's left attributed to a PR at the end is what survived.

Honest limits (these go in the Phase C report footer verbatim):
- Attribution is by exact line content per file. Duplicate contents are
  resolved most-recent-first; moved lines look like delete+add.
- Trivial lines (blanks, lone braces/brackets — see TRIVIAL_RE) carry no
  attribution and are excluded from survival denominators.
- Renames are followed via the PR files API previous_filename. Renames done
  outside PRs are invisible.
- Commits pushed directly to the default branch (no PR) are invisible; lines
  they delete still count as surviving here.
- PRs with missing patches (binary / >3000-file diffs) contribute no line
  attribution; their lines_added/deleted totals still exist in units.csv.
- Survival is measured at extraction time (the end of the data), which for a
  repo younger than --window equals "now".
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime

from .patches import parse_patch

# Lines that carry no signal: blank, or only punctuation/structure chars.
TRIVIAL_RE = re.compile(r"^[\s{}()\[\];,]*$")


def _ts(iso: str | None) -> float:
    if not iso:
        return float("inf")
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


class ReplayResult:
    def __init__(self):
        self.added = {}        # unit_id -> attributable (non-trivial) lines added
        self.deleted = {}      # unit_id -> attributable lines deleted
        self.surviving = {}    # unit_id -> attributable lines still live at end
        self.edges = defaultdict(int)   # (upstream_id, downstream_id) -> lines reworked
        self.files = {}        # unit_id -> set of file paths touched (final names)
        self.merged_ts = {}    # unit_id -> merge timestamp
        self.no_patch = defaultdict(int)  # unit_id -> files with missing patch
        # (upstream, downstream) -> {path: rework lines} — which file each
        # edge's lines landed in (lets clusters name their own anchor file)
        self.edge_files = defaultdict(lambda: defaultdict(int))

    def reworked_recent(self, unit_id: str, window_days: float) -> int:
        """Lines unit_id deleted from PRs merged < window_days before it."""
        horizon = window_days * 86400
        return sum(n for (up, down), n in self.edges.items()
                   if down == unit_id
                   and 0 <= self.merged_ts[unit_id] - self.merged_ts[up] < horizon)

    def reworked_by_others(self, unit_id: str, window_days: float) -> dict[str, int]:
        """upstream view: who deleted unit_id's lines within the window."""
        horizon = window_days * 86400
        return {down: n for (up, down), n in self.edges.items()
                if up == unit_id
                and 0 <= self.merged_ts[down] - self.merged_ts[up] < horizon}


def replay(prs: list[dict]) -> ReplayResult:
    """prs: sidecar rows (unit_id, merged, merged_at, files[{filename, status,
    previous_filename, patch}]). Only merged PRs participate."""
    merged = sorted((p for p in prs if p.get("merged")), key=lambda p: _ts(p.get("merged_at")))
    res = ReplayResult()
    live: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    for pr in merged:
        uid = pr["unit_id"]
        res.merged_ts[uid] = _ts(pr.get("merged_at"))
        res.added.setdefault(uid, 0)
        res.deleted.setdefault(uid, 0)
        touched = set()
        for f in pr.get("files", []):
            path = f["filename"]
            if f.get("status") == "renamed" and f.get("previous_filename"):
                if f["previous_filename"] in live:
                    live[path] = live.pop(f["previous_filename"])
            touched.add(path)
            if f.get("patch") is None and (f.get("additions") or f.get("deletions")):
                res.no_patch[uid] += 1
            book = live[path]
            for op, content in parse_patch(f.get("patch")):
                if TRIVIAL_RE.match(content):
                    continue
                if op == "+":
                    book[content].append(uid)
                    res.added[uid] += 1
                else:
                    res.deleted[uid] += 1
                    stack = book.get(content)
                    if stack:
                        owner = stack.pop()  # most-recent attribution
                        if not stack:
                            del book[content]
                        if owner != uid:  # intra-PR moves are not rework
                            res.edges[(owner, uid)] += 1
                            res.edge_files[(owner, uid)][path] += 1
        res.files[uid] = touched

    res.surviving = {uid: 0 for uid in res.added}
    for book in live.values():
        for stack in book.values():
            for owner in stack:
                res.surviving[owner] = res.surviving.get(owner, 0) + 1
    return res


# ---------- churn clusters ----------

def churn_clusters(res: ReplayResult, *, window_days: float, min_size: int,
                   min_edge_lines: int, edge_min_frac: float) -> list[dict]:
    """Connected components of merged PRs linked by SUBSTANTIAL rework edges
    (B deleted ≥ min_edge_lines of A's lines AND ≥ edge_min_frac of A's
    added work, within the window) — i.e. chains of PRs rewriting each
    other: "5 PRs to get dark mode right".

    Two deliberate deviations from naive "touching the same files":
    - File co-location linked 58-PR transitive blobs on a hot codebase
      (every PR touches globals.css or PICKUP.md). Co-location is cadence;
      churn is redoing the work.
    - Absolute line counts alone still chained the whole sprint (5 lines is
      noise in a fast repo). The relative test — B reworked a real fraction
      of A — is what "repeated attempts at the same thing" means. On the
      pilot repo this isolates exactly the dark-mode and PillStack sagas,
      stable across edge_min_frac 0.2–0.3."""
    horizon = window_days * 86400
    uids = list(res.merged_ts)
    parent = {u: u for u in uids}

    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    for (up, down), n in res.edges.items():
        if (n >= min_edge_lines
                and n >= edge_min_frac * max(res.added.get(up, 0), 1)
                and res.merged_ts[down] - res.merged_ts[up] < horizon):
            parent[find(up)] = find(down)

    groups = defaultdict(list)
    for u in uids:
        groups[find(u)].append(u)

    clusters = []
    for members in groups.values():
        if len(members) < min_size:
            continue
        members.sort(key=lambda u: res.merged_ts[u])
        mset = set(members)
        internal = sum(n for (up, down), n in res.edges.items()
                       if up in mset and down in mset)
        # "around <file>" = where THIS cluster's internal rework landed,
        # then breadth of membership, then name (deterministic)
        cluster_rework = defaultdict(int)
        for (up, down), by_file in res.edge_files.items():
            if up in mset and down in mset:
                for f, n in by_file.items():
                    cluster_rework[f] += n
        common = sorted(set.union(*(res.files[m] for m in members)),
                        key=lambda f: (-cluster_rework.get(f, 0),
                                       -sum(f in res.files[m] for m in members), f))
        clusters.append(dict(
            members=members,
            internal_rework_lines=internal,
            top_files=common[:5],
        ))
    clusters.sort(key=lambda c: -len(c["members"]))
    return clusters


# ---------- supersession ----------

def supersessions(res: ReplayResult, *, window_days: float, min_frac: float,
                  min_lines: int) -> dict[str, dict]:
    """upstream unit_id -> {by, lines, frac} when ≥min_frac of its
    attributable added lines were deleted by later PRs within the window."""
    out = {}
    for uid, added in res.added.items():
        if added < min_lines:
            continue
        reworkers = res.reworked_by_others(uid, window_days)
        total = sum(reworkers.values())
        if total / added >= min_frac:
            top = max(reworkers, key=reworkers.get)
            out[uid] = dict(by=sorted(reworkers, key=lambda k: -reworkers[k]),
                            lines=total, frac=round(total / added, 3),
                            mainly=top)
    return out
