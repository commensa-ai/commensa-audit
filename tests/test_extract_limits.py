"""Extraction-limiting tests — --since / --max-prs selection + parser.

No network: a fake requests.Session serves canned /pulls list pages
(newest-first, as the real API does for sort=created&direction=desc) and
records the calls + params so we can assert the early-stop behaviour that
makes large-repo audits cheap.
"""

import unittest

from commensa_audit.extractors.github import GitHubExtractor
from commensa_audit.cli import (build_parser, _since_date, _non_negative_int,
                                DEFAULT_MAX_PRS)


class _Resp:
    def __init__(self, payload, next_url=None):
        self.status_code = 200
        self._payload = payload
        self.links = {"next": {"url": next_url}} if next_url else {}
        self.headers = {}
        self.text = ""

    def json(self):
        return self._payload


class _FakeSession:
    """Serves `prs_desc` (newest-first) in pages; records every get()."""

    def __init__(self, prs_desc, page_size=100):
        self.headers = {}
        self.calls = []  # (url, params) per HTTP round-trip
        self.pages = [prs_desc[i:i + page_size]
                      for i in range(0, len(prs_desc), page_size)] or [[]]

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params) if params else None))
        idx = int(url.split(":")[1]) if url.startswith("next:") else 0
        nxt = f"next:{idx + 1}" if idx + 1 < len(self.pages) else None
        return _Resp(self.pages[idx], nxt)


# newest-first, as sort=created&direction=desc returns
PRS = [
    {"number": 250, "created_at": "2026-06-10T09:00:00Z"},
    {"number": 240, "created_at": "2026-06-05T09:00:00Z"},
    {"number": 230, "created_at": "2026-06-01T00:00:00Z"},
    {"number": 220, "created_at": "2026-05-20T09:00:00Z"},
    {"number": 210, "created_at": "2026-04-01T09:00:00Z"},
]


def _extractor(prs=PRS, page_size=100):
    sess = _FakeSession(prs, page_size=page_size)
    ext = GitHubExtractor("acme/widgets", session=sess)
    return ext, sess


class TestSelectPullNumbers(unittest.TestCase):
    def test_default_is_unchanged_all_ascending_no_sort_params(self):
        ext, sess = _extractor()
        self.assertEqual(ext.select_pull_numbers(), [210, 220, 230, 240, 250])
        # default path must NOT alter the request (Gate A reproducibility)
        _, params = sess.calls[0]
        self.assertEqual(params, {"state": "all", "per_page": 100})
        self.assertEqual(ext.list_pull_numbers(), [210, 220, 230, 240, 250])

    def test_max_prs_keeps_newest_and_sets_desc_sort(self):
        ext, sess = _extractor()
        self.assertEqual(ext.select_pull_numbers(max_prs=2), [240, 250])  # newest 2
        _, params = sess.calls[0]
        self.assertEqual(params["sort"], "created")
        self.assertEqual(params["direction"], "desc")

    def test_since_is_inclusive_and_excludes_older(self):
        ext, _ = _extractor()
        # 2026-06-01 PR (230) is on the boundary → included; 220/210 older → out
        self.assertEqual(ext.select_pull_numbers(since="2026-06-01"), [230, 240, 250])

    def test_since_and_max_prs_combine(self):
        ext, _ = _extractor()
        self.assertEqual(
            ext.select_pull_numbers(since="2026-01-01", max_prs=2), [240, 250])

    def test_max_prs_early_stops_pagination(self):
        # page_size=2 ⇒ 3 pages; cap 3 must stop after page 2, never fetch page 3
        ext, sess = _extractor(page_size=2)
        self.assertEqual(ext.select_pull_numbers(max_prs=3), [230, 240, 250])
        self.assertEqual(len(sess.calls), 2)
        self.assertEqual(ext.requests, 2)

    def test_since_early_stops_pagination(self):
        ext, sess = _extractor(page_size=2)
        # page1=[250,240], page2=[230,220]→220 is older than since ⇒ stop, no page3
        self.assertEqual(ext.select_pull_numbers(since="2026-06-01"), [230, 240, 250])
        self.assertEqual(len(sess.calls), 2)

    def test_max_prs_zero_means_no_cap(self):
        ext, _ = _extractor()
        self.assertEqual(ext.select_pull_numbers(max_prs=0),
                         [210, 220, 230, 240, 250])  # 0 = unlimited
        self.assertFalse(ext.capped)

    def test_capped_true_when_truncated(self):
        ext, _ = _extractor()  # 5 PRs, cap 2 ⇒ truncated
        ext.select_pull_numbers(max_prs=2)
        self.assertTrue(ext.capped)

    def test_capped_false_when_cap_equals_repo_size(self):
        ext, _ = _extractor()  # exactly 5 PRs, cap 5 ⇒ nothing truncated
        ext.select_pull_numbers(max_prs=5)
        self.assertFalse(ext.capped)

    def test_capped_false_on_unlimited(self):
        ext, _ = _extractor()
        ext.select_pull_numbers()
        self.assertFalse(ext.capped)


class TestParser(unittest.TestCase):
    def test_defaults_since_none_max_prs_capped(self):
        args = build_parser().parse_args(["--repo", "a/b"])
        self.assertIsNone(args.since)
        self.assertEqual(args.max_prs, DEFAULT_MAX_PRS)  # sane default cap
        self.assertEqual(DEFAULT_MAX_PRS, 500)

    def test_max_prs_zero_parses(self):
        args = build_parser().parse_args(["--repo", "a/b", "--max-prs", "0"])
        self.assertEqual(args.max_prs, 0)  # explicit "no cap"

    def test_max_prs_validator_rejects_negative(self):
        with self.assertRaises(Exception):
            _non_negative_int("-5")
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["--repo", "a/b", "--max-prs", "-1"])

    def test_valid_flags_parse(self):
        args = build_parser().parse_args(
            ["--repo", "a/b", "--since", "2026-03-01", "--max-prs", "150"])
        self.assertEqual(args.since, "2026-03-01")
        self.assertEqual(args.max_prs, 150)

    def test_since_validator_rejects_bad_date(self):
        with self.assertRaises(Exception):
            _since_date("03/01/2026")
        with self.assertRaises(Exception):
            _since_date("2026-13-40")

    def test_bad_since_exits(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["--repo", "a/b", "--since", "yesterday"])


if __name__ == "__main__":
    unittest.main()
