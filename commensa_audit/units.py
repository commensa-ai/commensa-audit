"""units.csv schema — the contract between extractors and the engine.

One row per unit of work (a PR on GitHub). This schema is the Gate A
regression target (reference/orderwebv2_units.csv) and the only interface
an extractor is allowed to emit.

Format notes, locked to the reference file:
- Titles are sanitized (commas and double quotes removed) so the CSV needs
  no quoting; the reference file contains zero quoted fields.
- csv.writer's default line terminator (CRLF) is kept — the reference file
  is CRLF-terminated.
- merged / looks_revert are 1/0 integers.
"""

from __future__ import annotations

import csv
import re
from typing import Iterable

UNIT_FIELDS = [
    "unit_id",
    "title",
    "created_at",
    "merged",
    "lines_added",
    "lines_deleted",
    "changed_files",
    "looks_revert",
]

_INT_FIELDS = {"merged", "lines_added", "lines_deleted", "changed_files", "looks_revert"}

# Word starting with "revert" anywhere in the title (Revert/Reverts/Reverted...),
# case-insensitive. Matches GitHub's own 'Revert "<title>"' convention.
# (?<![\w-]) blocks hyphen-joined negations like "non-reverting" — Gate A
# red-team finding, reviews/gateA_redteam.md.
REVERT_RE = re.compile(r"(?<![\w-])revert", re.IGNORECASE)


def sanitize_title(title: str) -> str:
    """Make a PR title CSV-safe without quoting: drop commas, double quotes,
    and any stray newlines; trim outer whitespace."""
    for ch in (",", '"', "\r", "\n"):
        title = title.replace(ch, " " if ch in ("\r", "\n") else "")
    return title.strip()


def looks_revert(title: str) -> int:
    return 1 if REVERT_RE.search(title) else 0


def write_units_csv(path: str, rows: Iterable[dict]) -> int:
    """Write rows (dicts with UNIT_FIELDS keys) to path. Returns row count."""
    n = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=UNIT_FIELDS, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)
            n += 1
    return n


def read_units_csv(path: str) -> list[dict]:
    """Read a units.csv back into typed dicts (ints coerced)."""
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for k in _INT_FIELDS & row.keys():
                row[k] = int(row[k])
            out.append(row)
    return out
