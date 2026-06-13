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


if __name__ == "__main__":
    unittest.main()
