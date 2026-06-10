# Pilot 1 results — order-sheet-web-v2 (30 labeled PRs)

Date: 2026-06-10. Rater: Matt (single, own code). Labels: 19 win / 3 neutral / 8 slop. Rubric: product/labeling_standard.md (judge worth, not size).

## Headline: the naive inversion FAILED
- **volume (lines) vs win: rho = +0.32** — bigger PRs were MORE likely wins, not less.
- Top-10 biggest: 7 win / 2 slop / 1 neutral. Bottom-10 smallest: 4 win / 5 slop / 1 neutral.
- → "less code = better / volume is the metric" is **dead** on this data. Kill it.

## The real signal: corrective-vs-generative (size was a confound)
| group | n | slop% | win% | mean lines |
|---|---|---|---|---|
| Generative (new features) | 23 | 17% | 74% | 268 |
| Corrective (fix/correct/superseded) | 7 | 57% | 29% | 69 |
- Corrective work is ~3× more likely to be slop. Small PRs looked sloppy only because **fixes/redos happen to be small.** The predictor is *rework*, not *size*. Validates the rework-tax metric (metrics_catalog.md A2) and Matt's labeling instinct.

## Honest caveats
1. N=30, single rater, own code — modest signal, not a verdict.
2. Corrective→slop is **partly induced by the rubric** (we told the rater corrective→slop). Suggestive, not independent.
3. **Wrong axis tested:** thesis = *tokens per durable outcome*; we measured *lines* (GitHub has lines, not tokens). A big clean feature ≠ slop. Lines can't test the real claim.

## The metric was always a RATIO — we only had the denominator
Lines = the OUTPUT (denominator). Tokens = the COST (numerator). The metric is **tokens per surviving line** — LOWER is better (tight direction); HIGHER = flailing/slop. Pilot 1 measured lines with no token cost attached, so it tested half the ratio and could not speak to the thesis. Example: 500 lines @ 8k tokens (~16 tok/line, tight) vs 500 lines @ 200k tokens (~400 tok/line, slop) — identical output, 25× burn.

## What this bought us
- Killed "lines alone = the metric" cheaply (lines is only the denominator).
- Pointed hard at **rework / corrective ratio** as the real signal (corrective PRs likely the token-expensive ones).
- Proved the real test needs the **numerator: token-per-PR from Claude Code logs** → compute tokens-per-surviving-line, then test against the win/slop labels.

## Next
1. Get token-per-PR from Claude Code logs → re-run as *tokens per durable outcome*, the actual thesis.
2. Add objective survival/supersession (git) as an independent outcome — cleaner than self-labels.
3. Bigger N + a second rater → inter-rater reliability on the standard.
