# commensa-audit — Commit Mode (`--local-clone`) Build Spec

> Phase D. Triggered by LaptopsAnytime (self-hosted cgit/Gitea, direct-commit workflow, no PRs — GBrain confirmed) but built because it's broadly needed: it unlocks every non-GitHub, non-PR, self-hosted prospect. Hand to a Claude Code session. Same gate discipline as SPEC.md (A/B/C). Read THESIS.md + context/measurement_architecture.md first for the why.

## The core design insight (Matt, 2026-06-13 — load-bearing)
**Drift measurement is AUTHOR-AGNOSTIC.** What survived, how many rewrites, how many commits hit the same region — measured from the code's behavior over time, not from who/what wrote it. So the tool measures *the management of the work*, regardless of whether AI, human, or human-committing-AI-as-themselves produced it. This is a bigger, more robust claim than "we measure AI rework."
- **Attribution (who/what wrote it) is the WEAK, OPTIONAL signal.** Co-Authored-By trailers only catch AI work that announces itself. When a human commits AI-written code under their own name (Dan's workflow), markers read ~0% AI — a known, permanent undercount. Report agent-marked as an explicit lower bound; NEVER rely on it for the before/after.
- **Drift (what happened to the work) is the STRONG, UNIVERSAL core.** Works on any repo, any author mix, marker or no marker.

## What commit-mode is
Read the LOCAL `.git` clone (already on the machine via GitKraken/any client). No host API, no network — pure git. Unit = the commit (vs the PR in GitHub-mode). Everything else — the line-attribution replay engine, corrective classification, survival — already exists and operates the same on commits as on PRs; feed it commits.

## Metrics (commit-mode)
- **Rework tax (commit version):** share of commits / changed-lines that are corrective. Corrective signal cascade, same shape as PR-mode: explicit message (fix/revert/redo/correct) → self-correction (a commit predominantly deleting lines added by a recent commit, within --window) → churn-cluster membership.
- **Survival:** line-attribution replay over commit history (engine already does this — point it at commits). Same self-gate: suppress below ~N attributable units.
- **Same-region churn (NEW, commit-native — Matt's "how many commits on the same section"):** count commits repeatedly touching the same file / line-range within --window. The purest drift signal; doesn't exist in PR-mode. Report hottest regions.
- **Agent-marked (optional, lower bound):** Co-Authored-By trailers in commit messages. Documented to undercount when humans commit AI work as their own. Not used for before/after.
- Velocity context (commits/week, size dist) — context only, never a target (LOC-trap rule holds).

## THE NATURAL-EXPERIMENT FEATURE: `--split-date`
The headline capability. `--split-date YYYY-MM-DD` (or `--before/--after`) partitions the commit history at a boundary and computes ALL metrics for each period, then reports the delta. **The calendar boundary is the treatment variable — no authorship label needed.** This is how the Dan/LA human→AI before/after gets measured: split at the ~45-day line, compare drift before vs after. Generalizes to any "we changed how we work on date X" question.

## Build phases & binary gates
- **Gate D-A — extractor fidelity.** Build the local-clone commit extractor (read `.git` via `git log`/plumbing, no network). GATE: its per-commit facts (sha, author, date, files, +/- lines) match `git log --numstat` on a known repo, exactly.
- **Gate D-B — cross-mode agreement.** Run commit-mode on **order-sheet-web-v2** (which has BOTH PRs and commits — we already have its PR-mode audit). GATE: commit-mode's drift metrics roughly track PR-mode's on the same repo (same rework story, no wild divergence). This validates commit-mode against the known-good PR result. Document expected differences (squash merges collapse commits, etc.).
  - **Integration contract (how the engine wires in — minimize new surface):** the engine consumes `units.csv` (schema in `commensa_audit/units.py`: unit_id · title · created_at · merged · lines_added · lines_deleted · changed_files · looks_revert) PLUS per-unit patch content for the line-attribution replay (`rework.py`; GitHub-mode supplies it via `GitHubExtractor.units(with_files=True)` → file `patch` text). **Commit-mode must emit BOTH:** (a) one units.csv row per commit — `unit_id`=short sha, `title`=`sanitize_title(subject)`, `created_at`=author date, `merged`=1 (a commit is landed by definition), lines/files from numstat, `looks_revert` from subject; and (b) the per-commit unified diff so the replay engine sees added/deleted line *content*, not just counts. **The D-A extractor only runs `--numstat` (counts) — D-B must add patch extraction (`git log -p`/`git show`), because survival/rework need line content.** Reuse `patches.py` parsing if the hunk format matches; adapt if not.
  - **quotePath / encoding hardening (carried from D-A review — do this BEFORE the OSWv2 run):** invoke git with `-c core.quotePath=false` and parse `--numstat -z` (NUL-delimited) so non-ASCII/space/odd filenames round-trip exactly. Add a regression test: a repo with a non-ASCII filename must round-trip `path`. Re-run Gate D-A's eval after the change to confirm the 11/11 exact match still holds.
- **Gate D-C — the natural experiment.** Run on Dan's LA repo (local clone) with `--split-date` at the ~45-day human→AI boundary. GATE: produces an honest before/after on rework, survival, same-region churn; Matt reads it and the delta is interpretable. THIS is the acceptance test and the first data point of the LA case study. Also: D-C adds the **same-region churn** metric (commit-native, deferred from D-B) — count commits repeatedly touching the same file/line-range within `--window`; report hottest regions.
  - **GUARDRAIL 1 (from D-B review, load-bearing): compare commit-mode to commit-mode ONLY.** Commit-mode reads rework higher in absolute terms than PR-mode (finer granularity surfaces more self-correction). The before/after is valid because BOTH sides of the split are commit-mode on the same repo. NEVER compare a commit-mode "after" against any PR-mode number (e.g. the OSWv2 27%).
  - **GUARDRAIL 2 (from D-B review): decide merge handling explicitly.** Under `git log -p` merges emit no diff and become near-empty units that dilute the corrective-unit% denominator. **Recommended: run with `--no-merges` for a clean before/after**; whichever is chosen, document it and apply it identically to both sides of the split.
  - **Sanity check before trusting survival:** confirm patch-text coverage is ~100% on Dan's repo (the `diff --git` split can drop files with " b/" in the path); if coverage is low, investigate before reading the deltas.

## Guardrails (bugs if violated)
- Read-only, local-only, **no network at all** in this mode (it's a local clone) — strongest version of the privacy story.
- **Always invoke git with `-c core.quotePath=false` and parse `-z` (NUL-delimited);** never trust default path quoting (D-A review finding — silently corrupts non-ASCII paths while the fidelity gate stays green).
- stdlib only (no host API client needed); reuse the existing engine.
- Honest limits in output: squash merges collapse history; rebases rewrite it; `--split-date` deltas are descriptive, not causal (the before/after is a natural experiment, n=1 repo — hypothesis-generating, document it); agent-marked is a lower bound and undercounts human-committed AI work.
- Same-region churn and survival self-gate on minimum volume; print n/a below threshold.

## Out of scope for Phase D
Tokens/cost (that's the harness, separate), sentiment, multi-repo rollups, GitHub-mode changes. Just: local clone in, commit-mode drift out, with --split-date.

## Why this is worth building now (not a one-off)
1. Unlocks the LA/Dan natural experiment (the case study + first before/after data).
2. Unlocks EVERY self-hosted / Gitea / GitLab / non-PR prospect — and our own infra is self-hosted, so this is clearly a large real-world slice, not an edge case.
3. Establishes that drift is author-agnostic and measurable without markers — the more robust, more general product claim.
4. `--split-date` is a reusable "did our workflow change help?" feature any customer wants.
