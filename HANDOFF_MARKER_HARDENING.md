# Handoff — Marker-Detection Hardening + Reporting Pass (consolidated)

> Written 2026-06-13 (Cowork) after the `theo` run surfaced three commit-mode bugs and a detection-completeness gap. Read this + `BUILD_LOG.md` (the three most recent entries: merge-NUL hotfix, marker body-scan hotfix, marker-completeness findings) + `THESIS.md` §8c. Same gate discipline as Phases A–D: one gate per session, binary acceptance, STOP for review, update BUILD_LOG. **The three hotfixes already in `local_clone.py` (merge-NUL, body-scan) are stopgaps — this handoff folds them in properly with tests.**

## Why now (time-sensitive)
The OSS **sweep analysis is Sunday**. The sweep's cross-repo agent-vs-human framing rests on agent-marked share, and detection has gaps. **Phase M-A + the sweep re-run must land before Sunday.** M-B and M-C can follow after.

## The acceptance fixture: `theo` (Matt's brother Greg's repo)
Local clone already on the machine at `~/Documents/claude/AI_Stewardship_Cert/_external/theo` (2149 commits, Jan–Jun 2026, solo, ~88% Claude-marked via body trailers). It exercises every gap at once, so it is the standing acceptance fixture. **Known-good numbers to assert against** (computed 2026-06-13 with the body-scan hotfix in place):

| Quantity | Expected |
|---|---|
| total commits (with merges) | 2149 |
| agent-marked (full-message scan) | **1886 (87.8%)** |
| no-trailer commits | 262 — of which **29 merges**, **11 committed by `GitHub <noreply@github.com>` (web UI)** |
| model ladder (Co-Authored-By) | Opus **4.5** ≈685 (Jan–Feb) · **4.6** ≈858 (Feb–Apr) · **4.7** ≈284 (Apr–May) · **4.8** ≈52 (May–Jun) |
| drift | survival **0.561** · corrective-lines **31.5%** · corrective-units **50.3%** |

Critical negative cases theo provides (must NOT be flagged agent): the **11 `GitHub <noreply@github.com>` web-UI commits** (a human using GitHub's web editor is NOT an agent), and the human co-author `Robyn Brister (COO)`.

---

## Phase M-A — marker completeness  ⟵ CRITICAL PATH for Sunday
Make `markers.py` + `local_clone.py` see every place a marker honestly lives. Five parts:

1. **Scan author + committer IDENTITY, not just trailers/body.** If the author or committer name/email matches an agent identity, count it. **Guardrail against false positives:** only the agent allowlist counts; generic platform identities are NOT agents — explicitly exclude `GitHub <noreply@github.com>` (web UI = human). theo's 11 web-UI commits must stay unmarked.
2. **Broaden + maintain `AGENT_IDENTS`.** Current list is Claude/Copilot-era. Add at least: lovable, windsurf, cline, roo, `v0`, bolt, replit, `amazon q`, codewhisperer, tabnine, cody, sourcegraph, amp, continue, augment, codeium, supermaven, phind, zed. Keep it a single maintained constant with a comment that it's necessarily incomplete (lower-bound by construction).
3. **Other trailer keys.** Beyond `Co-Authored-By`, detect `Assisted-by:`, `Generated-by:`, `On-behalf-of:` when the value names an agent identity.
4. **Structured MODEL extraction.** When a trailer/identity names a model (e.g. `Claude Opus 4.6 (1M context)`), parse and emit a structured `model` field per unit (family + version when present), in addition to the human-readable marker string. This is the data layer for model-durability (Door 3) — surfacing the metric is M-B/optional, but capture the field now.
5. **MARKER GATE + test corpus.** Commit-mode markers had ZERO test coverage — that's why the subject-only bug shipped. Build `tests/test_markers_commitmode.py` with a synthetic repo covering: body trailer (café/emoji bodies ok), subject-only (none expected), multi-model ladder, `Assisted-by`/`Generated-by`, agent-as-author, web-UI committer (negative), human co-author (negative). Plus a `quality/gateM_A_eval.py` that runs detection on `theo` and asserts the table above.

**GATE M-A (binary):** (a) `theo` reports **87.8% agent-marked (1886/2149)** and the model ladder resolves to 4.5/4.6/4.7/4.8 with the expected rough counts; (b) the 11 web-UI commits and the Robyn co-author are NOT flagged agent; (c) new marker tests pass; (d) **PR-mode regression: OSWv2's agent-marked output is byte-identical to before** (GitHub-mode already scanned full messages — these changes must not move it). STOP for review.

## Sweep re-run + analysis framing  ⟵ before Sunday, immediately after M-A passes
Re-run marker detection across the **frozen cohort** with the hardened detector, identically for every repo. **Pre-registration integrity:** this is an instrument fix applied uniformly, not a cohort change or a per-repo tweak — document it as such in the sweep log (what changed, that it ran on the same frozen list, the timestamp). Report agent-marked strictly as a **≥ lower bound**; do not let any repo's low marks be read as "human." Surface the before/after of the detector change so the improvement is auditable.

**Two things the theo session added (lock these before Sunday analysis):**
1. **Lead with the author-agnostic DRIFT findings (THESIS §8c), demote agent-marked.** The published headline is the **rework triad + survival** — the strong signal, independent of marker quality. Agent-marked is a clearly-labeled ≥ lower bound, context not headline. Do NOT headline "agent code is X% worse" off marked-share — that is the side most exposed to the detection gap. The two-extremes proof (erpnext vs OpenClaw) is the most exposed: loudest lower-bound caveat, OpenClaw stays anonymized.
2. **Document the cohort-selection caveat (NOT a fix — membership is frozen).** `cohort_select.py` selected the agent cohort by the SAME limited marker search (Co-Authored-By: Claude / Generated-with / Copilot / Codex), baseline = <5% marked. So agent-heavy repos using non-listed tools (Lovable/Windsurf/Cline/v0/Cody) may sit in baseline. Membership can't change (pre-registration) — so document it, and note the direction is favorable: it **dilutes** the agent/baseline contrast, making any difference found **conservative/understated, not inflated.**
3. **DEEP RE-MINE, not just a marker re-run (overrides the earlier "keep it shallow" call — Matt, 2026-06-13).** Greg's scan proved the git data is far richer than 0.3.0 extracted *and* richer than we analyzed from what we already pulled. Re-mine the frozen cohort for everything now visible, and split the reporting by confidence:
   - **FIRST, cheap check:** the sweep is PR-mode, so it already captured Co-Authored-By trailer *strings* (which contain model names). **The per-commit MODEL data is very likely already in the captured per-repo audit JSONs (`ai_marked.per_unit`) — parse it before re-mining.** ~80% recoverable with zero new extraction.
   - **Model-durability (STRONG, exploratory):** survival + rework split by authoring model (4.5/4.6/4.7/4.8) across the agent cohort. Objective (real trailers), genuinely new, headline-worthy. The standout finding Greg's scan unlocked.
   - **Hardened markers + identity (STRONG):** higher marker coverage (broader tool list, author/committer identity, other trailer keys) — a tighter lower bound.
   - **Escape rings + origin quadrants (EXPLORATORY, lexical lower-bound):** extract and report, but clearly labeled hypothesis-generating until connectors + human-confirm. Don't suppress them — label them.
   - **Integrity:** same frozen cohort (pre-registration of membership intact). Pre-registered analysis (rework triad, agent-vs-baseline) = **confirmatory**, as planned. All new axes = **exploratory**, discovered mid-stream, labeled as such. That split publishes "a lot more than we thought" without touching the pre-registration.

## Phase M-B — report redesign: "drift report with provenance"  (after Sunday is fine)
theo reframed the report from an *AI-rework report* into a *drift report with provenance*. Drift is the spine and the headline; attribution + model are a clearly-secondary lower-bound provenance layer. Rebuild the report's hierarchy and framing, in commit-mode (gate on mode; PR-mode rendering must stay byte-identical, verified on OSWv2). Same template adapts via "render only measured signals."

**New top-to-bottom hierarchy:**
1. **Mode/unit banner:** state what's measured ("measuring 2,149 commits, commit-mode") so the reader interprets correctly.
2. **DRIFT HEADLINE (the spine) — lead with survival + corrective-LINE%, NOT corrective-unit%.** theo proved corrective-unit% is title-inflated (999/1080 fired on `fix:`/`revert` message discipline). Headline reads like: *"44% of this code did not survive; 31.5% of changed lines were corrective."* Keep corrective-unit% in the body, explicitly caveated as title-signal-dependent.
3. **Hotspots** — where drift concentrates (already exists).
4. **PROVENANCE (secondary, clearly a lower bound):** attribution + the model timeline. Never a headline %.
   - Attribution: `count>0` → "≥X% agent-marked (lower bound — agent *involvement*, not share of lines)". `count==0` → *"no agent markers present — authorship not determinable from this history; the drift above is author-agnostic and stands regardless."* **Never "0.0%."**
   - **Model timeline + durability-by-model (NEW, uses M-A's structured model field):** which model authored work over the repo's life, and survival/rework split by model. theo: 4.5→4.6→4.7→4.8. This is the differentiated, CIO-facing panel — also a standalone Commensa Index / marketing artifact.
5. **Velocity context** (already exists).
6. **LIMITS / MEASUREMENT BOUNDARY box — prominent, not fine print (this IS the brand, §8b).** Must state plainly:
   - **"This measures committed work and post-commit drift. The in-session generate→reject→regenerate loop — where most agent drift actually happens — is invisible to git and requires the harness to capture."** (So survival is survival of *committed* lines; true AI-output→durable is lower and uncaptured.)
   - agent-marked is a floor; absence ≠ human; markers flag involvement, not proportion of lines.
   - commit-mode reads rework higher than PR-mode — do not cross-compare modes.
   - squash/rebase hides rework; drift is descriptive, not causal; survival ≠ value (the customer's gate defines value).

**Also suppress in commit-mode:** `abandoned` (structurally always 0 — every commit is `merged=1`); relabel "PRs" → "commits" everywhere (report.py + audit JSON `method` strings + CLI summary). General rule: **a panel self-suppresses when its mode can't support its data; no metric ever headlines a structurally-zero number.**

**GATE M-B:** theo report leads with drift, renders the model/durability panel, attribution is a labeled lower bound (never 0%), the measurement-boundary box is present and prominent; OSWv2 PR-mode report byte-identical. STOP.

## Phase M-C — merge handling + Gate D-A re-run  (after Sunday is fine)
1. Add a **merge-commit-under-`-z` unit test** (synthetic repo with a real merge) covering the NUL-leak the hotfix patched.
2. **Re-run Gate D-A** — confirm the NUL fix + the new messages pass didn't regress the 12/12 numstat fidelity.
3. **Expose `--no-merges` on the CLI** and default commit-mode audits to it (merges land as empty units that dilute corrective-unit%); document the choice.
**GATE M-C:** merge test passes, Gate D-A 12/12, `--no-merges` works. STOP.

## Guardrails (bugs if violated)
- PR-mode (GitHub) output must not move — OSWv2 is the regression anchor for both markers and report rendering.
- Marker detection stays a **lower bound**; never claim "human" from absence. Identity scan must not false-positive on platform identities (GitHub web UI).
- Bodies/messages stay **off disk** — scan in-memory, persist only marker results + the structured model field.
- One gate per session; do not self-declare passed (working rule 2) — STOP for Matt review.

## Suggested session order
M-A (this session) → sweep re-run → [Sunday analysis] → M-B → M-C.
