# BUILD_LOG — commensa-audit

Dogfooding rule (SPEC.md): every build session logs date, what shipped, approx tokens, corrections. This log's own rework tax is launch content.

| # | Date | Phase | What shipped | ~Tokens | Corrections/redirects | Notes |
|---|------|-------|--------------|---------|----------------------|-------|
| 0 | 2026-06-09 | spec | SPEC.md + PICKUP.md + reference/ staged (Cowork session) | — | — | handoff package, no code yet |
| 1 | 2026-06-09 | A | `commensa_audit/` package (pyproject, CLI, units schema, stdlib engine port, GitHub extractor). Gate A run vs order-sheet-web-v2: **162/162 PRs, 0 numeric-field mismatches** | ~80k (est.) | 0 code corrections (engine regression + extractor both passed first run); 1 operator redirect (re-root session in project dir) | see Session 1 notes below |
| 2 | 2026-06-09 | B | classifier + churn clusters + supersession + survival (`rework.py`, `classify.py`, `patches.py`; extractor emits `prs.jsonl` sidecar; CLI emits `audit_<repo>.json`). looks_revert red-team fix + 16 unit tests. **Gate B eval: 93.3% agreement (28/30)**, spot-check sheet ready | ~120k (est.) | 2 self-corrections during build: signal-2 over-fired (share-of-deletions → share-of-work), clusters were co-location blobs (file overlap → relative rework edges). Both caught by inspecting real output before eval | see Session 2 notes below |
| 3 | 2026-06-09 | C | `report.py` — one-page self-contained HTML report (jinja2), wired into CLI. Rendered for **order-sheet-web-v2 + jarvis** (sparse/empty-state case), visually self-reviewed via browser preview. 7 new tests (23 total) | ~100k (est.) | 3 self-caught fixes during visual review (non-deterministic cluster anchor file → per-cluster rework-weighted ranking; "superseded only" label; zero-share fragment slivers). 0 operator corrections | see Session 3 notes below |
| 4 | 2026-06-10 | C-nit | Gate C red-team nit fixed (Cowork): `estimate_basis` now reads "$400 per PR (your input) × N" instead of leaking CLI flag syntax — cli.py for future runs + patched into the existing quality/ artifacts (display label only, no data change). 23/23 tests pass | ~5k | 0 | sliver-legibility nit left to Matt's eye at forward test |
| 5 | 2026-06-10 | v1.1 | Four report additions (tasks.md Day 2–3): abandoned-attempt rate, module hotspots, agent-marked lower bound (`markers.py` + commits API), external-norms context line. Extractor: +state/closed_at/ai_markers in sidecar, +commits fetch, transport-timeout retry. 37 tests (14 new). Fresh re-extraction both repos; **v1.0 numbers reproduce exactly; Gate B regression still 93.3%** | ~90k (est.) | 3 test failures self-caught first run (marker double-match ×2, test text-case ×1); 1 robustness fix mid-run (extractor crashed on a network ReadTimeout — transport errors now retry with backoff) | see Session 5 notes below |

## Session 1 notes (Phase A)

**Engine port verification:** reference `commensa_validate.py` uses numpy/pandas/matplotlib — disallowed (SPEC: stdlib+requests+jinja2). Ported to pure stdlib in `commensa_audit/engine.py`; rank-average + Pearson + Spearman hand-rolled (no scipy, as in reference). Regression-tested by feeding the reference's own synthetic(120) data through both engines (matplotlib stubbed): all 4 rho values, 3 label means, and verdict **identical** (diff < 1e-15). `chart()` not ported (matplotlib) — Phase C HTML report replaces it. Engine keystone path needs `tokens`/`surviving_lines` columns (validation datasets / Phase B output), not the git-only extractor schema — raises a clear error, documented in module docstring.

**Dependencies:** nothing added beyond stdlib + requests. jinja2 deferred to Phase C.

**GitHub API (verified against docs.github.com 2026-06-09, per PICKUP warning):** list endpoint (`/pulls?state=all`, per_page max 100, Link-header pagination) does NOT carry additions/deletions/changed_files → one GET per PR (163 requests total for this repo; authenticated limit 5,000/hr). Headers: `application/vnd.github+json` + `X-GitHub-Api-Version: 2026-03-10`. Extractor is GET-only (read-only guardrail), retries 5xx with backoff, honors Retry-After/X-RateLimit-Reset on 403/429.

**Gate A result:** 162 rows both files; unit_id/created_at/merged/lines_added/lines_deleted/changed_files/looks_revert match **162/162**. 158/162 rows byte-identical. 4 rows (PR-51/72/75/76) differ in title text only: the pilot extractor transliterated `→`→`->`, `"`→`in`, `§`→(removed); live GitHub titles verified to contain those characters. New sanitizer removes commas/quotes and keeps Unicode — the pilot's `"`→`in` rule was dataset-specific (inch marks in cabinet titles) and would corrupt GitHub's standard `Revert "..."` convention on any other repo, so it was deliberately not replicated. Line counts unaffected.

**Reproduce:** `GH_TOKEN=$(gh auth token) python3 -m commensa_audit --repo mattlaptopsanytime-collab/order-sheet-web-v2 --out /tmp/commensa_gateA && diff /tmp/commensa_gateA/units.csv reference/orderwebv2_units.csv`

**Per working rule 2:** gate not self-declared passed — criteria met, pending red-team session + Matt review.

## Session 2 notes (Phase B)

**Carried in:** looks_revert false-positive fixed (`(?<![\w-])revert`, test added per reviews/gateA_redteam.md). Gate A regression re-verified after the change — units.csv unchanged.

**What was built:**
- `patches.py` — unified-diff parsing of the PR files API `patch` field (verified against docs: per_page 100, 3000-file cap, patch absent on binary/huge).
- `rework.py` — line-attribution replay: walk merged PRs in merge order, attribute live lines to the PR that added them (rename-aware, trivial lines excluded). One pass yields rework edges (self-correction), supersession, survival. Honest limits in the module docstring, destined for the report footer.
- `classify.py` — SPEC signal cascade (explicit → self_correction → churn_cluster → generative) + the tunable CONFIG block. Every classification carries the signal + a human-readable why.
- Extractor now also emits `prs.jsonl` (files+patches+merged_at+raw title); engine side never touches the API (architecture rule held). CLI: full pipeline + `--reuse` for offline re-classification.
- 16 unit tests (`tests/test_phase_b.py`), incl. the red-team regression.

**Two mid-build corrections (the dogfooding data):** first real run classified 79% of PRs corrective. (1) Signal 2 measured recent-deletions as a share of *deletions* — in a 13-day repo every deletion is "recent", so it fired on normal iteration; now measured as share of the PR's total attributable work (≥33%, ≥10 lines) = "undoing dominates". Also fixed intra-PR moves counting as self-rework edges. (2) Churn clusters via file co-location produced 42-PR transitive blobs (every PR touches globals.css/PICKUP.md); relinked on *substantial rework edges* (≥10 lines AND ≥25% of upstream's added lines) — isolates exactly the dark-mode saga (PR-136/138/139/141) and the PillStack saga (PR-8/10/12), stable across frac 0.2–0.3 (not knife-edge). Deviations documented in rework.py docstrings.

**Gate B result:** agreement with Pilot 1 grouping (reconstruction documented in `quality/gate_b_eval.py` — 6 title-explicit + PR-138 superseded; arithmetic matches RESULTS_pilot1.md 4/2/1) = **28/30 = 93.3%** strict AND with the corrective-or-superseded variant. Disagreements (documented, product learning): PR-139 (pilot win-generative; classifier churn-member + 100% superseded by the revert) and PR-138 (pilot corrective-because-superseded; v1 keeps superseded as a flag, not a classification — the correcting PR is the corrective one). Final headline: 27.2% of PRs / 12.9% of changed lines corrective; 2 clusters; 7 superseded; 91.7% line survival.

**Artifacts for Matt's spot-check:** `quality/gateB_spotcheck.md` (10 classifications + accept/reject), `quality/gateB_eval_output.txt`, `quality/audit_order-sheet-web-v2.json`. Reproduce: `python3 -m commensa_audit --repo … --out DIR [--reuse]` then `python3 quality/gate_b_eval.py DIR/audit_order-sheet-web-v2.json`.

**Parked (added to PICKUP):** closed-unmerged PRs (e.g. PR-123) as "abandoned attempts" — not visible to the replay; successor PRs are caught instead.

**Per working rule 2:** Gate B not self-declared passed — ≥80% criterion met, pending Matt's 10-PR spot-check (the second half of the gate).

## Session 3 notes (Phase C)

**Dependency:** jinja2 3.1.6 installed (`python3 -m pip install jinja2`) and added to pyproject — explicitly allowed by SPEC ("stdlib + requests + jinja2 max") and unlocked for Phase C by Matt; Ladder justification: HTML templating with autoescape (titles are attacker-ish input — PR titles can contain markup) beats hand-rolled string formatting on both safety and maintainability.

**What was built:** `commensa_audit/report.py` — single-file template + renderer. Per SPEC + Gate B decisions: two-line waste headline (rework tax | superseded, side by side, never merged — Matt's D, reviews/gateB_redteam.md); three evidence panels (churn clusters with full PR sagas, supersession who-replaced-whom, survival with lowest-survivor list); velocity context strip (LOC-trap note); collapsible per-PR table (162 rows, every verdict + signal — SPEC transparency); honest-limits footer **parsed from rework.py's module docstring at render time** (single source of truth, cannot drift — `honest_limits()`); the Durable = brand strip drawn with the repo's real numbers (fragmenting generated bar over solid teal survived bar); commensa.ai CTA per messaging.md §Distribution. Brand vendored (mark SVG + palette + tagline from ../marketing/) so the report is fully self-contained: no scripts, no external resources, only outbound href is the CTA (verified by test).

**Renders (Gate C candidates, in `quality/`):** `report_order-sheet-web-v2_2026-06-09.html` (162 PRs, with `--cost-per-pr 400` exercising the labeled dollar estimate: ≈$17,600) and `report_jarvis_2026-06-09.html` (3 PRs — the sparse/empty-state robustness case: 0% tax, empty-state copy, no division blowups). Note: jarvis was the only viable second repo — all other repos on the account use direct-push (0–2 PRs).

**Visual self-review (browser preview, per the build-agents-self-verify rule):** full-page + a11y-tree verification of every section on both reports. Caught and fixed: (1) cluster anchor file was non-deterministic across runs (set-iteration tie-break) and then wrongly global — now ranked by THIS cluster's internal rework lines per file (`edge_files` tracking), deterministic, verified identical across re-runs; (2) fragment label "superseded" → "superseded only" (corrective-classified superseded PRs sit in the corrective bucket); (3) zero-share fragments hidden. Determinism re-verified: same sidecar → byte-identical cluster JSON across runs.

**Tests:** 23/23 (7 new in `tests/test_phase_c.py`: two-line headline present + "never merged", brand palette + tagline + mark, CTA href is the only external URL, no `<script>`, dollar line labeled estimate, PR titles HTML-escaped, limits sourced ≥5 bullets from rework docstring, empty-states render).

**Gate C status (per working rule 2, not self-declared):** renders for two repos ✓ — Matt's forward-test ("I would forward this to another executive") is the gate itself, pending. If it fails, iterate the report, not the metrics (SPEC).

## Session 5 notes (report v1.1 — tasks.md Day 2–3 item 1)

**The four additions, with the choices they forced:**
1. **Abandoned-attempt rate** — closed-unmerged PRs ("N attempts shipped nothing"), slim strip in the headline area under the two waste cards (the two-line never-merge rule untouched). Needed PR `state` — units.csv `merged=0` can't distinguish closed from open; sidecar now carries `state`+`closed_at`, open PRs counted separately as in-flight, not abandoned. OSWv2: **2 abandoned (PR-123, PR-153)** — exactly the known pair; the parked S2 idea is now a shipped metric.
2. **Hotspots by module** — corrective share by top-level dir vs repo-wide, min 5 PRs/dir (1 dir suppressed on OSWv2), a PR counts in every dir it touches (documented). OSWv2 truth: no positive outlier (frontend 27.0% ≈ repo-wide 27.2%; docs 14.3%, root 7.1%) — the panel renders honest flat data; customer repos with real hotspots will show positive deltas.
3. **AI-marked share** — **both** marker sources, decision documented: PR body comes free in the detail call we already make; Co-Authored-By trailers need the commits API (verified against docs 2026-06-10: per_page 100, **250-commit cap per PR** — a stated limit) at +1 call/PR ≈ 162 extra calls, well inside 5,000/hr — so commit-level was NOT too expensive and v1.1 uses both. `markers.py`: trailer must name a known agent identity (plain Co-Authored-By is human pairing, not flagged — tested); body signatures ("Generated with Claude Code", 🤖). Sidecar stores marker strings only, never bodies/messages (local-first, lean). OSWv2: **at least 75.9% (123/162)**; jarvis: 100% (3/3). Labeled lower bound everywhere; "absence of a marker ≠ human" in strip AND footer.
4. **"How to read this number"** — Code Turnover Rate norms from ../references/competition.md (healthy <15% @30d; AI teams 1.8–2.5× human baselines, target <1.5×; larridin.com), rendered under the rework tax with the explicit label "external published research, not a Commensa benchmark; methods differ from the rework tax above" — repeated in the footer.

**Guardrails:** read-only held (GET-only incl. commits); deps still requests+jinja2; no token/energy claims; every new number's method + limits in the footer (verified by test + grep). Version → 0.2.0a1.

**Regression:** fresh full extraction both repos (~490 calls OSWv2). All v1.0 numbers reproduce exactly (27.2%/12.9%, 2 clusters, 7 superseded, 91.7% survival); `quality/gate_b_eval.py` on the fresh audit: still 28/30 = 93.3%. 37/37 tests. Visual review via browser preview: headline strip, norms line, hotspots panel, footer bullets all verified on both repos.

**Robustness fix shipped mid-session:** first live run died on a `requests.ReadTimeout` — `_get` retried HTTP status codes but not transport errors; now retries Timeout/ConnectionError with exponential backoff (the kind of bug only a real run finds).

**Artifacts:** `quality/report_order-sheet-web-v2_2026-06-10.html`, `quality/report_jarvis_2026-06-10.html` + matching audit JSONs. **STOPPED per instruction** — pending red-team + Matt's forward test on the v1.1 renders.
