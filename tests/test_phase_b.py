"""Phase B unit tests — stdlib unittest, run with:  python3 -m unittest discover tests"""

import unittest

from commensa_audit.classify import CONFIG, TITLE_RE, classify
from commensa_audit.patches import parse_patch
from commensa_audit.rework import churn_clusters, replay, supersessions
from commensa_audit.units import looks_revert


def _pr(uid, merged_at, files, title="t"):
    return dict(unit_id=uid, raw_title=title, merged=True,
                merged_at=merged_at, files=files)


def _patch(added=(), deleted=()):
    body = "@@ -1,9 +1,9 @@\n"
    body += "\n".join(f"-{l}" for l in deleted)
    if deleted and added:
        body += "\n"
    body += "\n".join(f"+{l}" for l in added)
    return body


class TestLooksRevert(unittest.TestCase):
    def test_red_team_false_positive_fixed(self):
        self.assertEqual(looks_revert("non-reverting change"), 0)  # gateA_redteam.md finding

    def test_github_revert_convention(self):
        self.assertEqual(looks_revert('Revert "feat: add dark mode"'), 1)

    def test_gate_a_row_still_matches(self):
        self.assertEqual(looks_revert("Revert to neutral palette site-wide; remap"), 1)

    def test_plain_words(self):
        self.assertEqual(looks_revert("add revert button to editor"), 1)
        self.assertEqual(looks_revert("introvert mode"), 0)


class TestTitleRegex(unittest.TestCase):
    CORRECTIVE = [
        "fix: kiosk validator allows Bar Code",
        "fix(devices): admin gate case-insensitive on role",
        "Fix light/dark mixing + padding",
        "ops: PillStack — correct order (sales top ops bottom)",
        "hotfix for prod crash",
        "Patched the CSV writer",
        "Undoing the palette change",
        "redo the navigation drawer",
        "repair broken symlink in build",
    ]
    GENERATIVE = [
        "non-reverting change",                      # red-team case
        "feat(devices): catalog as picklist source",
        "docs(S-06): close-out paperwork",
        "add fixtures for the test suite",           # 'fixtures' must not match 'fix'
        "dispatch listener for the bus",             # 'dispatch' must not match 'patch'
        "prefix-fixup naming pass",                  # hyphen-joined
        "Correctness-preserving refactor",           # 'correctness' joined by hyphen? no — single word
    ]

    def test_corrective_titles_match(self):
        for t in self.CORRECTIVE:
            self.assertTrue(TITLE_RE.search(t), t)

    def test_generative_titles_do_not_match(self):
        for t in self.GENERATIVE:
            self.assertFalse(TITLE_RE.search(t), t)


class TestParsePatch(unittest.TestCase):
    def test_roundtrip(self):
        patch = "@@ -1,3 +1,3 @@\n context\n-old line\n+new line\n\\ No newline at end of file"
        self.assertEqual(list(parse_patch(patch)), [("-", "old line"), ("+", "new line")])

    def test_none_patch(self):
        self.assertEqual(list(parse_patch(None)), [])


class TestReplay(unittest.TestCase):
    def setUp(self):
        # PR-A adds 4 lines; PR-B (2 days later) deletes 2 of them and adds its own.
        self.prs = [
            _pr("PR-A", "2026-01-01T00:00:00Z",
                [dict(filename="app.py", status="added", additions=4, deletions=0,
                      patch=_patch(added=["alpha = 1", "beta = 2", "gamma = 3", "delta = 4"]))]),
            _pr("PR-B", "2026-01-03T00:00:00Z",
                [dict(filename="app.py", status="modified", additions=2, deletions=2,
                      patch=_patch(added=["beta = 22", "epsilon = 5"],
                                   deleted=["beta = 2", "gamma = 3"]))]),
        ]
        self.res = replay(self.prs)

    def test_rework_edge(self):
        self.assertEqual(self.res.edges[("PR-A", "PR-B")], 2)
        self.assertEqual(self.res.reworked_recent("PR-B", 14), 2)
        self.assertEqual(self.res.reworked_recent("PR-B", 1), 0)  # outside a 1-day window

    def test_survival(self):
        self.assertEqual(self.res.surviving["PR-A"], 2)  # alpha, delta remain
        self.assertEqual(self.res.surviving["PR-B"], 2)  # beta=22, epsilon

    def test_trivial_lines_skipped(self):
        prs = [_pr("PR-T", "2026-01-01T00:00:00Z",
                   [dict(filename="x.py", status="added", additions=3, deletions=0,
                         patch=_patch(added=["", "}", "real_line = 1"]))])]
        res = replay(prs)
        self.assertEqual(res.added["PR-T"], 1)

    def test_rename_followed(self):
        prs = self.prs + [
            _pr("PR-C", "2026-01-04T00:00:00Z",
                [dict(filename="core.py", status="renamed", previous_filename="app.py",
                      additions=0, deletions=1, patch=_patch(deleted=["alpha = 1"]))]),
        ]
        res = replay(prs)
        self.assertEqual(res.edges[("PR-A", "PR-C")], 1)
        self.assertEqual(res.surviving["PR-A"], 1)  # only delta survives

    def test_unmerged_prs_excluded(self):
        prs = self.prs + [dict(unit_id="PR-X", merged=False, merged_at=None,
                               files=self.prs[0]["files"])]
        res = replay(prs)
        self.assertNotIn("PR-X", res.added)


class TestClustersAndSupersession(unittest.TestCase):
    def _saga(self):
        """Three same-file PRs rewriting each other = churn. Three docs PRs
        sharing a bookkeeping file but appending = cadence, not churn."""
        lines1 = [f"color_{i} = old" for i in range(30)]
        lines2 = [f"color_{i} = new" for i in range(30)]
        lines3 = [f"color_{i} = newer" for i in range(30)]
        prs = [
            _pr("PR-1", "2026-01-01T00:00:00Z",
                [dict(filename="theme.css", status="added", patch=_patch(added=lines1))]),
            _pr("PR-2", "2026-01-02T00:00:00Z",
                [dict(filename="theme.css", status="modified",
                      patch=_patch(added=lines2, deleted=lines1))]),
            _pr("PR-3", "2026-01-03T00:00:00Z",
                [dict(filename="theme.css", status="modified",
                      patch=_patch(added=lines3, deleted=lines2))]),
        ]
        for i, day in enumerate(("05", "06", "07")):
            prs.append(_pr(f"DOC-{i + 1}", f"2026-01-{day}T00:00:00Z",
                           [dict(filename="PICKUP.md", status="modified",
                                 patch=_patch(added=[f"session note {i + 1} entry"]))]))
        return prs

    def test_churn_cluster_found_cadence_excluded(self):
        res = replay(self._saga())
        clusters = churn_clusters(res, window_days=14, min_size=3,
                                  min_edge_lines=10, edge_min_frac=0.25)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["members"], ["PR-1", "PR-2", "PR-3"])

    def test_supersession(self):
        res = replay(self._saga())
        sup = supersessions(res, window_days=14, min_frac=0.5, min_lines=10)
        self.assertIn("PR-1", sup)   # fully replaced by PR-2
        self.assertIn("PR-2", sup)   # fully replaced by PR-3
        self.assertNotIn("PR-3", sup)
        self.assertEqual(sup["PR-1"]["mainly"], "PR-2")

    def test_classify_signal_priority(self):
        prs = self._saga()
        res = replay(prs)
        units = [dict(unit_id=p["unit_id"], raw_title=p["raw_title"], title=p["raw_title"],
                      merged=1, looks_revert=0, lines_added=30, lines_deleted=30)
                 for p in prs]
        units[1]["raw_title"] = "fix: palette pass 2"   # PR-2 → explicit beats self_correction
        out = classify(units, res, CONFIG)["classifications"]
        self.assertEqual(out["PR-2"]["signal"], "explicit")
        self.assertEqual(out["PR-3"]["signal"], "self_correction")
        self.assertEqual(out["PR-1"]["classification"], "generative")
        self.assertEqual(out["PR-1"].get("superseded_by"), "PR-2")
        self.assertEqual(out["DOC-1"]["classification"], "generative")
        self.assertEqual(out["DOC-3"]["classification"], "generative")  # cadence ≠ churn


if __name__ == "__main__":
    unittest.main()
