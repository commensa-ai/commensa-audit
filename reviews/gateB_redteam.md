# Gate B red-team + Matt's spot-check — PASS

Reviewer: Cowork session, 2026-06-09. Matt's spot-check: completed (accepted; two disagreements resolved below).

## Verified
1. **All 16 unit tests pass** in an independent sandbox run, including the Gate A red-team regression (`looks_revert` false positive) and the Gate A row-match test re-verified after the regex change.
2. **Classifier config** (`classify.py` CONFIG): thresholds documented with reasoning; signal cascade matches SPEC (explicit → self_correction → churn_cluster → generative); every classification carries its signal + human-readable why (transparency requirement met).
3. **The two mid-build corrections were right and well-caught:** share-of-deletions → share-of-work (the 79% over-fire in a young repo) and co-location blobs → substantial-rework-edge clusters (stable across frac 0.2–0.3, not knife-edge). Both found by inspecting real output before the eval — the correct discipline.
4. **Agreement: 93.3% (28/30)** vs Pilot 1, reconstruction arithmetic checked against RESULTS_pilot1.md. Honest limits (squash, young-repo survival, abandoned attempts) documented and destined for the report footer.

## Decision resolved by Matt (2026-06-09) — headline waste definition
**Two lines, shown together.** Rework tax = corrective work only (27.2% of PRs / 12.9% of lines on OSWv2); fully-superseded work is its own adjacent headline line ("7 PRs entirely replaced") — correcting vs. discarded are different failure modes and the report shows both. PR-138-style cases stay "generative, superseded." Phase C report must render both lines side by side. (Long-term: customer-tunable — the configurable gate; default stays separate.)

## Known limits carried forward (not gate-blocking)
- Closed-unmerged PRs invisible to the replay ("abandoned attempts") — parked, successor PRs are caught.
- Live-API re-extraction not re-run by reviewer (token on Matt's machine); reproduce command documented in BUILD_LOG.

## Verdict
**Gate B: PASS.** Cleared for Phase C (the report) in a fresh session, with the two-line waste headline as a Phase C requirement.
