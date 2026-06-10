"""Agent-marker detection — the honest git-native answer to "how much of
this is AI?".

Two sources, both verified against docs.github.com 2026-06-10:
- PR body (already in the Get-a-pull-request response — zero extra calls):
  tool signatures like "Generated with Claude Code".
- Commit messages (List-commits-on-a-PR, per_page 100, capped at 250
  commits/PR): Co-Authored-By trailers naming an agent.

The result is a LOWER BOUND by construction: agents that leave no marker,
squashed-away trailers, and humans pasting agent output are all invisible.
The report must say "at least X%" — absence of a marker is NOT evidence of
human authorship.

Co-Authored-By alone is NOT an agent signal (humans pair-program); the
trailer must name a known agent/bot identity (AGENT_IDENTS).
"""

from __future__ import annotations

import re

# Known agent identities seen in Co-Authored-By trailers and bot accounts.
# Tunable; matched case-insensitively against the trailer's name/email.
AGENT_IDENTS = [
    "claude", "anthropic", "copilot", "cursor", "openai", "chatgpt", "gpt-",
    "codex", "gemini", "jules", "devin", "aider", "sweep", "dependabot",
    "renovate", "noreply@anthropic.com", "[bot]",
]

# PR-body / commit-body tool signatures.
BODY_SIGNATURES = [
    re.compile(r"generated with .{0,40}\b(claude|copilot|cursor|codex|chatgpt|gpt|gemini|devin|aider)", re.I),
    re.compile(r"\bco-?authored\b.{0,60}\b(claude|copilot|cursor|codex|chatgpt|gemini|devin|aider)", re.I),
    re.compile(r"🤖.{0,40}generated", re.I),
]

_TRAILER_RE = re.compile(r"^\s*co-authored-by:\s*(.+)$", re.I | re.M)


def detect_markers(body: str | None, commit_messages: list[str]) -> list[str]:
    """Return de-duplicated human-readable marker strings found for one PR."""
    found: list[str] = []

    def add(s: str):
        s = " ".join(s.split())[:120]
        if s.lower() not in {f.lower() for f in found}:
            found.append(s)

    for sig in BODY_SIGNATURES:
        m = sig.search(body or "")
        if m:
            add(f"body: {m.group(0)}")

    for msg in commit_messages:
        trailer_hit = False
        for m in _TRAILER_RE.finditer(msg or ""):
            ident = m.group(1)
            if any(a in ident.lower() for a in AGENT_IDENTS):
                add(f"commit trailer: Co-Authored-By: {ident}")
                trailer_hit = True
        if trailer_hit:
            continue  # signatures would re-match the same trailer text
        for sig in BODY_SIGNATURES:
            m = sig.search(msg or "")
            if m:
                add(f"commit message: {m.group(0)}")
    return found
