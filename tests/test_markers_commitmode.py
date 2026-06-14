"""Phase M-A — commit-mode marker test corpus.

Each test builds a synthetic temp git repo with a specific marker scenario
and asserts the extractor's sidecar flags it (or, for negative cases,
doesn't). Marker detection had ZERO commit-mode test coverage before M-A
— that's why the subject-only body-scan bug shipped. These tests lock
the surface for future refactors.

Scenarios covered (one synthetic repo per case unless noted):
  body trailer (subject + body)                   — agent ✓
  Unicode body trailer (café/emoji content)       — agent ✓
  subject-only (no body)                          — clean ✗
  multi-model Claude ladder (4.5/4.6/4.7/4.8)     — agent + correct version
  Assisted-by trailer                             — agent ✓ (NEW trailer key)
  Generated-by trailer                            — agent ✓ (NEW trailer key)
  On-behalf-of trailer                            — agent ✓ (NEW trailer key)
  agent-as-author (Cursor <noreply@cursor.com>)   — agent ✓ via identity scan
  agent-as-committer (Copilot[bot])               — agent ✓ via identity scan
  GitHub <noreply@github.com> web-UI committer    — NOT flagged (negative)
  human Co-Authored-By                            — NOT flagged (negative)
  body signature "Generated with Claude Code"     — agent ✓
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from commensa_audit.extractors.local_clone import LocalCloneExtractor


def _git(repo, *args, **kw):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True, **kw,
    ).stdout


def _make_repo():
    d = tempfile.mkdtemp(prefix="commensa_m_a_")
    p = Path(d)
    _git(p, "init", "-q", "-b", "main")
    _git(p, "config", "user.name", "Test User")
    _git(p, "config", "user.email", "test@example.com")
    _git(p, "config", "commit.gpgsign", "false")
    return p


def _commit(repo, message, files=None, author=None, committer_env=None):
    """Make a commit with optional author / committer identity overrides.

    `author` is passed to git's --author. `committer_env` overrides
    GIT_COMMITTER_NAME and GIT_COMMITTER_EMAIL via environment.
    """
    for path, content in (files or {"f.txt": "x\n"}).items():
        full = repo / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content) if isinstance(content, str) else full.write_bytes(content)
        _git(repo, "add", path)
    cmd = ["commit", "-q", "-m", message]
    if author:
        cmd.append(f"--author={author}")
    env = None
    if committer_env:
        import os
        env = {**os.environ, **committer_env}
    _git(repo, *cmd, env=env)


def _sidecar_markers(repo):
    """Return list of sidecar markers per commit, newest-first."""
    return [side["ai_markers"]
            for _, side in LocalCloneExtractor(repo).units(with_files=True)]


def _sidecar_models(repo):
    return [side["ai_model"]
            for _, side in LocalCloneExtractor(repo).units(with_files=True)]


class TestPositiveMarkers(unittest.TestCase):
    """Cases the M-A detector MUST flag."""

    def test_co_authored_by_in_body(self):
        repo = _make_repo()
        _commit(repo, "feat: thing\n\nCo-Authored-By: Claude Opus 4.6 "
                      "<noreply@anthropic.com>")
        markers = _sidecar_markers(repo)[0]
        self.assertTrue(markers, "body trailer must flag agent")
        self.assertTrue(any("Co-Authored-By" in m for m in markers))

    def test_assisted_by_trailer(self):
        repo = _make_repo()
        _commit(repo, "feat: x\n\nAssisted-by: Cursor <noreply@cursor.com>")
        self.assertTrue(_sidecar_markers(repo)[0])

    def test_generated_by_trailer(self):
        repo = _make_repo()
        _commit(repo, "feat: y\n\nGenerated-by: Aider <aider@example.com>")
        self.assertTrue(_sidecar_markers(repo)[0])

    def test_on_behalf_of_trailer(self):
        repo = _make_repo()
        _commit(repo, "feat: z\n\nOn-behalf-of: Devin <devin@cognition.ai>")
        self.assertTrue(_sidecar_markers(repo)[0])

    def test_unicode_body_trailer(self):
        """Non-ASCII body content must not break trailer detection."""
        repo = _make_repo()
        _commit(repo, "fix: café résumé\n\nDetails: 結果 ✓ 🎉\n\n"
                      "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>")
        self.assertTrue(_sidecar_markers(repo)[0])

    def test_body_signature_only(self):
        repo = _make_repo()
        _commit(repo, "tweak\n\n🤖 Generated with [Claude Code]")
        self.assertTrue(_sidecar_markers(repo)[0])

    def test_agent_as_author_via_identity_scan(self):
        repo = _make_repo()
        _commit(repo, "robot work", author="Cursor Bot <noreply@cursor.com>")
        markers = _sidecar_markers(repo)[0]
        self.assertTrue(markers, "author identity matching agent must flag")
        self.assertTrue(any("author identity" in m for m in markers),
                        f"expected author-identity marker, got {markers}")

    def test_agent_as_committer_via_identity_scan(self):
        repo = _make_repo()
        _commit(repo, "auto-update",
                committer_env={"GIT_COMMITTER_NAME": "dependabot[bot]",
                               "GIT_COMMITTER_EMAIL": "dependabot[bot]@users.noreply.github.com"})
        markers = _sidecar_markers(repo)[0]
        self.assertTrue(markers)
        self.assertTrue(any("committer identity" in m for m in markers))


class TestNegativeMarkers(unittest.TestCase):
    """Cases that MUST NOT flag (the false-positive guardrails)."""

    def test_github_web_ui_committer_is_human(self):
        """The 11 web-UI commits in theo MUST stay unflagged. Platform
        exclusion runs BEFORE the agent allowlist, so `[bot]` matching
        inside `noreply@github.com` can't false-positive."""
        repo = _make_repo()
        _commit(repo, "doc fix via web UI",
                committer_env={"GIT_COMMITTER_NAME": "GitHub",
                               "GIT_COMMITTER_EMAIL": "noreply@github.com"})
        self.assertEqual(_sidecar_markers(repo)[0], [],
                         "GitHub <noreply@github.com> must NOT flag agent")

    def test_human_co_authored_by(self):
        repo = _make_repo()
        _commit(repo, "feat\n\nCo-Authored-By: Robyn Brister <robyn@example.com>")
        self.assertEqual(_sidecar_markers(repo)[0], [],
                         "human co-author must NOT flag agent")

    def test_clean_commit(self):
        repo = _make_repo()
        _commit(repo, "ordinary feature work")
        self.assertEqual(_sidecar_markers(repo)[0], [])

    def test_subject_only_with_fix(self):
        """A 'fix:' subject without any marker is human refactoring, not AI."""
        repo = _make_repo()
        _commit(repo, "fix: typo in readme")
        self.assertEqual(_sidecar_markers(repo)[0], [])


class TestModelLadder(unittest.TestCase):
    """Structured model extraction. theo's ladder is 4.5/4.6/4.7/4.8 across
    Claude Opus — this proves we recover all four versions."""

    def test_claude_opus_ladder(self):
        repo = _make_repo()
        # commit oldest first; LocalCloneExtractor yields newest first
        _commit(repo, "v1\n\nCo-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>",
                files={"a.txt": "1\n"})
        _commit(repo, "v2\n\nCo-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>",
                files={"a.txt": "1\n2\n"})
        _commit(repo, "v3\n\nCo-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>",
                files={"a.txt": "1\n2\n3\n"})
        _commit(repo, "v4\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>",
                files={"a.txt": "1\n2\n3\n4\n"})
        models = _sidecar_models(repo)
        # newest first: 4.8, 4.7, 4.6, 4.5
        versions = [m.get("version") for m in models]
        self.assertEqual(versions, ["4.8", "4.7", "4.6", "4.5"])
        for m in models:
            self.assertEqual(m.get("family"), "claude")
            self.assertEqual(m.get("tier"), "opus")

    def test_no_marker_no_model(self):
        repo = _make_repo()
        _commit(repo, "clean human work")
        self.assertIsNone(_sidecar_models(repo)[0])

    def test_marker_without_version_yields_family_only(self):
        repo = _make_repo()
        _commit(repo, "x\n\nCo-Authored-By: GitHub Copilot <copilot@github.com>")
        m = _sidecar_models(repo)[0]
        self.assertEqual(m.get("family"), "copilot")
        self.assertNotIn("version", m)


class TestMixedAndPriority(unittest.TestCase):
    def test_multiple_signals_dedup_to_single_marker_set(self):
        """When both author identity AND a body trailer flag the same agent,
        we collect BOTH marker strings (they're distinct evidence) but
        the model field resolves to one (first hit wins)."""
        repo = _make_repo()
        _commit(repo, "x\n\nCo-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>",
                author="Cursor Bot <noreply@cursor.com>")
        markers = _sidecar_markers(repo)[0]
        # both signal sources present
        self.assertTrue(any("author identity" in m for m in markers))
        self.assertTrue(any("Co-Authored-By" in m for m in markers))


if __name__ == "__main__":
    unittest.main()
