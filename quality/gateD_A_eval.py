"""Gate D-A — local-clone extractor fidelity.

Spec (COMMIT_MODE_SPEC.md): the extractor's per-commit facts (sha, author,
date, files, +/- lines) must match `git log --numstat` exactly on a known repo.

This script:
  1. Runs `git log --numstat` independently (the truth source).
  2. Runs LocalCloneExtractor on the same repo.
  3. Structural deep-compare every field on every commit.

Exit 0 = gate passed (zero divergence). Exit 1 = any divergence; prints
the first 10 mismatches with field-level diffs.

Default target: commensa-audit itself (this repo).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Make commensa_audit importable when invoked directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from commensa_audit.extractors.local_clone import LocalCloneExtractor

NUMSTAT_LINE = re.compile(r"^(-|\d+)\t(-|\d+)\t(.+)$")
SENTINEL = "@@@GATE_TRUTH@@@"


def truth_from_git(repo: Path, *, no_merges: bool = False) -> list[dict]:
    """Run `git log --numstat` independently and produce comparison dicts."""
    pretty = (f"{SENTINEL}%n"
              f"%H%n%P%n"
              f"%aN%n%aE%n%aI%n"
              f"%cN%n%cE%n%cI%n"
              f"%s")
    cmd = ["git", "-C", str(repo), "log",
           f"--pretty=format:{pretty}", "--numstat"]
    if no_merges:
        cmd.append("--no-merges")
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout

    commits = []
    for chunk in out.split(SENTINEL + "\n")[1:]:
        lines = chunk.split("\n")
        sha = lines[0]
        parents = lines[1].split() if lines[1] else []
        meta = {
            "sha": sha, "parents": parents,
            "author_name": lines[2], "author_email": lines[3],
            "author_date": lines[4],
            "committer_name": lines[5], "committer_email": lines[6],
            "committer_date": lines[7],
            "subject": lines[8],
            "files": [],
        }
        for line in lines[9:]:
            if not line:
                continue
            m = NUMSTAT_LINE.match(line)
            if not m:
                continue
            adds, dels, raw_path = m.groups()
            meta["files"].append({"adds": adds, "dels": dels, "raw_path": raw_path})
        commits.append(meta)
    return commits


def extractor_to_truth_form(c: dict) -> dict:
    """Project the extractor dict into the truth-shape for byte comparison."""
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
    """Return list of (field_path, truth_value, extracted_value) tuples."""
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

    print(f"\nGATE D-A: PASS — {matched}/{len(truth)} commits match `git log --numstat` exactly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
