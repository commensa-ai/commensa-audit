"""v1.1 unit tests — markers, abandoned, hotspots aggregation."""

import unittest

from commensa_audit.cli import _abandoned, _ai_marked, _hotspots
from commensa_audit.markers import detect_markers


class TestMarkers(unittest.TestCase):
    def test_claude_code_trailer(self):
        msgs = ["fix: thing\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>"]
        found = detect_markers(None, msgs)
        self.assertEqual(len(found), 1)
        self.assertIn("Co-Authored-By", found[0])

    def test_human_coauthor_not_flagged(self):
        msgs = ["feat: thing\n\nCo-Authored-By: Jane Doe <jane@example.com>"]
        self.assertEqual(detect_markers(None, msgs), [])

    def test_body_signature(self):
        body = "Adds X.\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)"
        found = detect_markers(body, [])
        self.assertTrue(found)

    def test_copilot_and_dedup(self):
        msgs = ["a\n\nCo-authored-by: GitHub Copilot <copilot@github.com>",
                "b\n\nco-authored-by: GitHub Copilot <copilot@github.com>"]
        self.assertEqual(len(detect_markers(None, msgs)), 1)

    def test_clean_pr(self):
        self.assertEqual(detect_markers("normal PR description", ["normal commit"]), [])


def _mk(uid, merged, state, files=(), markers=()):
    unit = dict(unit_id=uid, merged=merged)
    side = dict(unit_id=uid, state=state, ai_markers=list(markers),
                files=[dict(filename=f) for f in files])
    return unit, side


class TestAggregations(unittest.TestCase):
    def setUp(self):
        rows = [
            _mk("PR-1", 1, "closed", ["frontend/a.tsx"], ["body: generated with claude"]),
            _mk("PR-2", 0, "closed", ["frontend/b.tsx"]),          # abandoned
            _mk("PR-3", 0, "open", ["backend/c.php"]),             # in flight
            _mk("PR-4", 1, "closed", ["README.md"]),               # root file
        ]
        self.units = [u for u, _ in rows]
        self.side = {s["unit_id"]: s for _, s in rows}

    def test_abandoned_counts_closed_unmerged_only(self):
        a = _abandoned(self.units, self.side)
        self.assertEqual(a["units"], ["PR-2"])
        self.assertEqual(a["in_flight_open_prs"], 1)
        self.assertEqual(a["pct_of_prs"], 25.0)

    def test_ai_marked_lower_bound(self):
        m = _ai_marked(self.units, self.side)
        self.assertEqual(m["count"], 1)
        self.assertEqual(m["pct_of_prs_lower_bound"], 25.0)

    def test_hotspots_min_prs_and_multi_dir(self):
        cls = {u["unit_id"]: dict(classification="corrective" if u["unit_id"] == "PR-1"
                                  else "generative") for u in self.units}
        h = _hotspots(self.units, cls, self.side, min_prs=2, top_n=5)
        self.assertEqual(len(h["top"]), 1)               # only frontend has ≥2 PRs
        top = h["top"][0]
        self.assertEqual((top["dir"], top["prs"], top["pct_corrective"]),
                         ("frontend", 2, 50.0))
        self.assertEqual(h["suppressed_dirs"], 2)        # backend, (root)

    def test_hotspots_default_threshold_suppresses_noise(self):
        cls = {u["unit_id"]: dict(classification="generative") for u in self.units}
        h = _hotspots(self.units, cls, self.side)        # min_prs=5
        self.assertEqual(h["top"], [])


class TestZeroPrRepo(unittest.TestCase):
    """Audit-the-auditor regression: a 0-PR repo audits to zeros, not a crash."""

    def test_empty_pipeline_and_render(self):
        import argparse
        from commensa_audit.classify import CONFIG, classify
        from commensa_audit.cli import _aggregate
        from commensa_audit.report import render
        from commensa_audit.rework import replay

        res = replay([])
        result = classify([], res, CONFIG)
        args = argparse.Namespace(repo="x/empty", window=14,
                                  cost_per_pr=None, ai_spend=None)
        audit = _aggregate([], res, result, args, [])
        self.assertEqual(audit["rework_tax"]["total_prs"], 0)
        self.assertEqual(audit["rework_tax"]["pct_prs_corrective"], 0.0)
        html = render(audit, [])
        self.assertIn("0 PRs", html)


if __name__ == "__main__":
    unittest.main()
