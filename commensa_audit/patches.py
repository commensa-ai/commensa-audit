"""Unified-diff patch parsing (the `patch` field of GitHub's PR files API).

Extracts added/deleted line *contents* in order. We deliberately work on
content, not positions: the rework model (rework.py) attributes lines by
exact content match, which survives the missing-base-state problem (we never
have the full file, only PR patches).
"""

from __future__ import annotations


def parse_patch(patch: str | None):
    """Yield ("+"|"-", line_content) for each changed line in a unified diff.

    Hunk headers (@@), file headers (---/+++), and the "\\ No newline at end
    of file" marker are skipped. A missing patch (binary / too-large diff)
    yields nothing.
    """
    if not patch:
        return
    for raw in patch.split("\n"):
        if raw.startswith("@@") or raw.startswith("\\"):
            continue
        if raw.startswith("+++") or raw.startswith("---"):
            continue  # not emitted by the API, but harmless to guard
        if raw.startswith("+"):
            yield "+", raw[1:]
        elif raw.startswith("-"):
            yield "-", raw[1:]
