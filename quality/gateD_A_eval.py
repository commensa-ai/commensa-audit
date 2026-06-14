"""Gate D-A — local-clone extractor fidelity.

Spec (COMMIT_MODE_SPEC.md): the extractor's per-commit facts (sha, author,
date, files, +/- lines) must match `git log --numstat` exactly on a known repo.

D-B refresh (2026-06-13): the spec's encoding hardening step requires
`-c core.quotePath=false` and parsing `-z`. The gate's truth-source git
command therefore uses those same flags; the integrity of the comparison
comes from the truth-source parser being an INDEPENDENT implementation of
the extractor parser (different code paths, both consuming the same raw
git bytes). 0 divergence = exact match.

Exit 0 = gate passed. Exit 1 = any divergence; prints the first 10
mismatches with field-level diffs.

Default target: commensa-audit itself (this repo).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from commensa_audit.extractors.local_clone import LocalCloneExtractor

NUMSTAT_RE = re.compile(r"^(-|\d+)\t(-|\d+)\t(.*)$", re.DOTALL)
SENTINEL = "@@@GATE_TRUTH@@@"
SENTINEL_BYTES = SENTINEL.encode("utf-8") + b"\n"


def truth_from_git(repo: Path, *, no_merges: bool = False) -> list[dict]:
    """Independent parse of `git log -z -c core.quotePath=false --numstat`.

    Deliberately distinct from LocalCloneExtractor's parser — this is the
    "ground truth" arm of the gate. Both arms see the same raw git bytes;
    a mismatch can only come from a parser bug on either side.
    """
    pretty = (f"{SENTINEL}%n"
              f"%H%n%P%n"
              f"%aN%n%aE%n%aI%n"
              f"%cN%n%cE%n%cI%n"
              f"%s")
    cmd = ["git", "-C", str(repo),
           "-c", "core.quotePath=false",
           "log", "-z",
           f"--pretty=format:{pretty}", "--numstat"]
    if no_merges:
        cmd.append("--no-merges")
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout

    commits: list[dict] = []
    for chunk in raw.split(SENTINEL_BYTES)[1:]:
        # Independent parser: walk byte-by-byte, NOT calling extractor methods.
        meta_lines: list[str] = []
        tail = chunk
        for _ in range(9):
            head, sep, tail = tail.partition(b"\n")
            meta_lines.append(head.decode("utf-8"))
        sha, parents_line, aN, aE, aI, cN, cE, cI, subject = meta_lines
        parents = parents_line.split() if parents_line else []

        # NUL-delimited numstat records; drop trailing empties
        records = [r for r in tail.split(b"\x00") if r]
        files: list[dict] = []
        i = 0
        while i < len(records):
            rec = records[i].decode("utf-8")
            m = NUMSTAT_RE.match(rec)
            if not m:
                i += 1
                continue
            adds, dels, path = m.groups()
            if path == "" and i + 2 <= len(records) - 1:
                old = records[i + 1].decode("utf-8")
                new = records[i + 2].decode("utf-8")
                files.append({"adds": adds, "dels": dels,
                              "raw_path": f"{old} => {new}"})
                i += 3
            else:
                files.append({"adds": adds, "dels": dels, "raw_path": path})
                i += 1

        commits.append({
            "sha": sha, "parents": parents,
            "author_name": aN, "author_email": aE, "author_date": aI,
            "committer_name": cN, "committer_email": cE, "committer_date": cI,
            "subject": subject, "files": files,
        })
    return commits


def extractor_to_truth_form(c: dict) -> dict:
    files = []
    for f in c["files"]:
        if f["binary"]:
            adds, dels = "-", "-"
        else:
            adds, dels = str(f["additions"]), str(f["deletions"])
        files.append({"adds": adds, "dels": dels, "raw_path": f["raw_path"]})
    return {
        "sha": c["sha"], "parents": c["parents"],
        "author_name": c["author_name"], "author_email": c["author_email"],
        "author_date": c["author_date"],
        "committer_name": c["committer_name"], "committer_email": c["committer_email"],
        "committer_date": c["committer_date"],
        "subject": c["subject"],
        "files": files,
    }


def diff_one(truth: dict, extracted: dict) -> list[tuple]:
    diffs = []
    for k in ("sha", "parents", "author_name", "author_email", "author_date",
              "committer_name", "committer_email", "committer_date", "subject"):
        if truth[k] != extracted[k]:
            diffs.append((k, truth[k], extracted[k]))
    if len(truth["files"]) != len(extracted["files"]):
        diffs.append(("files_count", len(truth["files"]), len(extracted["files"])))
    else:
        for i, (tf, ef) in enumerate(zip(truth["files"], extracted["files"])):
            for fk in ("adds", "dels", "raw_path"):
                if tf[fk] != ef[fk]:
                    diffs.append((f"files[{i}].{fk}", tf[fk], ef[fk]))
    return diffs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(Path(__file__).parent.parent),
                    help="path to git repo (default: this repo)")
    ap.add_argument("--no-merges", action="store_true",
                    help="filter merge commits on BOTH sides")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    print(f"Gate D-A — local-clone extractor fidelity")
    print(f"repo        : {repo}")
    print(f"no_merges   : {args.no_merges}")
    print(f"flags       : -c core.quotePath=false -z (independent parsers)")

    truth = truth_from_git(repo, no_merges=args.no_merges)
    extracted = [extractor_to_truth_form(c)
                 for c in LocalCloneExtractor(repo).commits(no_merges=args.no_merges)]
    print(f"truth count : {len(truth)}")
    print(f"extracted   : {len(extracted)}")

    if len(truth) != len(extracted):
        print(f"\nGATE D-A: FAIL — commit count mismatch")
        return 1

    matched = 0
    diff_records = []
    for i, (t, e) in enumerate(zip(truth, extracted)):
        d = diff_one(t, e)
        if d:
            diff_records.append((i, t["sha"][:12], d))
        else:
            matched += 1
    print(f"matched     : {matched} / {len(truth)}")
    print(f"divergent   : {len(diff_records)}")

    if diff_records:
        print("\nFirst few divergences:")
        for i, sha, d in diff_records[:10]:
            print(f"  commit[{i}] {sha}")
            for field, t_val, e_val in d:
                print(f"    {field}: truth={t_val!r}  extracted={e_val!r}")
        print(f"\nGATE D-A: FAIL — {len(diff_records)}/{len(truth)} commits differ")
        return 1

    print(f"\nGATE D-A: PASS — {matched}/{len(truth)} commits match `git log --numstat` "
          f"exactly (under -z + quotePath=false)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
