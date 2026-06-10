# Gate C red-team (technical half) — PASS · awaiting Matt's forward test

Reviewer: Cowork session, overnight 2026-06-09→10. Method: independent test run + full inspection of both rendered reports.

## Verified against the gate requirements
1. **All 23 tests pass** in an independent sandbox run.
2. **Two-line waste headline: exactly as decided.** "The waste, in two lines" — rework tax (27.2% / 44 of 162 / 12.9% of lines, with signal breakdown) beside superseded (7 PRs, 448 lines), with the literal sentence "the two numbers are shown together, never merged." Matt's Gate B decision implemented faithfully.
3. **Brand:** the Durable = renders inline in the header with the tagline — and doubles as the report's centerpiece visualization (the generated-fragments-over-survived-bar chart IS the logo's meaning, drawn from real data). Palette matches brand.md.
4. **Honest-limits footer:** present and substantive — heuristic classification, exact-content attribution limits, rename/direct-push blind spots, young-repo survival caveat, "no token or energy claims — git does not record them," local-only generation note.
5. **CTA:** commensa.ai footer block, correctly framed (free snapshot → continuous version with the spend numerator).
6. **Transparency:** all 162 PRs listed with verdict + the signal that fired (collapsed details element — right choice for a one-pager).
7. **Dollar figure labeled as estimate with its basis shown** (--cost-per-pr 400 × 44). Velocity context carries the LOC-trap disclaimer.
8. **Both renders exist:** order-sheet-web-v2 (full case, 51KB self-contained) and jarvis (sparse/empty-state case) — the empty-state test was the right extra mile.
9. **jinja2 addition:** SPEC-allowed, Ladder-justified in BUILD_LOG (autoescape vs attacker-ish PR titles — correct reasoning).

## Nits (Matt's forward-test eyes, not blockers)
- "$17,600 — estimate, basis: --cost-per-pr 400.0" leaks CLI flag syntax into exec-facing copy; render as "based on $400/PR (your input)."
- The "superseded only 0.5%" fragment in the bar is nearly invisible at that share — acceptable, but check it reads at a glance.

## Verdict
**Technical half: PASS.** Remaining: Matt opens `quality/report_order-sheet-web-v2_2026-06-09.html` and answers the only question that matters: *"Would I forward this to another executive?"* Yes → Gate C passes → go-live checklist (launch_plan.md Phase 1).

---

## v1.1 addendum (2026-06-10) — PASS
Four additions verified in the fresh render (report_*_2026-06-10.html): abandoned attempts (2, 1.2%, method note) · hotspots panel (dir-level, <5-PR suppression) · AI-marked "at least 75.9%" (lower-bound framing correct; trailers + body signatures) · external-norms context line (labeled external). 37/37 tests run independently; full re-extraction reproduced all v1.0 numbers; transport-retry fix shipped from a live failure.
**Content correction triggered:** the flagship draft's "devices 35%" claim was a hand-run artifact — dir hotspots are flat; the dark-mode cluster is the true concentration story. Draft updated.
**Capability discovered:** Co-Authored-By trailers carry MODEL identity (Opus 4.7 vs 4.8) → git-native lower-bound model split (26% vs 34% corrective, equal survival — phase-confounded, capability not claim). Filed for the model-durability layer + OSS sweep cohorting.
**Forward test now runs on the 2026-06-10 renders.**
