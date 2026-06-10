# Gate B spot-check — 10 classifications for Matt

> Built 2026-06-09, Session 2. Source: `quality/audit_order-sheet-web-v2.json`
> (full per-PR detail), agreement table in `gateB_eval_output.txt`.
> SPEC Gate B: ≥80% agreement (**result: 93.3%**, 28/30 both variants) AND
> Matt accepts the explanations on 10 spot-checked classifications — that's
> this sheet. Mark each ACCEPT / REJECT.

| # | PR | Classification | Why (the signal that fired) | Pilot label |
|---|----|----------------|------------------------------|-------------|
| 1 | PR-141 `Revert to neutral palette site-wide` | corrective — explicit | revert title; the anchor of the dark-mode saga | (unlabeled) |
| 2 | PR-31 `fix: kiosk validator allows Bar Code` | corrective — explicit | conventional-commit `fix:` | slop ✓ |
| 3 | PR-9 `PillStack — correct order` | corrective — explicit | title token `correct`; PR-9 redid PR-8's layout same evening | neutral ✓ |
| 4 | PR-124 `(devices detail rework)` | corrective — self_correction | deletes 232 lines added <14d earlier, 223 of them PR-111's — the :8001-parity redo arc | (unlabeled) |
| 5 | PR-149 | corrective — self_correction | deletes 15 recent lines, mainly PR-148 (11) — Morgan migration docs redone next PR | (unlabeled) |
| 6 | PR-12 | corrective — churn_cluster | PR 3/3 in PillStack cluster (PR-8 → PR-10 → PR-12; each ~80% replaced by the next) | (unlabeled) |
| 7 | PR-139 `Dark-mode the remaining white components` | corrective — churn_cluster | PR 3/4 in dark-mode cluster; 100% of its lines replaced by PR-141 four PRs later | **win — DISAGREEMENT 1.** Pilot saw finished feature work; the classifier sees work that was redone and then fully reverted. Both true — judge worth vs durability. |
| 8 | PR-138 `Unify dark theme single navy/slate palette` | generative — but superseded_by PR-141 (100% replaced) | 2nd member of the cluster, no corrective signal fired; supersession reported alongside | **slop/corrective — DISAGREEMENT 2.** Pilot grouped superseded with corrective; v1 keeps "superseded" a separate flag (the PR generated work — it just didn't last). Tunable. |
| 9 | PR-3 `import: live Google Sheet CSV path` (1,393 lines) | generative | no signal fired; 1.4k-line import that stuck | win ✓ |
| 10 | PR-123 `feat(devices): restructure detail page` | generative | closed-unmerged so it never entered the rework replay; title has no corrective token | slop — known limit: the classifier can't see "abandoned attempt" yet; PR-125 (its successor) IS caught as explicit corrective. Logged as a Phase-C-or-later idea (PICKUP Parked). |

## Headline numbers (repo: order-sheet-web-v2, window 14d)

- **Rework tax: 27.2% of PRs (44/162), 12.9% of changed lines** — signals: 37 explicit · 5 self-correction · 2 churn-cluster
- **Churn clusters: 2** — dark-mode saga (PR-136/138/139/141, 350 internal rework lines) and PillStack saga (PR-8/10/12)
- **Superseded PRs: 7** (incl. all three dark-mode predecessors at 95–100% replaced)
- **Line survival: 91.7% overall, 98.4% median** (young repo — last merge 5 days before extraction; honest-limits note in JSON)
- Velocity context: 92.9 PRs/week, 98.8% merge rate, median PR +93 lines (context only, never a target)
