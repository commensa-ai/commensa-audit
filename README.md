# commensa-audit

**What % of your AI engineering effort went to fixing your AI's own work?**

`commensa-audit` answers that from your git history. Point it at a GitHub repo; get a one-page report:

- **Rework tax** — share of PRs (and changed lines) that corrected earlier work, vs. net-new value
- **Superseded work** — PRs whose output was entirely replaced later (shown separately — discarded ≠ correcting)
- **Abandoned attempts** — PRs closed without merging: the waste merge-based metrics never see
- **Churn clusters** — chains of PRs rewriting each other ("it took 10 PRs to get dark mode right")
- **Line survival** — how much merged code is still alive at the end of the window
- **Hotspots** — rework share by module, against the repo-wide rate
- **Agent-marked share** — "at least X% of PRs carry agent markers" (Co-Authored-By trailers, body signatures) — a stated lower bound, never an attribution claim

We built it because we needed it: our own agent-built product shipped 162 PRs in 13 days, and the audit showed **27% of them were the AI correcting itself**.

## Install & run

```
pip install commensa-audit
commensa-audit --repo owner/name --token $GH_TOKEN
```

Or straight from source:

```
pip install git+https://github.com/commensa-ai/commensa-audit
```

Output: `report_<repo>.html` (self-contained, forwardable), `audit_<repo>.json` (raw numbers), `units.csv` (per-PR data).

### Scoping large repos

By default the audit covers the **newest 500 PRs** — a safety cap so a naive run on a huge repo stays fast and bounded. When it truncates, the run prints a notice telling you how to raise it. Two optional flags control the window (both newest-first):

```
commensa-audit --repo frappe/erpnext --since 2026-03-14 --max-prs 150
```

- `--since YYYY-MM-DD` — only PRs created on/after this UTC date
- `--max-prs N` — cap to the N newest PRs (default `500`; use `--max-prs 0` for no cap)

Both early-stop pagination, so `--max-prs 150` costs ~150 PRs' worth of API calls, not the repo's entire history. Run with no flags on a repo under 500 PRs and you get everything, exactly as before.

## Privacy, by architecture

- **Read-only.** GET requests only; a token with read scope is sufficient.
- **Local-first.** Everything runs and stays on your machine. No telemetry, no phone-home, nothing leaves your network.
- **Inspectable.** Pure Python, stdlib + `requests` + `jinja2`. Read every line before you run it.

## How classification works (and its honest limits)

Every PR is classified by a transparent signal cascade — explicit corrective titles/reverts → self-correction (a PR predominantly undoing lines added in the prior N days) → churn-cluster membership → otherwise generative. Every classification in the output carries the signal that fired and a human-readable why. Thresholds live in one config block; tune them and re-run offline with `--reuse`.

Known limits (also printed in the report footer): classification is heuristic; squash merges blur attribution; survival windows mean young repos read optimistic; agent-marked share is a lower bound — absence of a marker is not evidence of human authorship. We grade our own certainty rather than fake precision — that's the whole point of the project.

## Why "rework tax"?

Agent-era teams measure activity — PRs merged, lines shipped, velocity. None of that distinguishes progress from cleanup. The rework tax does: it's the share of motion that was correction, the closest git-only proxy for "how well was this work directed?" It won't tell you everything (cost-per-outcome needs token data git doesn't have — that's [what we're building next](https://commensa.ai)) — but it's the most honest first number, and it's free.

## The continuous version

This tool is a snapshot. [Commensa](https://commensa.ai) is the trendline: continuous rework measurement by team and module, alerts, monthly executive reports — and the cost side git can't see, captured at the agent harness. First 25 companies: founding-partner terms.

**measure the durable work, not the noise.**

MIT licensed.
