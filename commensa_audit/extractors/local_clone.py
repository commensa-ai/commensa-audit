"""Local-clone commit extractor — Phase D, commit mode.

Reads `.git` via subprocess git commands. NO network, NO host API. Yields one
unit per commit (vs one per PR in GitHubExtractor). Reuses the existing
engine (`patches.py` / `rework.py` / `classify.py`) via the same units.csv
schema plus per-file unified-diff `patch` text on the sidecar.

Guardrails (SPEC.md + COMMIT_MODE_SPEC.md):
  - read-only (only `git log`, no writes)
  - local-only, no network in this mode at all
  - stdlib + subprocess only (no requests, no jinja2 on the extractor side)
  - ALWAYS invoke git with `-c core.quotePath=false` and parse `-z`
    (NUL-delimited) so non-ASCII / tab / newline filenames round-trip exactly
    (D-A review finding: default quoting silently corrupts non-ASCII paths
    while the fidelity gate stays green)

Per-commit dict shape (what Gate D-A validates):
  sha, parents, author_name, author_email, author_date,
  committer_name, committer_email, committer_date, subject,
  files: [{raw_path, path, rename_from, additions, deletions, binary,
           patch (only when with_files=True)}]

`raw_path` reconstructs the canonical `git log --numstat` text shape (with
rename arrows) for downstream consumers that expect it. `path` and
`rename_from` are the parsed form; engine code uses those.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Iterator

from ..units import sanitize_title, looks_revert
from ..markers import detect_markers

SENTINEL = "@@@COMMENSA_COMMIT@@@"           # unlikely to appear in metadata
SENTINEL_BYTES = SENTINEL.encode("utf-8") + b"\n"
NUMSTAT_RE = re.compile(r"^(-|\d+)\t(-|\d+)\t(.*)$", re.DOTALL)
# `prefix{old => new}suffix` — git's concise rename (only matters when
# we *display* a raw_path; with -z we read renames structurally, not from text)
RENAME_BRACE = re.compile(r"^(.*)\{(.*?) => (.*?)\}(.*)$")


class LocalCloneExtractor:
    """Extract commits from a local git clone.

    Yields commits in `git log` default order (reverse chronological).
    """

    def __init__(self, repo_dir):
        self.repo_dir = Path(repo_dir).resolve()
        try:
            subprocess.run(
                self._git_args("rev-parse", "--git-dir"),
                capture_output=True, check=True,
            )
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or b"").decode("utf-8", errors="replace").strip()
            raise ValueError(
                f"{str(self.repo_dir)!r} is not a git repo: {stderr}"
            )

    # -- transport -------------------------------------------------------

    def _git_args(self, *extras) -> list[str]:
        """All git invocations route through here.

        `-c core.quotePath=false` (encoding hardening) is applied universally
        so the same option does not need to be set per call. Paths come
        through as UTF-8 instead of `"caf\\303\\251.txt"` C-quoted form.
        """
        return ["git", "-C", str(self.repo_dir),
                "-c", "core.quotePath=false", *extras]

    # -- public ----------------------------------------------------------

    def commits(self, *, no_merges: bool = False,
                since: str | None = None,
                until: str | None = None) -> Iterator[dict]:
        """Yield commits (metadata + files-from-numstat, no patch text).

        Single git invocation, `-z` NUL-delimited so non-ASCII / tab /
        newline filenames are preserved verbatim.
        """
        pretty = (f"{SENTINEL}%n"
                  f"%H%n%P%n"            # sha, parents (space-joined)
                  f"%aN%n%aE%n%aI%n"     # author name / email / strict ISO 8601
                  f"%cN%n%cE%n%cI%n"     # committer name / email / strict ISO
                  f"%s")                 # subject (single line by definition)
        cmd = self._git_args("log", "-z",
                             f"--pretty=format:{pretty}", "--numstat")
        if no_merges:
            cmd.append("--no-merges")
        if since is not None:
            cmd.extend(["--since", since])
        if until is not None:
            cmd.extend(["--until", until])
        result = subprocess.run(cmd, capture_output=True, check=True)
        yield from self._parse_log_z(result.stdout)

    def commits_with_patches(self, *, no_merges: bool = False,
                             since: str | None = None,
                             until: str | None = None) -> Iterator[dict]:
        """Same as commits() but each file dict also carries a `patch` key
        holding its unified-diff text. Two-pass: metadata+numstat is one
        invocation, patches another. The cost is amortized — both passes
        are single `git log` calls (not N+1).
        """
        all_commits = list(self.commits(no_merges=no_merges,
                                        since=since, until=until))
        patches_by_sha = self._collect_patches(
            no_merges=no_merges, since=since, until=until)
        for c in all_commits:
            file_patches = patches_by_sha.get(c["sha"], {})
            for f in c["files"]:
                # Patch keyed by the rename's destination (new path) when
                # renamed, otherwise by the file path itself.
                f["patch"] = (file_patches.get(f["path"])
                              or file_patches.get(f["rename_from"]))
            yield c

    def units(self, *, with_files: bool = False,
              no_merges: bool = False,
              since: str | None = None,
              until: str | None = None) -> Iterator[dict | tuple[dict, dict]]:
        """Yield (unit_row, sidecar_row) tuples — same shape as
        GitHubExtractor.units() so the engine wires in unchanged.

        unit_row: units.csv schema (locked) — unit_id is the short sha,
        title is sanitize_title(subject), created_at is author date,
        merged=1 (a commit IS landed by definition), counts come from
        numstat, looks_revert from subject.

        sidecar_row (with_files=True only): includes per-file patch text
        so rework.py's line-attribution replay works.
        """
        commit_iter = (self.commits_with_patches(no_merges=no_merges,
                                                 since=since, until=until)
                       if with_files else
                       self.commits(no_merges=no_merges,
                                    since=since, until=until))
        # Agent markers (Co-Authored-By trailers) live in the commit BODY,
        # not the subject. Pull full messages once and scan them in-memory;
        # only the marker RESULT is persisted (bodies stay off disk).
        messages_by_sha = (self._collect_messages(no_merges=no_merges,
                                                  since=since, until=until)
                           if with_files else {})
        for c in commit_iter:
            uid = "SHA-" + c["sha"][:12]
            unit = {
                "unit_id": uid,
                "title": sanitize_title(c["subject"]),
                "created_at": c["author_date"],
                "merged": 1,
                "lines_added": sum(f["additions"] for f in c["files"]
                                   if not f["binary"]),
                "lines_deleted": sum(f["deletions"] for f in c["files"]
                                     if not f["binary"]),
                "changed_files": len(c["files"]),
                "looks_revert": looks_revert(c["subject"]),
            }
            if not with_files:
                yield unit
                continue
            # Sidecar matches the GitHub sidecar's shape so the existing
            # engine consumes it without modification.
            sidecar = {
                "unit_id": uid,
                "number": c["sha"][:12],          # short sha stands in for PR number
                "raw_title": c["subject"],
                "created_at": c["author_date"],
                "merged_at": c["committer_date"],
                "merged": True,
                "state": "closed",                # commits are landed
                "closed_at": c["committer_date"],
                # marker strings only — bodies/messages stay off disk.
                # Scan the FULL message (subject + body) so Co-Authored-By
                # trailers in the body are seen (theo: ~88% Claude-marked,
                # all in the body — subject-only scan reported 0). M-A:
                # also pass author/committer identity (catches bot accounts
                # like cursor-bot, copilot[bot]), with platform exclusion
                # protecting GitHub web-UI commits from being flagged.
                **_marker_fields(detect_markers(
                    messages_by_sha.get(c["sha"], c["subject"]),
                    [messages_by_sha.get(c["sha"], c["subject"])],
                    author_identity=f'{c["author_name"]} <{c["author_email"]}>',
                    committer_identity=f'{c["committer_name"]} <{c["committer_email"]}>')),
                "files": [{
                    "filename": f["path"],
                    "status": ("renamed" if f["rename_from"]
                               else ("added" if f["additions"] and not f["deletions"]
                                     else "modified")),
                    "previous_filename": f["rename_from"],
                    "additions": f["additions"],
                    "deletions": f["deletions"],
                    "patch": f.get("patch"),
                } for f in c["files"]],
            }
            yield unit, sidecar

    # -- pass 1: metadata + numstat (-z parser) --------------------------

    def _parse_log_z(self, output_bytes: bytes) -> Iterator[dict]:
        for chunk in output_bytes.split(SENTINEL_BYTES)[1:]:
            yield self._parse_chunk_z(chunk)

    def _parse_chunk_z(self, chunk_bytes: bytes) -> dict:
        """Parse one commit chunk produced by `git log -z ... --numstat`.

        Byte layout (verified empirically against real git output):
          <sha>\\n<parents>\\n<aN>\\n<aE>\\n<aI>\\n<cN>\\n<cE>\\n<cI>\\n<subject>\\n
          <numstat NUL-records>\\0
        Where each numstat record is one of:
          regular: <adds>\\t<dels>\\t<path>\\0
          rename : <adds>\\t<dels>\\t\\0<src>\\0<dst>\\0
        """
        # Split off the 9 metadata lines and keep the rest as a byte tail
        head, _, tail = chunk_bytes.partition(b"\n")  # sha
        sha = head.decode("utf-8")
        head, _, tail = tail.partition(b"\n")  # parents
        parents = head.decode("utf-8").split() if head else []
        author_name, tail   = _eat_line(tail)
        author_email, tail  = _eat_line(tail)
        author_date, tail   = _eat_line(tail)
        committer_name, tail   = _eat_line(tail)
        committer_email, tail  = _eat_line(tail)
        committer_date, tail   = _eat_line(tail)
        # Subject — git inserts a trailing \n before the numstat block, so
        # split on the FIRST newline; tail now holds the NUL-record stream.
        # MERGE/empty commits have NO numstat, so under -z the subject is
        # terminated by the commit-boundary NUL, not a newline — cut the
        # subject at the first NUL so it never leaks into the title (theo
        # 41-merge repo surfaced this; see BUILD_LOG D-B hotfix).
        subject_bytes, _, tail = tail.partition(b"\n")
        subject = subject_bytes.split(b"\x00", 1)[0].decode("utf-8")

        # Numstat records are NUL-terminated. The trailing commit boundary
        # adds one extra NUL (so we filter empties).
        raw_records = [r for r in tail.split(b"\x00") if r]
        files: list[dict] = []
        i = 0
        while i < len(raw_records):
            rec = raw_records[i].decode("utf-8")
            m = NUMSTAT_RE.match(rec)
            if not m:
                i += 1
                continue
            adds_s, dels_s, path = m.groups()
            binary = (adds_s == "-" and dels_s == "-")
            if path == "" and i + 2 < len(raw_records) + 1 and i + 1 < len(raw_records):
                # Rename in -z form: empty path field + two follow-on entries
                old_path = raw_records[i + 1].decode("utf-8")
                new_path = raw_records[i + 2].decode("utf-8") if i + 2 < len(raw_records) else ""
                files.append({
                    "raw_path": f"{old_path} => {new_path}",  # canonical form
                    "path": new_path,
                    "rename_from": old_path,
                    "additions": 0 if binary else int(adds_s),
                    "deletions": 0 if binary else int(dels_s),
                    "binary": binary,
                })
                i += 3
            else:
                files.append({
                    "raw_path": path,
                    "path": path,
                    "rename_from": None,
                    "additions": 0 if binary else int(adds_s),
                    "deletions": 0 if binary else int(dels_s),
                    "binary": binary,
                })
                i += 1

        return {
            "sha": sha, "parents": parents,
            "author_name": author_name, "author_email": author_email,
            "author_date": author_date,
            "committer_name": committer_name, "committer_email": committer_email,
            "committer_date": committer_date,
            "subject": subject, "files": files,
        }

    # -- pass 2: per-file unified-diff patches ---------------------------

    PATCH_SENTINEL = "@@@COMMENSA_PATCH@@@"
    DIFF_HEADER_RE = re.compile(rb"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)

    def _collect_patches(self, *, no_merges: bool, since: str | None,
                         until: str | None) -> dict[str, dict[str, str]]:
        """Single git log pass collecting all unified-diff patches.

        Returns {sha: {file_path: patch_text}}. Patches are split on the
        canonical `diff --git a/X b/Y` headers — that boundary is
        unambiguous, so this pass doesn't need -z."""
        pretty = f"{self.PATCH_SENTINEL}%n%H"
        cmd = self._git_args("log",
                             f"--pretty=format:{pretty}",
                             "-p", "--no-color")
        if no_merges:
            cmd.append("--no-merges")
        if since is not None:
            cmd.extend(["--since", since])
        if until is not None:
            cmd.extend(["--until", until])
        result = subprocess.run(cmd, capture_output=True, check=True)
        out = result.stdout  # bytes — patch text can include any bytes
        # Split into per-commit chunks. Each starts with sha\n then the
        # concatenated unified diffs for every file in that commit.
        out_lines = out.split(self.PATCH_SENTINEL.encode("utf-8") + b"\n")
        patches: dict[str, dict[str, str]] = {}
        for chunk in out_lines[1:]:
            sha_bytes, _, body = chunk.partition(b"\n")
            sha = sha_bytes.decode("utf-8")
            patches[sha] = self._split_patches_by_file(body)
        return patches

    def _split_patches_by_file(self, body: bytes) -> dict[str, str]:
        """Split a multi-file unified-diff body keyed by destination path."""
        out: dict[str, str] = {}
        # Find every `diff --git a/X b/Y` header position
        headers = list(self.DIFF_HEADER_RE.finditer(body))
        for i, m in enumerate(headers):
            new_path = m.group(2).decode("utf-8", errors="replace")
            start = m.start()
            end = headers[i + 1].start() if i + 1 < len(headers) else len(body)
            patch_text = body[start:end].decode("utf-8", errors="replace")
            out[new_path] = patch_text
        return out

    # -- pass 3: full commit messages (markers live in the BODY) ---------

    MSG_SENTINEL = "@@@COMMENSA_MSG@@@"

    def _collect_messages(self, *, no_merges: bool, since: str | None,
                          until: str | None) -> dict[str, str]:
        """Single git log pass returning {sha: full_message}.

        Full message = subject + body, because Co-Authored-By trailers (the
        canonical agent marker) live in the body. Scanned in-memory only;
        never persisted — only the marker RESULT is stored, preserving the
        bodies-off-disk privacy stance."""
        pretty = f"{self.MSG_SENTINEL}%n%H%n%B"
        cmd = self._git_args("log", f"--pretty=format:{pretty}")
        if no_merges:
            cmd.append("--no-merges")
        if since is not None:
            cmd.extend(["--since", since])
        if until is not None:
            cmd.extend(["--until", until])
        out = subprocess.run(cmd, capture_output=True, check=True).stdout
        text = out.decode("utf-8", errors="replace")
        messages: dict[str, str] = {}
        for chunk in text.split(self.MSG_SENTINEL + "\n")[1:]:
            sha, _, body = chunk.partition("\n")
            messages[sha.strip()] = body.rstrip("\n")
        return messages

    # -- utility ---------------------------------------------------------

    @staticmethod
    def _parse_rename(raw_path: str) -> tuple[str, str | None]:
        """Parse git's rename notation into (new_path, old_path).

        Kept for downstream tests that exercise the brace form even though
        the -z parser now sees renames structurally. Two forms:
          1) `prefix{old => new}suffix` — git's concise/brace form
          2) `old => new`                — fallback when the brace form doesn't fit
        Non-renames return (raw_path, None) unchanged.
        """
        m = RENAME_BRACE.match(raw_path)
        if m:
            prefix, old, new, suffix = m.groups()
            new_path = (prefix + new + suffix).replace("//", "/")
            old_path = (prefix + old + suffix).replace("//", "/")
            return new_path, old_path
        if " => " in raw_path:
            old, new = raw_path.split(" => ", 1)
            return new, old
        return raw_path, None


def _eat_line(tail: bytes) -> tuple[str, bytes]:
    """Consume up to the next \\n; return (decoded line, remaining bytes)."""
    head, _, rest = tail.partition(b"\n")
    return head.decode("utf-8"), rest


def _marker_fields(result: dict) -> dict:
    """Unpack ``{markers, model}`` from detect_markers into the sidecar's
    ``ai_markers`` (backward-compatible list of strings) + ``ai_model``
    (structured family/tier/version dict, new in M-A)."""
    return {"ai_markers": result["markers"], "ai_model": result["model"]}
