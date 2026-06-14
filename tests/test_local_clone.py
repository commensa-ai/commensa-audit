"""Phase D extractor unit tests — covers the edge cases not present in
the commensa-audit repo's own history (renames, binaries, merges, empty repo)."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from commensa_audit.extractors.local_clone import LocalCloneExtractor


def _git(repo, *args, **kwargs):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True,
                          **kwargs).stdout


def _make_repo():
    d = tempfile.mkdtemp(prefix="commensa_d_")
    p = Path(d)
    _git(p, "init", "-q", "-b", "main")
    _git(p, "config", "user.name", "Test User")
    _git(p, "config", "user.email", "test@example.com")
    _git(p, "config", "commit.gpgsign", "false")
    return p


def _commit(repo, message, add_files=None, rm_files=None):
    for path, content in (add_files or {}).items():
        full = repo / path
        full.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            full.write_bytes(content)
        else:
            full.write_text(content)
        _git(repo, "add", path)
    for path in (rm_files or []):
        _git(repo, "rm", path)
    _git(repo, "commit", "-q", "-m", message)


class TestSimpleHistory(unittest.TestCase):
    def test_commit_order_is_reverse_chronological(self):
        repo = _make_repo()
        _commit(repo, "first",  {"a.txt": "one\n"})
        _commit(repo, "second", {"a.txt": "one\ntwo\n"})
        _commit(repo, "third",  {"a.txt": "one\ntwo\nthree\n"})
        cs = list(LocalCloneExtractor(repo).commits())
        self.assertEqual([c["subject"] for c in cs], ["third", "second", "first"])

    def test_addition_and_deletion_counts(self):
        repo = _make_repo()
        _commit(repo, "add",    {"f.txt": "1\n2\n3\n"})
        _commit(repo, "modify", {"f.txt": "1\n2\nNEW\n4\n"})  # +2, -1
        cs = list(LocalCloneExtractor(repo).commits())
        latest = cs[0]
        self.assertEqual(latest["files"][0]["additions"], 2)
        self.assertEqual(latest["files"][0]["deletions"], 1)
        self.assertEqual(latest["files"][0]["path"], "f.txt")
        self.assertFalse(latest["files"][0]["binary"])
        self.assertIsNone(latest["files"][0]["rename_from"])

    def test_metadata_fields_present(self):
        repo = _make_repo()
        _commit(repo, "only", {"x": "y\n"})
        c = list(LocalCloneExtractor(repo).commits())[0]
        self.assertEqual(c["author_name"], "Test User")
        self.assertEqual(c["author_email"], "test@example.com")
        self.assertEqual(c["committer_name"], "Test User")
        self.assertEqual(c["committer_email"], "test@example.com")
        self.assertTrue(c["sha"])
        self.assertEqual(len(c["sha"]), 40)
        # initial commit has no parents
        self.assertEqual(c["parents"], [])

    def test_parents_list_populated(self):
        repo = _make_repo()
        _commit(repo, "a", {"f.txt": "1\n"})
        _commit(repo, "b", {"f.txt": "1\n2\n"})
        cs = list(LocalCloneExtractor(repo).commits())
        # newest first
        self.assertEqual(len(cs[0]["parents"]), 1)   # b has 1 parent
        self.assertEqual(len(cs[1]["parents"]), 0)   # a is initial


class TestBinary(unittest.TestCase):
    def test_binary_file_is_flagged(self):
        repo = _make_repo()
        # .gitattributes can't lie about binaries; use real bytes
        _commit(repo, "binary", {"img.bin": b"\x00\x01\xff\xfe" * 200})
        c = list(LocalCloneExtractor(repo).commits())[0]
        f = c["files"][0]
        self.assertTrue(f["binary"])
        self.assertEqual(f["additions"], 0)
        self.assertEqual(f["deletions"], 0)
        self.assertEqual(f["path"], "img.bin")


class TestRename(unittest.TestCase):
    def test_simple_rename_via_git_mv(self):
        repo = _make_repo()
        _commit(repo, "add foo", {"foo.txt": "x\n"})
        _git(repo, "mv", "foo.txt", "bar.txt")
        _git(repo, "commit", "-q", "-m", "rename foo to bar")
        cs = list(LocalCloneExtractor(repo).commits())
        rename_commit = cs[0]
        # git log --numstat shows a SINGLE entry for the rename
        self.assertEqual(len(rename_commit["files"]), 1)
        f = rename_commit["files"][0]
        self.assertEqual(f["rename_from"], "foo.txt")
        self.assertEqual(f["path"], "bar.txt")
        # raw_path is what git emitted (rename arrow form intact)
        self.assertIn("=>", f["raw_path"])

    def test_rename_parser_brace_form(self):
        path, fro = LocalCloneExtractor._parse_rename("src/{old => new}.py")
        self.assertEqual(path, "src/new.py")
        self.assertEqual(fro, "src/old.py")

    def test_rename_parser_simple_form(self):
        path, fro = LocalCloneExtractor._parse_rename("old.txt => new.txt")
        self.assertEqual(path, "new.txt")
        self.assertEqual(fro, "old.txt")

    def test_rename_parser_no_rename(self):
        path, fro = LocalCloneExtractor._parse_rename("normal/path.py")
        self.assertEqual(path, "normal/path.py")
        self.assertIsNone(fro)


class TestMerges(unittest.TestCase):
    def test_no_merges_flag_filters_merge_commits(self):
        repo = _make_repo()
        _commit(repo, "base", {"a.txt": "0\n"})
        _git(repo, "checkout", "-q", "-b", "feature")
        _commit(repo, "feature work", {"b.txt": "1\n"})
        _git(repo, "checkout", "-q", "main")
        _commit(repo, "main work",    {"c.txt": "2\n"})
        _git(repo, "merge", "-q", "--no-ff", "-m", "merge feature", "feature")
        all_c   = list(LocalCloneExtractor(repo).commits())
        no_merg = list(LocalCloneExtractor(repo).commits(no_merges=True))
        # all: base, feature_work, main_work, merge = 4
        # no-merges: 3
        self.assertEqual(len(all_c), 4)
        self.assertEqual(len(no_merg), 3)
        # merge commit (newest in all_c) has 2 parents
        self.assertEqual(len(all_c[0]["parents"]), 2)


class TestBadInputs(unittest.TestCase):
    def test_non_repo_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                LocalCloneExtractor(d)

    def test_nonexistent_path_raises(self):
        with self.assertRaises((ValueError, FileNotFoundError)):
            LocalCloneExtractor("/nope/does/not/exist")


class TestEncodingHardening(unittest.TestCase):
    """D-A review finding: default git quoting silently corrupts non-ASCII
    paths while --numstat fidelity stays green. -c core.quotePath=false + -z
    round-trips them exactly. These tests pin that behavior."""

    def test_non_ascii_filename_round_trips_verbatim(self):
        repo = _make_repo()
        path = "café/résumé.txt"
        _commit(repo, "non-ASCII path", {path: "x\n"})
        c = list(LocalCloneExtractor(repo).commits())[0]
        self.assertEqual(len(c["files"]), 1)
        self.assertEqual(c["files"][0]["path"], path)
        self.assertEqual(c["files"][0]["raw_path"], path)
        self.assertFalse(c["files"][0]["binary"])
        # Defensive: ensure no C-quoting leaked through (would look like \303\251)
        self.assertNotIn("\\", c["files"][0]["path"])

    def test_emoji_filename_round_trips(self):
        repo = _make_repo()
        path = "fire-🔥/notes.txt"
        _commit(repo, "emoji path", {path: "burn\n"})
        c = list(LocalCloneExtractor(repo).commits())[0]
        self.assertEqual(c["files"][0]["path"], path)

    def test_filename_with_spaces_and_punctuation(self):
        repo = _make_repo()
        path = "docs (draft) v2/notes & ideas.md"
        _commit(repo, "punctuation path", {path: "x\n"})
        c = list(LocalCloneExtractor(repo).commits())[0]
        self.assertEqual(c["files"][0]["path"], path)


class TestEnginePatchIntegration(unittest.TestCase):
    """Phase D-B: per-file unified-diff `patch` text must round-trip into
    sidecar entries so patches.parse_patch / rework.py work unchanged."""

    def test_patch_text_attached_when_with_files(self):
        from commensa_audit.patches import parse_patch
        repo = _make_repo()
        _commit(repo, "add",    {"f.txt": "1\n2\n3\n"})
        _commit(repo, "modify", {"f.txt": "1\n2\nNEW\n4\n"})
        cs = list(LocalCloneExtractor(repo).commits_with_patches())
        latest = cs[0]
        f = latest["files"][0]
        self.assertIn("patch", f)
        self.assertIsNotNone(f["patch"])
        self.assertIn("diff --git", f["patch"])
        # parse_patch must read it as a standard unified diff
        events = list(parse_patch(f["patch"]))
        kinds = [k for k, _ in events]
        self.assertIn("+", kinds)
        self.assertIn("-", kinds)

    def test_units_emission_matches_csv_schema(self):
        """units() yields rows that conform to units.py's locked schema."""
        from commensa_audit.units import UNIT_FIELDS
        repo = _make_repo()
        _commit(repo, "feat: add core", {"core.py": "x = 1\n"})
        _commit(repo, "fix: typo in core", {"core.py": "y = 1\n"})
        units = list(LocalCloneExtractor(repo).units())
        self.assertEqual(len(units), 2)
        for u in units:
            self.assertEqual(sorted(u.keys()), sorted(UNIT_FIELDS))
            self.assertEqual(u["merged"], 1)         # commits are landed
            self.assertTrue(u["unit_id"].startswith("SHA-"))

    def test_units_with_files_emits_sidecar(self):
        """units(with_files=True) returns (unit, sidecar) tuples; sidecar
        carries the file list with patch text."""
        repo = _make_repo()
        _commit(repo, "init",  {"a.py": "x = 1\n"})
        _commit(repo, "tweak", {"a.py": "x = 2\n"})
        out = list(LocalCloneExtractor(repo).units(with_files=True))
        self.assertEqual(len(out), 2)
        unit, sidecar = out[0]
        self.assertEqual(unit["unit_id"], sidecar["unit_id"])
        self.assertTrue(sidecar["merged"])
        self.assertEqual(len(sidecar["files"]), 1)
        self.assertEqual(sidecar["files"][0]["filename"], "a.py")
        self.assertIn("@@", sidecar["files"][0]["patch"])  # unified-diff hunk marker

    def test_looks_revert_carried_into_unit(self):
        """A commit whose subject begins with Revert ... must read looks_revert=1
        on the unit row (matches Phase A's gate semantics for PR titles)."""
        repo = _make_repo()
        _commit(repo, "Revert \"feat: broken\"", {"x.py": "z = 0\n"})
        u = next(LocalCloneExtractor(repo).units())
        self.assertEqual(u["looks_revert"], 1)


if __name__ == "__main__":
    unittest.main()
