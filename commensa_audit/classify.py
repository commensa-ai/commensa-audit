"""Corrective-vs-generative classifier (SPEC.md core algorithm).

Objective signals, no hand labels, in priority order — first hit wins:
1. explicit       — revert / fix-family title (conventional-commit fix: included)
2. self_correction — PR substantially deletes lines another PR added < window
                     days earlier (attributed upstream via rework edges)
3. churn_cluster  — 3rd-or-later member of a qualifying churn cluster
else generative.

Every classification carries its signal + a human-readable detail string —
transparency requirement, the report shows WHY.

Supersession is reported alongside but does NOT flip the upstream PR to
corrective: the superseded PR generated work (it just didn't last); the
correcting PR is the corrective one. Pilot 1 grouped superseded PRs with
corrective — gate_b_eval shows agreement both ways.
"""

from __future__ import annotations

import re

from .rework import ReplayResult, churn_clusters, supersessions

# ---- Tunable thresholds, one block (the seed of the configurable gate) ----
CONFIG = dict(
    window_days=14,            # self-correction / churn / supersession window
    # signal 1 — explicit title. (?<![\w-]) blocks "non-reverting", "prefix-…"
    title_re=r"(?<![\w-])(fix(es|ed|ing)?|revert(s|ed|ing)?|redo(ne|es|ing)?"
             r"|correct(s|ed|ing|ion|ions)?|hotfix(es)?|patch(es|ed|ing)?"
             r"|repair(s|ed|ing)?|undo(es|ne|ing)?)(?![\w-])",
    # signal 2 — self-correction: corrective when UNDOING dominates the PR's
    # work, not merely when recent lines get touched (in a young, fast repo
    # every deletion is "recent" — share-of-deletions over-fired badly).
    selfcorr_min_lines=10,     # absolute floor (ignore cosmetic touches)
    selfcorr_min_share=0.33,   # recent-deleted / (attributable adds + deletes)
    # signal 3 — churn clusters: chains of PRs rewriting each other.
    # An edge needs absolute size AND a real fraction of the upstream PR's
    # work — absolute-only edges transitively chained the whole sprint.
    cluster_min_size=3,
    cluster_min_edge_lines=10,  # rework lines linking two PRs into a chain
    cluster_edge_min_frac=0.25,  # …and ≥ this share of upstream's added lines
    # supersession (reported, not a classification signal)
    supersede_min_frac=0.50,   # share of a PR's added lines replaced within window
    supersede_min_lines=10,    # ignore tiny PRs where 2 lines = 50%
)

TITLE_RE = re.compile(CONFIG["title_re"], re.IGNORECASE)


def classify(units: list[dict], res: ReplayResult, config: dict = CONFIG) -> dict:
    """Returns {unit_id: {classification, signal, detail, superseded_by?}}."""
    window = config["window_days"]
    clusters = churn_clusters(
        res, window_days=window,
        min_size=config["cluster_min_size"],
        min_edge_lines=config["cluster_min_edge_lines"],
        edge_min_frac=config["cluster_edge_min_frac"])
    superseded = supersessions(
        res, window_days=window,
        min_frac=config["supersede_min_frac"],
        min_lines=config["supersede_min_lines"])

    late_cluster_member = {}   # unit_id -> (cluster_idx, position)
    for ci, c in enumerate(clusters):
        for pos, uid in enumerate(c["members"], 1):
            if pos >= 3:
                late_cluster_member[uid] = (ci, pos, len(c["members"]))

    out = {}
    for u in units:
        uid = u["unit_id"]
        title = u.get("raw_title") or u["title"]
        entry = dict(classification="generative", signal=None, detail="")

        m = TITLE_RE.search(title)
        if u.get("looks_revert") or m:
            word = "revert" if u.get("looks_revert") else m.group(0).lower()
            entry.update(classification="corrective", signal="explicit",
                         detail=f"title token {word!r}")
        elif uid in res.merged_ts:
            recent = res.reworked_recent(uid, window)
            work = res.added.get(uid, 0) + res.deleted.get(uid, 0)
            if (recent >= config["selfcorr_min_lines"]
                    and recent / max(work, 1) >= config["selfcorr_min_share"]):
                ups = sorted(((up, n) for (up, down), n in res.edges.items()
                              if down == uid), key=lambda t: -t[1])[:3]
                entry.update(
                    classification="corrective", signal="self_correction",
                    detail=f"deletes {recent} lines added <{window}d earlier "
                           f"(mainly {', '.join(f'{a} ({n})' for a, n in ups)})")
            elif uid in late_cluster_member:
                ci, pos, size = late_cluster_member[uid]
                files = ", ".join(clusters[ci]["top_files"][:2])
                entry.update(
                    classification="corrective", signal="churn_cluster",
                    detail=f"PR {pos}/{size} in churn cluster #{ci + 1} ({files})")
        if uid in superseded:
            s = superseded[uid]
            entry["superseded_by"] = s["mainly"]
            entry["superseded_frac"] = s["frac"]
        out[uid] = entry

    return dict(classifications=out, clusters=clusters, superseded=superseded,
                config=dict(config))
