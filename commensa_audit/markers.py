"""Agent-marker detection — the honest git-native answer to "how much of
this is AI?".

Three signal sources (all evaluated; OR-merged, deduped):
1. **AUTHOR / COMMITTER IDENTITY** — name or email matches an agent allowlist
   (`Cursor`, `Copilot[bot]`, `Aider`, etc.). Guardrail: a platform identity
   like `GitHub <noreply@github.com>` is NOT an agent — a human using the web
   editor commits with that identity; it must stay unflagged.
2. **TRAILER KEYS** in the commit message body — beyond `Co-Authored-By`, we
   also count `Assisted-by:`, `Generated-by:`, `On-behalf-of:` when the
   value names an agent identity.
3. **BODY SIGNATURES** — looser narrative form ("Generated with Claude Code",
   the 🤖 marker) for repos that don't use trailers at all.

The result is a LOWER BOUND by construction: agents that leave no marker,
squashed-away trailers, and humans pasting agent output as themselves are
all invisible. The report must say "at least X%" — absence of a marker is
NOT evidence of human authorship.

When a marker also names a MODEL (e.g. `Claude Opus 4.6`), the structured
`{family, tier, version}` is captured per unit for downstream
durability-by-model analysis (Door 3). Surfacing the metric is M-B/optional;
capture happens now.
"""

from __future__ import annotations

import re

# Known agent identities. Necessarily incomplete (new ones appear monthly) —
# this list is a lower bound by construction. Matched case-insensitively as
# substrings against the candidate text (trailer value, identity, signature).
AGENT_IDENTS = [
    # Anthropic
    "claude", "anthropic", "noreply@anthropic.com",
    # GitHub / Microsoft / OpenAI
    "copilot", "openai", "chatgpt", "gpt-", "codex",
    # Google
    "gemini", "jules",
    # Independent / framework / IDE-integrated agents
    "cursor", "devin", "aider", "sweep", "dependabot", "renovate",
    "lovable", "windsurf", "cline", "roo", "bolt.new", "replit-agent",
    "amazon q", "codewhisperer", "tabnine", "cody", "sourcegraph",
    " amp ", "continue.dev", "augment", "codeium", "supermaven", "phind", "zed",
    # Generic bot suffix
    "[bot]",
]

# Platform identities that look bot-like but are NOT agents. A human using
# GitHub's web UI commits as `GitHub <noreply@github.com>` — manual edit
# through a browser, not an agent. Excluded BEFORE the agent allowlist check.
PLATFORM_IDENTS_NOT_AGENTS = [
    "noreply@github.com",       # github.com web UI commits
]

# Trailer keys that count as agent markers when the VALUE names an agent.
# Matched case-insensitively.
AGENT_TRAILER_KEYS = (
    "co-authored-by", "assisted-by", "generated-by", "on-behalf-of",
)
_TRAILER_RE = re.compile(
    r"^\s*(co-authored-by|assisted-by|generated-by|on-behalf-of)\s*:\s*(.+)$",
    re.I | re.M,
)

# Narrative body signatures — repos that DO mark agent work but don't use
# trailers. Each pattern captures enough context to identify the model.
BODY_SIGNATURES = [
    re.compile(r"generated with .{0,40}\b(claude|copilot|cursor|codex|chatgpt|gpt|gemini|devin|aider)", re.I),
    re.compile(r"\bco-?authored\b.{0,60}\b(claude|copilot|cursor|codex|chatgpt|gemini|devin|aider)", re.I),
    re.compile(r"🤖.{0,40}generated", re.I),
]

# Structured MODEL extraction — when a marker names a specific model
# ("Claude Opus 4.6 (1M context)"), capture {family, tier, version} per unit.
# Patterns are ordered: more specific first (family + tier + version) before
# bare-family fallbacks.
_MODEL_PATTERNS = [
    # Claude — optional tier (Opus/Sonnet/Haiku/Fable) + version like 5, 4.6, 4.6.1
    (re.compile(r"\bclaude(?:\s+(opus|sonnet|haiku|fable))?\s+([0-9]+(?:\.[0-9]+(?:\.[0-9]+)?)?)", re.I),
     "claude"),
    # GPT family with a version
    (re.compile(r"\b(?:chat)?gpt[-\s]?([0-9]+(?:\.[0-9]+)?)", re.I), "gpt"),
    # Gemini with a version
    (re.compile(r"\bgemini[-\s]?([0-9]+(?:\.[0-9]+)?)", re.I), "gemini"),
    # Codex with a version-like suffix
    (re.compile(r"\bcodex[-\s]([a-z0-9.-]+)", re.I), "codex"),
    # Bare family fallbacks (no version) — last so they don't shadow versioned matches
    (re.compile(r"\bclaude\b", re.I), "claude"),
    (re.compile(r"\bcopilot\b", re.I), "copilot"),
    (re.compile(r"\bcursor\b", re.I), "cursor"),
    (re.compile(r"\bgemini\b", re.I), "gemini"),
    (re.compile(r"\baider\b", re.I), "aider"),
    (re.compile(r"\bdevin\b", re.I), "devin"),
]


def looks_like_agent(text: str | None) -> bool:
    """Case-insensitive substring match against AGENT_IDENTS. Platform
    identities (GitHub web UI) are excluded FIRST so they never trip the
    allowlist."""
    if not text:
        return False
    text_lo = text.lower()
    if any(p in text_lo for p in PLATFORM_IDENTS_NOT_AGENTS):
        return False
    return any(a in text_lo for a in AGENT_IDENTS)


def extract_model(text: str | None) -> dict | None:
    """Return ``{'family': ..., ['tier': ...], ['version': ...]}`` when the
    text names a recognizable model. Returns None if no family resolves.

    ``tier`` and ``version`` are present only when they appear in the text.
    """
    if not text:
        return None
    for pattern, family in _MODEL_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        out: dict = {"family": family}
        groups = m.groups()
        if family == "claude" and len(groups) == 2:
            tier, version = groups
            if tier:
                out["tier"] = tier.lower()
            if version:
                out["version"] = version
        elif groups and groups[0]:
            out["version"] = groups[0]
        return out
    return None


def detect_markers(body: str | None,
                   commit_messages: list[str] | None,
                   author_identity: str | None = None,
                   committer_identity: str | None = None) -> dict:
    """Detect agent markers from every signal source.

    Returns ``{"markers": [str, ...], "model": dict | None}``.

    ``markers`` is the de-duplicated list of human-readable marker strings
    (the existing sidecar's ``ai_markers`` field consumes this list as-is;
    the strings for Co-Authored-By trailers match the pre-M-A wording
    verbatim so OSWv2's PR-mode output stays byte-identical).

    ``model`` is best-of structured ``{family[, tier][, version]}``; None
    when a commit IS marked but no model can be parsed (e.g. plain
    "Copilot" with no version).

    Args:
        body: PR body text (PR-mode) or commit body (commit-mode).
        commit_messages: full commit messages (subject + body for each).
        author_identity: ``"Name <email>"`` of the author, when known.
        committer_identity: ``"Name <email>"`` of the committer, when known.
            Used to flag GitHub web-UI commits as NOT-agent before any
            trailer scan.
    """
    markers: list[str] = []
    model: dict | None = None

    def add(s: str) -> None:
        s = " ".join(s.split())[:120]
        if s.lower() not in {m.lower() for m in markers}:
            markers.append(s)

    def take_model(text: str) -> None:
        nonlocal model
        if model is None:
            model = extract_model(text)

    # 1. Identity scan — author + committer. Platform identities short-circuit.
    for identity, label in ((author_identity, "author"),
                            (committer_identity, "committer")):
        if identity and looks_like_agent(identity):
            add(f"{label} identity: {identity}")
            take_model(identity)

    # 2. Body (PR description / commit body) — trailers first, then narrative
    #    signatures as fallback if no trailer fired.
    if body:
        trailer_hit_in_body = False
        for m in _TRAILER_RE.finditer(body):
            key, value = m.group(1).lower(), m.group(2).strip()
            if looks_like_agent(value):
                if key == "co-authored-by":
                    add(f"body trailer: Co-Authored-By: {value}")
                else:
                    label = "-".join(p.capitalize() for p in key.split("-"))
                    add(f"body trailer: {label}: {value}")
                take_model(value)
                trailer_hit_in_body = True
        if not trailer_hit_in_body:
            for sig in BODY_SIGNATURES:
                sm = sig.search(body)
                if sm:
                    add(f"body: {sm.group(0)}")
                    take_model(sm.group(0))

    # 3. Commit messages — trailers first per message; signatures fallback
    #    when nothing trailer-matched in THAT message.
    for msg in (commit_messages or []):
        if not msg:
            continue
        trailer_hit = False
        for m in _TRAILER_RE.finditer(msg):
            key, value = m.group(1).lower(), m.group(2).strip()
            if looks_like_agent(value):
                # Match the PRE-M-A wording exactly when key == co-authored-by
                # so OSWv2's saved ai_markers stay byte-identical.
                if key == "co-authored-by":
                    add(f"commit trailer: Co-Authored-By: {value}")
                else:
                    label = "-".join(p.capitalize() for p in key.split("-"))
                    add(f"commit trailer: {label}: {value}")
                take_model(value)
                trailer_hit = True
        if trailer_hit:
            continue
        for sig in BODY_SIGNATURES:
            sm = sig.search(msg)
            if sm:
                add(f"commit message: {sm.group(0)}")
                take_model(sm.group(0))

    return {"markers": markers, "model": model}
