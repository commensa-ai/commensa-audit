# commensa-audit — Build Spec v1

**What this is:** a CLI tool. Point it at a GitHub repo → get a one-page "AI Rework Report." The lead-gen wedge and first market test for Commensa (see `../execution/launch_plan.md` Phase 0). Not a platform, not a dashboard, not the harness.

**One sentence of product truth:** *"X% of your AI engineering effort went to correcting your AI's own work."* Everything in the report serves that sentence.

## Inputs / outputs

```
commensa-audit --repo owner/name --token $GH_TOKEN [--window 60] [--cost-per-pr 400 | --ai-spend 25000]
```

- **Input:** any GitHub repo (read-only API access). Optional: local clone path instead of API.
- **Output:** `report_<repo>_<date>.html` (one page, self-contained, forwardable) + `audit_<repo>.json` (raw numbers) + `units.csv` (per-PR data).

## The metrics (v1 — only what git supports; NO token metrics, they're harness-era)

1. **Rework tax** (headline): % of PRs and % of changed lines classified *corrective* vs *generative*. Dollar translation when `--cost-per-pr` or `--ai-spend` provided, clearly labeled estimate.
2. **Churn clusters:** groups of ≥3 PRs within 14 days touching the same files/components ("5 PRs to get dark mode right").
3. **Supersession chains:** PRs whose changes were substantially replaced by a later PR within the window.
4. **Survival rate:** % of merged lines still present at window end (rename-aware; document method + limits honestly).
5. **Velocity context:** PRs/week, merge rate, size distribution — context, never praised as a target (LOC-trap guardrail).

Every number carries a confidence note (e.g., survival detection is heuristic; squash merges limit attribution). **We grade our own certainty — no false precision.** No claims about tokens, models, or energy in v1.

## Corrective-vs-generative classification (the core algorithm)

Objective signals, no hand labels, in priority order:
1. **Explicit:** revert commits; titles matching `fix|revert|redo|correct|hotfix|patch|repair|undo` (conventional-commit `fix:` type included).
2. **Self-correction window:** PR substantially modifies/deletes lines introduced by another PR merged < N days earlier (default 14) → corrective, attributed upstream where traceable.
3. **Churn-cluster membership:** ≥3rd PR in a cluster on the same files/topic → corrective-leaning.
4. Everything else → generative.

Output per PR: classification + which signal fired (transparency in the report). Tunable thresholds in one config block — this is the seed of the configurable gate.

## Build phases & acceptance gates (binary — do not proceed on "close enough")

### Phase A — Extractor + engine on known ground
Port `reference/` code into a clean package (`commensa_audit/`). GitHub API extractor: PRs, diffs, merge/revert status, file-level line history for the survival window.
**GATE A:** run on `mattlaptopsanytime-collab/order-sheet-web-v2` → reproduces `reference/orderwebv2_units.csv` (162 PRs, matching line counts). This is the regression test; the answers are known.

### Phase B — Classification + metrics
Implement the corrective classifier + churn clusters + supersession + survival.
**GATE B:** on order-sheet-web-v2's 30 labeled PRs (`reference/LABEL_THESE.csv`), the objective classifier's corrective/generative split agrees with the corrective-tagged subset from Pilot 1 at ≥80%, AND Matt spot-checks 10 classifications and accepts the explanations. Disagreements get documented, not hidden — they're product learning.

### Phase C — The report
One-page self-contained HTML (inline CSS, Commensa brand: indigo `#1d2b4d`, teal `#18a06b`, marks in `../marketing/`). Structure: headline rework-tax number with dollar line → 3 evidence panels (clusters, supersession, survival) → method & confidence footer → "get the continuous version" CTA.
**GATE C:** renders for order-sheet-web-v2 AND one more of Matt's repos; Matt's test: *"I would forward this to another executive."* If not, iterate the report, not the metrics.

## Constraints (guardrails — violations are bugs)

- **Read-only.** Never writes to the audited repo. Token needs `repo:read` only.
- **Local-first.** All data stays on the user's machine; nothing phones home in v1.
- **No unsupported claims.** No token/model/energy numbers; no "AI-generated" attribution claims we can't back (we audit *all* PRs; the AI framing comes from the customer knowing their repo is agent-built).
- **Dependencies:** stdlib + `requests` + `jinja2` max (The Ladder applies — justify anything beyond these in BUILD_LOG.md). No scipy (rank-correlation is hand-rolled in reference code).
- **Honest limits in the report itself:** squash-merge attribution, rename detection, heuristic classification — stated in the footer, not buried.

## Out of scope for v1 (resist — log ideas in PICKUP instead)
Web UI · auth/SaaS · MCP server/harness hooks · token metrics · model attribution · benchmark comparisons · multi-repo rollups · GitLab/Bitbucket/Gitea adapters.

**Architecture rule that keeps adapters cheap:** the extractor and the engine are separate — the engine consumes `units.csv` (one row per unit of work), never a host API. Any future host = one new extractor emitting the same CSV. **First adapter after Gate C: Gitea** (API is largely GitHub-compatible; Matt's own Morgan/NAS stack runs it = dogfood; self-hosted-git shops are the security-conscious segment that loves local-first). GitKraken needs nothing — it's a client, not a host. Host-agnostic fallback for later: `--local-clone` mode reading plain git (loses PR boundaries, uses merge commits as units).

## Dogfooding rule
Log every build session in `BUILD_LOG.md`: date, session #, what shipped, approx tokens (from Claude Code usage), corrections needed. The build's own rework tax is launch content.
