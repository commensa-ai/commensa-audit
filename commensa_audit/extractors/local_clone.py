"""Local-clone commit extractor — Phase D, commit mode.

Reads `.git` via subprocess git commands. NO network, NO host API. Yields one
unit per commit (vs one per PR in GitHubExtractor). The engine downstream is
the same; Phase D-B wires it to commit units.

Guardrails (SPEC.md + COMMIT_MODE_SPEC.md):
  - read-only (only `git log`, no writes)
  - local-only, no network in this mode at all
  - stdlib + subprocess only (no requests, no jinja2 dep on the extractor side)

Per-commit dict shape (what Gate D-A validates against `git log --numstat`):
  sha, parents, author_name, author_email, author_date,
  committer_name, committer_email, committer_date, subject,
  files: [{raw_path, path, rename_from, additions, deletions, binary}]

`raw_path` is exactly what `git log --numstat` emits (rename arrows intact).
`path` and `rename_from` are the parsed form (None when not a rename).
This dual representation lets the gate byte-compare raw_path while downstream
code uses the parsed form.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Iterator

SENTINEL = "@@@COMMENSA_COMMIT@@@"           # unlikely to appear in metadata
NUMSTAT_LINE = re.compile(r"^(-|\d+)\t(-|\d+)\t(.+)$")
# `a/{b => c}d` form: prefix-{old => new}-suffix  (git's "concise" rename)
RENAME_BRACE = re.compile(r"^(.*)\{(.*?) => (.*?)\}(.*)$")


class LocalCloneExtractor:
    """Extract commits from a local git clone.

    Yields commits in `git log` default order (reverse chronological).
    """

    def __init__(self, repo_dir):
        self.repo_dir = Path(repo_dir).resolve()
        # Validate it's a git repo (or worktree)
        try:
            subprocess.run(
                ["git", "-C", str(self.repo_dir), "rev-parse", "--git-dir"],
                capture_output=True, check=True, text=True,
            )
        except subprocess.CalledProcessError as e:
            raise ValueError(
                f"{str(self.repo_dir)!r} is not a git repo: {e.stderr.strip()}"
            )

    # -- public ----------------------------------------------------------

    def commits(self, *, no_merges: bool = False,
                since: str | None = None,
                until: str | None = None) -> Iterator[dict]:
        """Yield one dict per commit.

        Defaults match `git log` defaults so Gate D-A's byte comparison
        against `git log --numstat` holds exactly. since/until use git's
        --since/--until date syntax.
        """
        pretty = (f"{SENTINEL}%n"
                  f"%H%n%P%n"            # sha, parents (space-joined)
                  f"%aN%n%aE%n%aI%n"     # author name / email / strict ISO 8601
                  f"%cN%n%cE%n%cI%n"     # committer name / email / strict ISO
                  f"%s")                 # subject (single line by definition)
        cmd = ["git", "-C", str(self.repo_dir), "log",
               f"--pretty=format:{pretty}", "--numstat"]
        if no_merges:
            cmd.append("--no-merges")
        if since is not None:
            cmd.extend(["--since", since])
        if until is not None:
            cmd.extend(["--until", until])
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return self._parse(result.stdout)

    # -- parsing ---------------------------------------------------------

    def _parse(self, output: str) -> Iterator[dict]:
        # output: SENTINEL\n metadata-lines\n optional numstat\n SENTINEL\n ...
        chunks = output.split(SENTINEL + "\n")
        for chunk in chunks[1:]:        # first chunk is the empty prefix
            yield self._parse_chunk(chunk)

    def _parse_chunk(self, chunk: str) -> dict:
        lines = chunk.split("\n")
        # Required metadata layout (9 lines):
        sha = lines[0]
        parents = lines[1].split() if lines[1] else []
        author_name = lines[2]
        author_email = lines[3]
        author_date = lines[4]
        committer_name = lines[5]
        committer_email = lines[6]
        committer_date = lines[7]
        subject = lines[8]

        files: list[dict] = []
        # The 10th line is blank (separating subject from numstat); skip blanks.
        for line in lines[9:]:
            if not line:
                continue
            m = NUMSTAT_LINE.match(line)
            if not m:
                continue
            adds_s, dels_s, raw_path = m.groups()
            binary = (adds_s == "-" and dels_s == "-")
            path, rename_from = self._parse_rename(raw_path)
            files.append({
                "raw_path": raw_path,
                "path": path,
                "rename_from": rename_from,
                "additions": 0 if binary else int(adds_s),
                "deletions": 0 if binary else int(dels_s),
                "binary": binary,
            })

        return {
            "sha": sha,
            "parents": parents,
            "author_name": author_name,
            "author_email": author_email,
            "author_date": author_date,
            "committer_name": committer_name,
            "committer_email": committer_email,
            "committer_date": committer_date,
            "subject": subject,
            "files": files,
        }

    @staticmethod
    def _parse_rename(raw_path: str) -> tuple[str, str | None]:
        """Return (new_path, old_path | None) for git's numstat rename notations.

        Two forms emitted by `git log --numstat`:
          1) "prefix{old => new}suffix"  — git's concise/brace form
          2) "old => new"                — fallback when the brace form doesn't fit
        Non-renames return (raw_path, None) unchanged.
        """
        m = RENAME_BRACE.match(raw_path)
        if m:
            prefix, old, new, suffix = m.groups()
            # Note: git collapses double slashes when prefix/suffix abut empties
            new_path = (prefix + new + suffix).replace("//", "/")
            old_path = (prefix + old + suffix).replace("//", "/")
            return new_path, old_path
        if " => " in raw_path:
            old, new = raw_path.split(" => ", 1)
            return new, old
        return raw_path, None
