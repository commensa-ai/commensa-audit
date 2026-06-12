"""Phase C report tests — render correctness + guardrails."""

import re
import unittest

from commensa_audit.report import honest_limits, render


def _fixture():
    units = [
        dict(unit_id="PR-1", title="feat: thing", raw_title="feat: thing", merged=1,
             lines_added=100, lines_deleted=5, changed_files=2, looks_revert=0),
        dict(unit_id="PR-2", title="fix: thing <broken>", raw_title="fix: thing <broken>",
             merged=1, lines_added=30, lines_deleted=25, changed_files=1, looks_revert=0),
    ]
    audit = dict(
        repo="acme/widgets", window_days=14,
        rework_tax=dict(pct_prs_corrective=50.0, pct_changed_lines_corrective=34.4,
                        corrective_prs=1, total_prs=2,
                        by_signal={"explicit": 1},
                        estimated_rework_cost_usd=400.0,
                        estimate_basis="--cost-per-pr 400.0 × 1 corrective PRs"),
        churn_clusters=[], supersessions={"PR-1": dict(by=["PR-2"], lines=60,
                                                       frac=0.6, mainly="PR-2")},
        survival=dict(method="line-attribution replay", overall_rate=0.7,
                      median_rate=0.7, per_unit={"PR-1": 0.4, "PR-2": 1.0}),
        velocity_context=dict(prs_per_week=2.0, merge_rate=100.0,
                              size_lines_added=dict(p25=30, median=65, p75=100, max=100),
                              note="context only — velocity is never a target (LOC trap)"),
        abandoned=dict(count=1, pct_of_prs=50.0, units=["PR-9"], in_flight_open_prs=1,
                       method="PRs closed without merging (GitHub state=closed, merged_at null)."),
        hotspots=dict(top=[dict(dir="frontend", prs=6, corrective=3, pct_corrective=50.0)],
                      min_prs=5, suppressed_dirs=2,
                      method="corrective share of PRs touching each top-level directory."),
        ai_marked=dict(count=1, pct_of_prs_lower_bound=50.0,
                       per_unit={"PR-2": ["commit trailer: Co-Authored-By: Claude <noreply@anthropic.com>"]},
                       method="PRs with ≥1 agent marker. Lower bound — absence of a "
                              "marker is not evidence of human authorship."),
        external_norms=dict(metric="Code Turnover Rate — share of merged code reverted/rewritten within 30 days",
                            healthy="< 15%", ai_vs_human="AI-assisted teams measured at 1.8–2.5× human baselines (target < 1.5×)",
                            label="external published research, not a Commensa benchmark; methods differ from the rework tax above"),
        classifications={"PR-1": dict(classification="generative", signal=None, detail="",
                                      superseded_by="PR-2", superseded_frac=0.6),
                         "PR-2": dict(classification="corrective", signal="explicit",
                                      detail="title token 'fix'")},
        config={}, confidence_notes=[],
    )
    return audit, units


class TestReport(unittest.TestCase):
    def setUp(self):
        audit, units = _fixture()
        self.html = render(audit, units)

    def test_two_line_waste_headline_never_merged(self):
        self.assertIn("Rework tax", self.html)
        self.assertIn("Superseded", self.html)
        self.assertIn("never merged", self.html)

    def test_brand_and_cta(self):
        self.assertIn("measure the durable work, not the noise.", self.html)
        self.assertIn('href="https://commensa.ai"', self.html)
        self.assertIn("Durable Equals", self.html)   # the mark's aria-label
        self.assertIn("#18a06b", self.html)          # brand teal
        self.assertIn("#1d2b4d", self.html)          # brand ink

    def test_self_contained_no_external_resources(self):
        # no scripts, no external fetches; the only https URL is the CTA link
        self.assertNotIn("<script", self.html)
        for url in re.findall(r'(?:src|href)="(http[^"]+)"', self.html):
            self.assertEqual(url, "https://commensa.ai")

    def test_dollar_line_labeled_estimate(self):
        self.assertIn("400", self.html)
        self.assertIn("estimate", self.html.lower())

    def test_titles_escaped(self):
        self.assertNotIn("<broken>", self.html)
        self.assertIn("&lt;broken&gt;", self.html)

    def test_honest_limits_sourced_from_rework_docstring(self):
        limits = honest_limits()
        self.assertGreaterEqual(len(limits), 5)
        for l in limits[:3]:
            self.assertIn(l, self.html)
        self.assertTrue(any("squash" in l.lower() or "direct" in l.lower() for l in limits))

    def test_empty_states_render(self):
        audit, units = _fixture()
        audit["churn_clusters"] = []
        audit["supersessions"] = {}
        audit["hotspots"]["top"] = []
        audit["rework_tax"].pop("estimated_rework_cost_usd")
        h = render(audit, units)
        self.assertIn("No churn clusters", h)
        self.assertIn("No PR had a majority", h)
        self.assertIn("repo too small for module-level hotspots", h)

    def test_zero_pr_survival_honest_in_all_three_surfaces(self):
        # Regression (S7 smoke find): a 0-merged-line repo must read "no data",
        # never "0% survived". S6 fixed only the headline; the Evidence·survival
        # panel (report.py) and the CLI summary (cli.py) still printed "0.0% overall"
        # / "survival: 0%", which reads as "everything was discarded" — the opposite.
        from commensa_audit.cli import _survival_summary
        audit, _ = _fixture()
        units = []  # 0-PR repo: no merged-line attribution exists
        audit["classifications"] = {}
        audit["churn_clusters"] = []
        audit["supersessions"] = {}
        audit["hotspots"]["top"] = []
        audit["rework_tax"].update(total_prs=0, corrective_prs=0,
                                   pct_prs_corrective=0.0, pct_changed_lines_corrective=0.0)
        audit["rework_tax"].pop("estimated_rework_cost_usd", None)
        audit["abandoned"].update(count=0, pct_of_prs=0.0, units=[], in_flight_open_prs=0)
        audit["ai_marked"].update(count=0, pct_of_prs_lower_bound=0.0, per_unit={})
        audit["velocity_context"].update(prs_per_week=0.0, merge_rate=0.0,
                                         size_lines_added=dict(p25=0, median=0, p75=0, max=0))
        # the 0/1 fallback overall_rate is exactly what made "0%" leak
        audit["survival"].update(overall_rate=0.0, median_rate=None, per_unit={})

        honest = "no merged PR lines to measure yet"
        h = render(audit, units)
        # Surfaces 1 (headline) + 2 (Evidence·survival panel): both honest, no percent claim
        self.assertEqual(h.count(honest), 2,
                         "honest empty-state must appear in BOTH report survival surfaces")
        # the survival panel's "<b>X%</b> overall · median per-PR …" phrasing must be gone:
        # 'overall' appears only there, so its absence proves no percent-survival claim remains
        self.assertNotIn("overall", h)

        # Surface 3: CLI stdout summary
        summary = _survival_summary(audit["survival"])
        self.assertEqual(summary, f"overall line survival: {honest}")
        self.assertNotIn("0%", summary)

        # guard the other direction — the normal (has-lines) path still shows the percent
        self.assertIn("overall", self.html)   # renders "<b>70.0%</b> overall · median per-PR 70%"
        self.assertEqual(_survival_summary({"per_unit": {"PR-1": 0.7}, "overall_rate": 0.7}),
                         "overall line survival: 70%")

    # ---- v1.1 additions ----

    def test_abandoned_line_in_headline_area(self):
        self.assertIn("shipped nothing", self.html)
        self.assertIn("closed without merging", self.html)
        # headline area = before the durable strip
        self.assertLess(self.html.index("shipped nothing"),
                        self.html.index("what the agents generated"))

    def test_ai_marked_is_labeled_lower_bound(self):
        self.assertIn("at least 50.0%", self.html)
        self.assertIn("absence of a marker", self.html)

    def test_hotspots_panel(self):
        self.assertIn("hotspots — where the rework concentrates", self.html.lower())
        self.assertIn("frontend", self.html)
        self.assertIn("suppressed as noise", self.html)

    def test_norms_labeled_external(self):
        self.assertIn("Code Turnover Rate", self.html)
        self.assertIn("not a Commensa benchmark", self.html)

    def test_new_methods_in_footer(self):
        foot = self.html[self.html.index("Method &amp; confidence"):]
        for needle in ("closed without merging", "top-level directory", "Lower bound"):
            self.assertIn(needle, foot)


if __name__ == "__main__":
    unittest.main()
