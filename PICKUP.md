# PICKUP — commensa-audit

**What this is:** the Commensa audit CLI — repo in, one-page AI Rework Report out. Phase 0 of `../execution/launch_plan.md`. Owner: Matt Buscher. **Read SPEC.md before writing any code.**

**Status:** **ON PyPI (Session 7, 2026-06-12): `pip install commensa-audit` → 0.3.0.** Public repo https://github.com/commensa-ai/commensa-audit (MIT, README live), 55/55 tests. **0.3.0 = extraction limiting** — `--since YYYY-MM-DD` + `--max-prs N` (newest-first, early-stop pagination), with a **default safety cap of 500 PRs** (printed raise-it notice; `--max-prs 0` = no cap). Library default stays unlimited so Gate A is byte-identical (re-proven: 0 locked-field drift). Prior: 0.2.1 = the 0-PR empty-state honesty fix (`50ee2e3`). Each release clean-venv verified from PyPI and tagged. **Left for Matt: the Day 3–4 posting** (flagship post, Show HN, cold batch #1 per ../execution/tasks.md) — see the OSS-sweep caveat in Parked ideas before posting big-repo numbers.

## Folder map
- `SPEC.md` — the build spec: metrics, classifier, phases A/B/C with binary gates — THE MAP
- `BUILD_LOG.md` — session log + token/correction tracking (dogfooding rule; update every session)
- `pyproject.toml` — package metadata (deps: requests + jinja2, the SPEC maximum)
- `commensa_audit/` — the package: `cli.py` (entry), `units.py` (units.csv schema — the extractor↔engine contract), `engine.py` (stdlib metrics port, regression-verified vs reference), `extractors/github.py` (read-only paginated extractor), `patches.py` + `rework.py` (line-attribution replay: edges/supersession/survival), `classify.py` (signal cascade + CONFIG block), `report.py` (Phase C one-pager: template + brand, limits parsed from rework.py docstring)
- `tests/` — stdlib unittest suite (`python3 -m unittest discover tests`)
- `quality/` — gate artifacts: `gate_b_eval.py` (agreement vs Pilot 1), `gateB_spotcheck.md` (Matt's 10-PR check), `gateB_eval_output.txt`, `audit_order-sheet-web-v2.json`
- `reviews/` — red-team verdicts (`gateA_redteam.md`)
- `reference/` — proven prior code + known-good data (read, port, don't import blindly):
  - `commensa_validate.py` — metrics engine (survival, slop score, rank-correlation, no scipy)
  - `inversion_test.py` — Pilot 1 analysis script
  - `orderwebv2_units.csv` — 162 PRs ground truth (Gate A regression target)
  - `LABEL_THESE.csv` — Matt's 30 win/neutral/slop labels (Gate B check)
  - `RESULTS_pilot1.md` — why rework is the headline metric (context)

## Working rules for build sessions
1. One phase per session. Phase gates are binary — A: reproduce the 162-PR dataset · B: ≥80% classifier agreement + Matt spot-check · C: Matt would forward the report. Don't start the next phase in the same session a gate passes; stop, let Matt review.
2. Builder/reviewer split: this session builds; a separate fresh session (or Cowork) red-teams the phase output against SPEC.md acceptance criteria before the gate is called passed.
3. Update BUILD_LOG.md and this PICKUP before ending every session.
4. Scope discipline: anything not in SPEC.md v1 scope gets logged under "Parked ideas" below, not built.
5. Guardrails in SPEC.md are bugs if violated: read-only, local-first, no unsupported claims, stdlib+requests+jinja2 only.

## Current priority
**Matt's lane (his accounts, not a build session):** Day 3–4 posting per ../execution/tasks.md (flagship + Show HN, numbers re-verified) — the only open item; 0.3.0 is published, tagged, and reconciled with git. Build-side next: nothing queued — new work starts from a fresh design conversation or tasks.md. **Before posting any big-repo audit, read the OSS-sweep caveat in Parked ideas** (the explicit-title signal over-counts rework on human-driven repos).

## Next after Gate C
~~This folder becomes its own GitHub repo~~ — DONE (S6): live at github.com/commensa-ai/commensa-audit, self-audit shipped in `quality/`. Now in launch_plan.md Phase 1 / tasks.md Day 3–4 territory.

## Parked ideas
(log here during build; review weekly)
- **OSS-sweep caveat — explicit-signal over-counts rework on human-driven repos (S7 big-repo proof).** On a public OSS repo doing ~150 PRs/week with disciplined conventional-commit titles, the `explicit` title signal fired heavily on `fix:` + backport titles, while line-share / survival / cluster signals all read healthy. Single-digit % of PRs carried agent markers. The headline %-of-PRs metric is misleading on repos that aren't agent-driven. Before the OSS sweep publishes cross-repo claims, gate the rework-tax headline on agent-marked share and/or add a "explicit-dominant + low-agent-marked" caveat to the report. 0.3.0+ classifier work. (Per-repo identity withheld per protocol §"per-repo data stays private.")
- ~~Detect closed-unmerged PRs as "abandoned attempts"~~ — SHIPPED in v1.1 (S5) as the abandoned-attempt rate.
- `count_superseded_as_corrective` config toggle — Pilot 1 grouped superseded PRs with corrective; v1 reports supersession as a separate flag. Revisit after more labeled repos. (S2)
- Agent-marker identity list (`markers.py AGENT_IDENTS`) as a maintained/configurable registry — new agents appear monthly; could also attribute rework BY agent once N marked repos exist. (S5)
- Hotspots drill-down: second-level dirs for monorepos where one top-level dir dominates (OSWv2: frontend = 115/162 PRs ≈ repo-wide by construction). (S5)

## Warnings
- GitHub API: verify current pagination/rate-limit behavior before writing the extractor — don't code against memory.
- The 162-PR dataset is the only ground truth; if Gate A numbers drift, the bug is in the new extractor, not the reference data.
- Token data does NOT exist in git — any temptation to estimate tokens in v1 violates the no-unsupported-claims guardrail.
