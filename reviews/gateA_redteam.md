# Gate A red-team — PASS (with 1 minor, non-blocking finding)

Reviewer: Cowork session (independent of builder), 2026-06-09. Method: code review of all 517 lines + independent execution in sandbox.

## Verified independently
1. **CSV format fidelity:** read reference/orderwebv2_units.csv via the new `units.py`, wrote it back — **byte-identical round-trip** (CRLF, no quoting, schema preserved).
2. **Correlation math:** `spearmanr` checked against a known scipy value ([1,2,3,4,5] vs [5,6,7,8,7] → 0.8207826816681233) — **exact match**, ties handled correctly (method='average').
3. **Synthetic end-to-end:** `synthetic(120) → compute_metrics → analyze` runs clean on pure stdlib, sane GREEN verdict, all metric fields populated.
4. **Guardrails:** extractor is GET-only ✓; deps = requests only (jinja2 correctly deferred) ✓; no token estimation anywhere ✓; `looks_revert` computed on the RAW title before sanitization ✓ (sanitizer strips the quotes that GitHub's `Revert "..."` convention needs).
5. **Builder's 4-title-diff explanation:** sound. The pilot's `"`→`in` transliteration was dataset-specific and would corrupt revert detection on other repos; not replicating it was the right call.
6. **API handling:** Link-header pagination with params correctly dropped after page 1; 403/429 honors Retry-After / X-RateLimit-Reset; 5xx backoff; unauthenticated-rate-limit warning in CLI.

## Finding (minor, fix in Phase B — not gate-blocking)
- `looks_revert("non-reverting change")` → **1** (false positive: `\brevert` matches after a hyphen). Rare pattern, didn't affect Gate A (162/162 numeric match), but the Phase B classifier consumes this signal — tighten the regex (e.g., exclude `(?<!non-)` or require title-leading `Revert`) and add it to the classifier test set.

## Cosmetic (no action required)
- `engine.py` exports module imports (argparse, csv, math...) in its public namespace; `__all__` would tidy it.

## Verdict
**Gate A: PASS.** Acceptance criterion met (162/162 PRs, 0 numeric mismatches, title diffs explained and verified as correct behavior). Cleared for Phase B in a fresh session, carrying the looks_revert fix into the classifier work.
